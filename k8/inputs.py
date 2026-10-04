"""Portable Massive-only input builder for the filing-aware options study.

For each (ticker, session) it reproduces the archive construction used in research:
  * spot = close of the last completed minute before the valuation clock (close - 5 min, 15:55 ET normally);
  * ~180-calendar-day expiry nearest to 180 days among listed standard contracts (as_of the session);
  * ATM strike = paired strike nearest spot; latest valid NBBO within 300 s, quote age <= 60 s;
  * American IV (QuantLib FD, continuous carry) via the portable `k8.options_pricing` module;
  * carry: prior-date Treasury CMT (log-discount interpolation), trailing-365-day paid cash dividend yield;
  * put/call volume ratio over every standard strike of the selected expiry (daily aggregates);
  * close-window total return: 15:56 -> next 15:56 split-adjusted minute close, plus cash dividends on ex-dates.
Only Massive REST endpoints are used."""
import math, os, subprocess, sys, tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import numpy as np
import pandas as pd
import exchange_calendars as xc
from .api import api_get, api_get_all

CAL = xc.get_calendar("XNYS")
NY = "America/New_York"
TENORS = {"yield_1_month": 1, "yield_2_month": 2, "yield_3_month": 3, "yield_4_month": 4, "yield_6_month": 6, "yield_1_year": 12,
          "yield_2_year": 24, "yield_3_year": 36, "yield_5_year": 60, "yield_7_year": 84, "yield_10_year": 120}


def sessions(start, end):
    return [d.strftime("%Y-%m-%d") for d in CAL.sessions_in_range(start, end)]


def clock(day, minutes_before_close):
    return CAL.session_close(pd.Timestamp(day)) - pd.Timedelta(minutes=minutes_before_close)


def minute_closes(ticker, start, end, adjusted):
    """Last trade before close-5min (decision spot, 15:55 ET) per session, from 5-minute bars: the bar starting at
    close-10min closes at close-5min, equal to the 1-minute bar ending at close-5min. Execution uses the same price
    (the research archive used 15:56; one minute apart)."""
    days = sessions(start, end); out = {}
    months = pd.period_range(pd.Timestamp(days[0]), pd.Timestamp(days[-1]), freq="M")
    rows = []
    for m in months:
        a, b = max(m.start_time, pd.Timestamp(start)), min(m.end_time, pd.Timestamp(end))
        rows += api_get_all(f"/v2/aggs/ticker/{ticker}/range/5/minute/{a:%Y-%m-%d}/{b:%Y-%m-%d}", {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000})
    if not rows:
        return pd.DataFrame(columns=["spot", "exec"])
    t = pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True)
    s = pd.Series([r["c"] for r in rows], index=t)
    for d in days:
        c5 = clock(d, 5)
        w5 = s[(s.index >= c5 - pd.Timedelta(minutes=35)) & (s.index <= c5 - pd.Timedelta(minutes=5))]   # 5-min bar starting at t closes at t+5
        v = w5.iloc[-1] if len(w5) else np.nan
        out[d] = (v, v)
    return pd.DataFrame.from_dict(out, orient="index", columns=["spot", "exec"])


def treasury(start, end):
    rows = api_get_all("/fed/v1/treasury-yields", {"date.gte": start, "date.lte": end, "limit": 50000, "sort": "date.asc"})
    return pd.DataFrame(rows).set_index("date").sort_index()


def rate_for(ty, day, expiry):
    prior = ty[ty.index < day]
    if prior.empty or (pd.Timestamp(day) - pd.Timestamp(prior.index[-1])).days > 7:
        return np.nan
    row = prior.iloc[-1]; years = (pd.Timestamp(expiry) - pd.Timestamp(day)).days / 365
    nodes = sorted(((pd.Timestamp(day) + pd.DateOffset(months=mo) - pd.Timestamp(day)).days / 365, -2 * math.log1p(row[f] / 200) * ((pd.Timestamp(day) + pd.DateOffset(months=mo) - pd.Timestamp(day)).days / 365))
                   for f, mo in TENORS.items() if f in row and pd.notna(row[f]))
    lo = [n for n in nodes if n[0] <= years]; hi = [n for n in nodes if n[0] >= years]
    if not lo or not hi:
        return np.nan
    lo, hi = lo[-1], hi[0]
    w = 0.0 if hi[0] == lo[0] else (years - lo[0]) / (hi[0] - lo[0])
    return -((1 - w) * lo[1] + w * hi[1]) / years


def dividends(ticker, start, end):
    rows = api_get_all("/v3/reference/dividends", {"ticker": ticker, "ex_dividend_date.gte": start, "ex_dividend_date.lte": end, "limit": 1000})
    d = pd.DataFrame(rows)
    return d[d.dividend_type.isin(["CD", "SC"])] if len(d) else pd.DataFrame(columns=["ex_dividend_date", "pay_date", "declaration_date", "cash_amount"])


