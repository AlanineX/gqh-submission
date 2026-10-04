"""Cached Massive REST access: one compressed SQLite cache file (WAL), shared token-bucket rate gate, thread-safe.
Starter-notebook semantics: responses keyed by full URL; next_url pagination followed; truncation raises."""
import atexit, hashlib, json, os, queue, sqlite3, threading, time, zlib
from pathlib import Path
import requests

BASE_URL = "https://api.massive.com"
CACHE_DIR = Path(os.environ.get("K8_CACHE", str(Path(__file__).resolve().parents[1] / ".massive_cache"))).resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB = CACHE_DIR / os.environ.get("K8_DB", "requests.sqlite")
RATE = float(os.environ.get("K8_RATE", "200"))
_local, _wlock, _glock = threading.local(), threading.Lock(), threading.Lock()
_next = [0.0]
_pending, _q = {}, queue.Queue()


def _writer():
    """Single writer: batch inserts, commit about once per second (avoids a disk sync per response)."""
    con = sqlite3.connect(DB, timeout=120); con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
    con.execute("CREATE TABLE IF NOT EXISTS r (k TEXT PRIMARY KEY, v BLOB)"); con.commit()
    while True:
        batch = [_q.get()]
        t = time.monotonic()
        while time.monotonic() - t < 1.0 and len(batch) < 2000:
            try:
                batch.append(_q.get(timeout=0.1))
            except queue.Empty:
                pass
        stop = None in batch
        rows = [b for b in batch if b is not None]
        if rows:
            con.executemany("INSERT OR REPLACE INTO r VALUES (?, ?)", rows); con.commit()
            for k, _ in rows:
                _pending.pop(k, None)
        if stop:
            return


for _i in range(30):
    try:
        _c0 = sqlite3.connect(DB, timeout=120); _c0.execute("CREATE TABLE IF NOT EXISTS r (k TEXT PRIMARY KEY, v BLOB)"); _c0.commit()
        if _c0.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            _c0.execute("PRAGMA journal_mode=WAL")
        _c0.close(); break
    except sqlite3.OperationalError:
        time.sleep(2)
_wt = threading.Thread(target=_writer, daemon=True); _wt.start()


@atexit.register
def _flush():
    _q.put(None); _wt.join(timeout=120)


def _key() -> str:
    """MASSIVE_API_KEY from the environment, else from .env beside the package (starter-notebook convention)."""
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    env = Path(__file__).resolve().parents[1] / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("MASSIVE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("Set MASSIVE_API_KEY in the environment or in .env")
    return key




def _db():
    c = getattr(_local, "db", None)
    if c is None:
        c = _local.db = sqlite3.connect(DB, timeout=60, check_same_thread=False)
    return c


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
        s.headers["Authorization"] = f"Bearer {_key()}"
        a = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=4); s.mount("https://", a)
    return s


def _gate():
    with _glock:
        now = time.monotonic(); t = max(now, _next[0]); _next[0] = t + 1.0 / RATE
    if t > now:
        time.sleep(t - now)


def api_get(path_or_url: str, params: dict | None = None) -> dict:
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    full = requests.Request("GET", url, params=params).prepare().url
    k = hashlib.sha1(full.encode()).hexdigest()
    if k in _pending:
        return json.loads(zlib.decompress(_pending[k]))
    row = _db().execute("SELECT v FROM r WHERE k=?", (k,)).fetchone()
    if row:
        return json.loads(zlib.decompress(row[0]))
    r = None
    for attempt in range(10):
        _gate()
        try:
            r = _session().get(full, timeout=60)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 20)); continue
        break
    r.raise_for_status()
    payload = json.loads(r.content)
    blob = zlib.compress(r.content, 1)              # raw bytes: no re-serialization
    _pending[k] = blob; _q.put((k, blob))
    return payload


def api_get_all(path: str, params: dict | None = None, max_pages: int = 500) -> list[dict]:
    payload = api_get(path, params)
    rows, pages = list(payload.get("results") or []), 1
    while payload.get("next_url"):
        if pages >= max_pages:
            raise RuntimeError(f"pagination truncated at {max_pages} pages: {path}")
        payload = api_get(payload["next_url"]); rows += payload.get("results") or []; pages += 1
    return rows
