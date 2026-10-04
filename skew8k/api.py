"""Cached Massive REST client. Key from MASSIVE_API_KEY (environment or .env); responses cached in SQLite under MASSIVE_CACHE
(default .massive_cache). Reads are lock-free; each process writes its own shard file, so parallel runs never block each other."""
import hashlib, json, os, sqlite3, threading, time
from pathlib import Path
import requests

BASE_URL = "https://api.massive.com"
CACHE = Path(os.environ.get("MASSIVE_CACHE", ".massive_cache")).resolve() / "requests.sqlite"
SHARD = CACHE.with_name(f"requests_shard_{os.getpid()}.sqlite")
_lock, _local, _pending, _started = threading.Lock(), threading.local(), {}, []
SESSION = requests.Session()


def _key():
    k = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not k and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.strip().startswith("MASSIVE_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        raise RuntimeError("Set MASSIVE_API_KEY (environment or .env)")
    return k


def _writer():
    db = sqlite3.connect(SHARD, timeout=120, check_same_thread=False)
    db.execute("PRAGMA synchronous=OFF"); db.execute("CREATE TABLE IF NOT EXISTS r (k TEXT PRIMARY KEY, v BLOB)"); db.commit()
    while True:
        time.sleep(2)
        with _lock:
            batch = list(_pending.items())
        if batch:
            db.executemany("INSERT OR REPLACE INTO r VALUES (?,?)", batch); db.commit()
            with _lock:
                for k, _ in batch:
                    _pending.pop(k, None)


def flush():
    while _pending:
        time.sleep(0.5)


def _dbs():
    if not hasattr(_local, "dbs"):
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        files = [f for f in [CACHE] + sorted(CACHE.parent.glob("requests_shard_*.sqlite")) if f.exists() and f != SHARD]
        _local.dbs = [sqlite3.connect(f"file:{f}?mode=ro&immutable=1", uri=True, check_same_thread=False) for f in files]
    return _local.dbs


def api_get(path_or_url, params=None):
    """GET one page, cached by full URL; retries rate limits and server errors."""
    if not _started:
        SESSION.headers["Authorization"] = "Bearer " + _key(); threading.Thread(target=_writer, daemon=True).start(); _started.append(1)
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    full = requests.Request("GET", url, params=params).prepare().url
    k = hashlib.sha1(full.encode()).hexdigest()
    with _lock:
        hit = _pending.get(k)
    if hit is not None:
        return json.loads(hit)
    for db in _dbs():
        try:
            row = db.execute("SELECT v FROM r WHERE k=?", (k,)).fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row:
            return json.loads(row[0])
    for attempt in range(10):
        try:
            resp = SESSION.get(full, timeout=60)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 20)); continue
        break
    resp.raise_for_status(); payload = resp.json()
    with _lock:
        _pending[k] = json.dumps(payload)
    return payload


def api_get_all(path, params=None, max_pages=500):
    payload = api_get(path, params); rows = list(payload.get("results") or []); pages = 1
    while payload.get("next_url") and pages < max_pages:
        payload = api_get(payload["next_url"]); rows += payload.get("results") or []; pages += 1
    return rows