def chain(ticker, day, target=180, radius=30):
    rows = api_get_all("/v3/reference/options/contracts", {"underlying_ticker": ticker, "as_of": day, "limit": 1000,
                       "expiration_date.gte": (pd.Timestamp(day) + pd.Timedelta(days=target - radius)).strftime("%Y-%m-%d"),
                       "expiration_date.lte": (pd.Timestamp(day) + pd.Timedelta(days=target + radius)).strftime("%Y-%m-%d")})
    c = pd.DataFrame(rows)
    if c.empty:
        return c
    std = c.get("shares_per_contract", pd.Series(100, index=c.index)).fillna(100).eq(100)
    if "additional_underlyings" in c:
        std &= c.additional_underlyings.isna() | c.additional_underlyings.map(lambda v: not v if isinstance(v, list) else True)
    c = c[std & c.contract_type.isin(["call", "put"])]
    if c.empty:
        return c
    exp = min(sorted(set(c.expiration_date)), key=lambda e: (abs((pd.Timestamp(e) - pd.Timestamp(day)).days - target), e))
    return c[c.expiration_date == exp][["ticker", "contract_type", "strike_price", "expiration_date"]]


def latest_quote(opt, at):
    rows = api_get(f"/v3/quotes/{opt}", {"timestamp.gte": (at - pd.Timedelta(seconds=300)).value, "timestamp.lte": at.value,
                   "order": "desc", "sort": "timestamp", "limit": 50}).get("results") or []
    for q in rows:
        b, a, ts = q.get("bid_price"), q.get("ask_price"), pd.Timestamp(q["sip_timestamp"], unit="ns", tz="UTC")
        if b and a and 0 < b < a:
            age = (at - ts).total_seconds()
            return (b, a, ts) if 0 <= age <= 60 else (np.nan, np.nan, ts)
    return (np.nan, np.nan, None)


def _iv(args):
    from .options_pricing import american_implied_volatility
    mid, S, K, at, exp, r, side, q, cutoff = args
    try:
        res = american_implied_volatility(mid, S, K, at, exp, r, side, [], continuous_dividend_yield=q, research_cutoff=cutoff)
        return res.iv if res.status == "solved" else np.nan
    except Exception:
        return np.nan


def _build(tickers, start, end, workers=6, processes=6):
    """Returns (panel, returns). `start`..`end` are decision sessions; one warm-up month should precede the research window."""
    workers = max(1, min(int(workers), 6))
    processes = max(1, min(int(processes), 6))
    days = sessions(start, end)
    ty = treasury((pd.Timestamp(start) - pd.Timedelta(days=14)).strftime("%Y-%m-%d"), end)
    nxt = end                                   # never request data after the window end
    with ThreadPoolExecutor(workers) as ex:
        spot = dict(zip(tickers, ex.map(lambda t: minute_closes(t, start, nxt, False), tickers)))
        divs = dict(zip(tickers, ex.map(lambda t: dividends(t, (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d"), nxt), tickers)))
        jobs = [(t, d) for t in tickers for d in days]
        chains = dict(zip(jobs, ex.map(lambda j: chain(*j), jobs)))
        rows, quote_jobs = [], []
        for (t, d), c in chains.items():
            S = spot[t].spot.get(d, np.nan)
            row = {"date": d, "ticker": t, "spot": S, "iv_valid": False, "volume_valid": False}
            if c is None or c.empty or not np.isfinite(S):
                rows.append(row); continue
            exp = c.expiration_date.iloc[0]
            paired = c.groupby("strike_price").contract_type.nunique(); ks = paired.index[paired.eq(2)]
            if not len(ks):
                rows.append(row); continue
            K = float(min(ks, key=lambda k: (abs(k - S), k)))
            dv = divs[t]; dd = dv[(dv.ex_dividend_date <= d) & (dv.ex_dividend_date > (pd.Timestamp(d) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")) & (dv.pay_date <= d)] if len(dv) else dv
            row.update(selected_expiry=exp, atm_strike=K, rate=rate_for(ty, d, exp), dividend_yield=float(dd.cash_amount.sum()) / S if len(dd) else 0.0,
                       call_contract=c[(c.strike_price == K) & (c.contract_type == "call")].ticker.iloc[0],
                       put_contract=c[(c.strike_price == K) & (c.contract_type == "put")].ticker.iloc[0], contracts=c)
            rows.append(row)
        at = {d: clock(d, 5) for d in days}
        need = [(i, side) for i, r in enumerate(rows) if "call_contract" in r for side in ("call", "put")]
        quotes = list(ex.map(lambda j: latest_quote(rows[j[0]][f"{j[1]}_contract"], at[rows[j[0]]["date"]]), need))
        # put/call volume of the selected expiry: one daily-aggregate request per contract over its selection span
        span = {}
        for r in rows:
            for opt, kind in zip(r.get("contracts", pd.DataFrame()).get("ticker", []), r.get("contracts", pd.DataFrame()).get("contract_type", [])):
                a, b = span.get(opt, (r["date"], r["date"], kind))[:2]
                span[opt] = (min(a, r["date"]), max(b, r["date"]), kind)
        def vols(opt):
            a, b, _ = span[opt]
            res = api_get_all(f"/v2/aggs/ticker/{opt}/range/1/day/{a}/{b}", {"adjusted": "false", "limit": 50000})
            return {pd.Timestamp(x["t"], unit="ms", tz="UTC").tz_convert(NY).strftime("%Y-%m-%d"): x.get("v", 0) for x in res}
        vol = dict(zip(span, ex.map(vols, list(span))))
    for (i, side), (b, a, ts) in zip(need, quotes):
        rows[i][f"{side}_bid"], rows[i][f"{side}_ask"] = b, a
    iv_jobs = []
    for i, r in enumerate(rows):
        if "call_contract" not in r:
            continue
        c = r.pop("contracts")
        cv = sum(vol[o].get(r["date"], 0) for o in c.ticker[c.contract_type == "call"])
        pv = sum(vol[o].get(r["date"], 0) for o in c.ticker[c.contract_type == "put"])
        r.update(call_total_volume_180=cv, put_total_volume_180=pv, pcr_volume_180=pv / cv if cv > 0 else np.nan, volume_valid=cv > 0)
        if np.isfinite([r.get("call_bid", np.nan), r.get("put_bid", np.nan), r["rate"]]).all():
            for side in ("call", "put"):
                iv_jobs.append((i, side, ((r[f"{side}_bid"] + r[f"{side}_ask"]) / 2, r["spot"], r["atm_strike"], at[r["date"]].isoformat(), r["selected_expiry"], r["rate"], side, r["dividend_yield"], end)))
    with ProcessPoolExecutor(processes) as px:
        ivs = list(px.map(_iv, [j[2] for j in iv_jobs], chunksize=16))
    for (i, side, _), v in zip(iv_jobs, ivs):
        rows[i][f"{side}_iv_180"] = v
    panel = pd.DataFrame(rows)
    for col in ("call_iv_180", "put_iv_180"):
        if col not in panel:
            panel[col] = np.nan
    panel["iv_spread_180"] = panel.call_iv_180 - panel.put_iv_180
    panel["iv_valid"] = panel.call_iv_180.notna() & panel.put_iv_180.notna()
    # market-on-close total returns: label d = close(d) -> close(next session), split-adjusted, plus cash dividends
    # whose ex-date is the next session (paid to holders at close d). The final label is left missing.
    rets = []
    def daily(t, adjusted):
        rows = api_get_all(f"/v2/aggs/ticker/{t}/range/1/day/{start}/{end}", {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000})
        return pd.Series({pd.Timestamp(r["t"], unit="ms", tz="UTC").tz_convert(NY).strftime("%Y-%m-%d"): r["c"] for r in rows}, dtype=float)
    with ThreadPoolExecutor(6) as ex2:
        adjc = dict(zip(tickers, ex2.map(lambda t: daily(t, True), tickers)))
        rawc = dict(zip(tickers, ex2.map(lambda t: daily(t, False), tickers)))
    for t in tickers:
        c = adjc[t].reindex(days)
        r = c.shift(-1) / c - 1
        dv = divs[t]
        if len(dv):
            exmap = {}
            for x in dv.itertuples():
                e = pd.Timestamp(x.ex_dividend_date); e = e if CAL.is_session(e) else CAL.date_to_session(e, "next")
                k = CAL.previous_session(e).strftime("%Y-%m-%d"); exmap[k] = exmap.get(k, 0) + x.cash_amount
            raw = rawc[t]
            r = r + pd.Series({d: exmap[d] / raw.get(d, np.nan) if d in exmap else 0.0 for d in r.index})
        rets.append(pd.DataFrame({"date": r.index, "ticker": t, "return": r.values}))
    return panel.drop(columns=[c for c in panel.columns if c.endswith("_contract")]), pd.concat(rets, ignore_index=True)


def build(tickers, start, end, chunks=1, total_rate=float(os.environ.get("K8_TOTAL_RATE", "400"))):
    """Split tickers across subprocesses (each its own GIL, rate share and IV workers); concatenate their outputs."""
    tickers = list(tickers)
    if chunks <= 1 or len(tickers) <= chunks:
        return _build(tickers, start, end)
    parts = [tickers[i::chunks] for i in range(chunks)]
    pkg_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, K8_RATE=str(total_rate / chunks), PYTHONPATH=pkg_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    with tempfile.TemporaryDirectory() as tmp:
        procs = [subprocess.Popen([sys.executable, "-m", __name__, start, end, f"{tmp}/{i}", *p], env=env) for i, p in enumerate(parts)]
        codes = [q.wait() for q in procs]
        if any(codes):
            raise RuntimeError(f"input chunk failed: exit codes {codes}")
        return (pd.concat([pd.read_parquet(f"{tmp}/{i}/panel.parquet") for i in range(chunks)], ignore_index=True),
                pd.concat([pd.read_parquet(f"{tmp}/{i}/returns.parquet") for i in range(chunks)], ignore_index=True))


if __name__ == "__main__":
    s, e, out, *tk = sys.argv[1:]
    Path(out).mkdir(parents=True, exist_ok=True)
    panel, rets = _build(tk, s, e)
    panel.to_parquet(f"{out}/panel.parquet"); rets.to_parquet(f"{out}/returns.parquet")
