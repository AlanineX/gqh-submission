"""Event and placebo construction, parallel option pricing with the starter engine, strategy library (five starter strategies,
their bearish mirrors and advanced structures) and scoreboards. P&L is per $1 of spot at entry, net of a premium haircut per
option leg per side and 3 bp per stock side."""
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
from . import engine as E
from .api import flush

R = E.RISK_FREE
HORIZONS = ["1", "2", "3", "5", "10", "21", "42", "63", "exp"]
LIBRARY = ["long_call", "covered_call", "protective_put", "collar", "cash_secured_put"]
ADVANCED = ["risk_reversal", "bull_call_spread", "short_strangle", "short_straddle"]
# (bullish legs, bearish mirror legs); "S" is the synthetic stock K e^{-rT} + C_K - P_K
STRATS = {
    "stock": ({"S": 1}, {"S": -1}),
    "long_call": ({"C_K": 1}, {"P_K": 1}),
    "covered_call": ({"S": 1, "C_U": -1}, {"S": -1, "P_L": -1}),
    "protective_put": ({"S": 1, "P_L": 1}, {"S": -1, "C_U": 1}),
    "collar": ({"S": 1, "P_L": 1, "C_U": -1}, {"S": -1, "C_U": 1, "P_L": -1}),
    "cash_secured_put": ({"P_L": -1}, {"C_U": -1}),
    "risk_reversal": ({"C_U": 1, "P_L": -1}, {"P_L": 1, "C_U": -1}),
    "bull_call_spread": ({"C_K": 1, "C_U": -1}, {"P_K": 1, "P_L": -1}),
    "short_strangle": ({"C_U": -1, "P_L": -1}, {"C_U": -1, "P_L": -1}),
    "short_straddle": ({"C_K": -1, "P_K": -1}, {"C_K": -1, "P_K": -1}),
}


def item_events(item, start, end, universe):
    ev = E.build_events(f"item_{item}", start, end, universe)
    ev["event_date"] = ev["filing_date"]; ev["kind"] = "event"
    return ev[["ticker", "event_date", "t_pre", "t_0", "kind"]]


def placebo(ev, n, start, end, gap=10, seed=0):
    """Random sessions for the same names, in proportion to their event counts, at least `gap` sessions from any of their events."""
    rng, CAL = np.random.default_rng(seed), E.CAL
    sess = CAL[(CAL >= start) & (CAL <= end)]; w = ev.ticker.value_counts(normalize=True); rows = []
    for t in rng.choice(w.index, n * 5, p=w.values):
        d = sess[rng.integers(len(sess))]; f = ev.event_date[ev.ticker == t]
        if len(rows) < n and (np.abs(CAL.searchsorted(f) - CAL.searchsorted(d)) >= gap).all() and d < CAL[-2]:
            rows.append({"ticker": t, "event_date": d, "t_pre": E.session_before(d), "t_0": CAL[CAL.searchsorted(d, side="right")], "kind": "placebo"})
    return pd.DataFrame(rows)


def price(ev, buckets=None, otm=None, threads=6, data_end=None):
    """Leg marks at t_pre, t_0 and every fixed horizon for each event (starter engine: chain as of t_pre, parity spot, strikes)."""
    threads = max(1, min(int(threads), 6))
    buckets = buckets or {"3-6m": E.EXPIRY_BUCKETS["3-6m"]}; otm = otm or E.OTM_GRID

    def one(r):
        try:
            pr, _ = E.price_event(r.ticker, pd.Timestamp(r.t_pre), pd.Timestamp(r.t_0), pd.Timestamp(r.event_date), buckets, otm, data_end=data_end)
        except Exception:
            return []
        rows = []
        for p in pr:
            i0 = E.CAL.get_loc(p.t_0)
            days = {"0": p.t_0, **{str(h): E.CAL[i0 + h] for h in E.HORIZONS if i0 + h < len(E.CAL) and E.CAL[i0 + h] <= p.expiry_session}, "exp": p.expiry_session}
            for h, d in days.items():
                if d <= (pd.Timestamp(data_end) if data_end is not None else E.LAST_SESSION):
                    rows.append({"ticker": p.ticker, "event_date": p.event_date, "kind": r.kind, "bucket": p.bucket, "horizon": h, "day": d,
                                 "expiry": p.expiry, **{f"k_{k}": v for k, v in p.strikes.items()}, **{f"m_{k}": v for k, v in p.marks(d).items()}})
        return rows
    with ThreadPoolExecutor(threads) as ex:
        out = [x for rows in ex.map(one, ev.itertuples(index=False)) for x in rows]
    flush()
    return pd.DataFrame(out)


def _leg(df, leg, otm):
    if leg == "S":
        T = (pd.to_datetime(df.expiry) - pd.to_datetime(df.day)).dt.days.clip(lower=0) / 365
        return df.k_K * np.exp(-R * T) + df.m_C_K - df.m_P_K
    return df[{"C_K": "m_C_K", "P_K": "m_P_K", "C_U": f"m_C_U{otm}", "P_L": f"m_P_L{otm}"}[leg]]


def pnl(legs, otm=0.05, haircut=0.02, bucket="3-6m"):
    """One row per (event, horizon): every strategy's bullish and bearish P&L per $1 of spot at entry (t_0 close), net of costs."""
    key = ["ticker", "event_date", "kind"]; L = legs[legs.bucket == bucket].drop_duplicates(key + ["horizon"])
    e = L[L.horizon == "0"].set_index(key); out = []
    S0 = _leg(e.reset_index(), "S", otm).to_numpy()
    for h in HORIZONS:
        x = L[L.horizon == h].set_index(key).reindex(e.index)
        row = pd.DataFrame(index=e.index); row["horizon"] = h
        for name, sides in STRATS.items():
            for side, legs_ in zip(("bull", "bear"), sides):
                g = c = 0.0
                for leg, w in legs_.items():
                    v0 = _leg(e.reset_index(), leg, otm).to_numpy(); v1 = _leg(x.reset_index(), leg, otm).to_numpy()
                    g = g + w * (v1 - v0); c = c + (2 * 3e-4 * S0 if leg == "S" else 2 * haircut * np.abs(v0))
                row[f"{name}_{side}"] = (g - c) / S0
        out.append(row.reset_index())
    return pd.concat(out, ignore_index=True)


def ci(x, n=2000, seed=0):
    x = pd.Series(x).dropna().to_numpy()
    if len(x) < 10:
        return np.nan, np.nan
    b = np.random.default_rng(seed).choice(x, (n, len(x))).mean(1)
    return np.percentile(b, 2.5), np.percentile(b, 97.5)


def board(p, strategies, horizons=("5", "10", "21", "42"), side="bull"):
    """Mean P&L (% of spot) with a 95% bootstrap interval, hit rate and n, per strategy and horizon."""
    rows = []
    for s in strategies:
        for h in horizons:
            col = p[p.horizon == h]
            x = (col[f"{s}_bull"].where(col.tercile != "bottom", col[f"{s}_bear"]) if side == "directed" else col[f"{s}_{side}"]).dropna()
            lo, hi = ci(x)
            rows.append({"strategy": s, "horizon": h, "mean_%": 100 * x.mean(), "lo_%": 100 * lo, "hi_%": 100 * hi, "hit": (x > 0).mean(), "n": len(x)})
    return pd.DataFrame(rows)


def gap(a, b, s, h, side="bull"):
    """Event-minus-placebo difference in mean P&L (% of spot) and its t-statistic."""
    x, y = a[a.horizon == h][f"{s}_{side}"].dropna(), b[b.horizon == h][f"{s}_{side}"].dropna()
    d = x.mean() - y.mean(); se = np.sqrt(x.var() / len(x) + y.var() / len(y))
    return 100 * d, d / se


def cohorts(p, strategy, h, side="bull"):
    """Monthly cohort series: mean net P&L (per $1 of spot) of the trades entered in each month, held `h` sessions.
    With 10-session holds cohorts barely overlap, so the series reads like a monthly return on the capital committed."""
    x = p[p.horizon == h][["event_date", f"{strategy}_{side}"]].dropna()
    m = x.groupby(pd.to_datetime(x.event_date).dt.to_period("M"))[f"{strategy}_{side}"].mean()
    full = m.reindex(pd.period_range(m.index.min(), m.index.max(), freq="M"), fill_value=0.0)
    return full


def stats(m):
    """Annualized Sharpe of a monthly series, total, worst month, maximum drawdown of the cumulative sum, share of positive months."""
    cum = m.cumsum()
    return {"months": len(m), "sharpe_ann": float(np.sqrt(12) * m.mean() / m.std()) if m.std() > 0 else np.nan, "total_%": 100 * m.sum(),
            "worst_month_%": 100 * m.min(), "max_dd_%": 100 * float((cum.cummax() - cum).max()), "pos_months": float((m > 0).mean())}


def closes(universe, start, end):
    """Split-adjusted daily closes for the universe (one daily-aggregate request per name)."""
    out = {}
    for t in universe:
        rows = E.api_get_all(f"/v2/aggs/ticker/{t}/range/1/day/{start}/{end}", {"adjusted": "true", "sort": "asc", "limit": 50000})
        if rows:
            idx = pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True).tz_convert("America/New_York").normalize().tz_localize(None)
            out[t] = pd.Series([float(r["c"]) for r in rows], index=idx)
    flush()
    return pd.DataFrame(out).sort_index()


def hedge(p, px, h="10", delta=None):
    """Market-hedged P&L: subtract delta x beta x (equal-weight market return over the same hold). Beta: 60 sessions to t_0."""
    delta = delta or {"stock": 1.0, "protective_put": 0.7, "covered_call": 0.6}
    r = px.pct_change(fill_method=None); mk = r.mean(axis=1); lvl = np.log1p(mk.fillna(0)).cumsum()
    beta = (r.mul(mk, axis=0).rolling(60, min_periods=40).mean() - r.rolling(60, min_periods=40).mean().mul(mk.rolling(60, min_periods=40).mean(), axis=0)).div(mk.rolling(60, min_periods=40).var(ddof=0), axis=0)
    q = p[p.horizon == h].copy(); cal = px.index
    i0 = cal.searchsorted(pd.to_datetime(q.t_0)); i1 = np.minimum(i0 + int(h), len(cal) - 1)
    q["market"] = np.expm1(lvl.values[i1] - lvl.values[np.minimum(i0, len(cal) - 1)])
    q["beta"] = [beta.iat[min(i, len(cal) - 1), beta.columns.get_loc(t)] if t in beta.columns else np.nan for i, t in zip(i0, q.ticker)]
    for s, d in delta.items():
        q[f"{s}_hedged"] = q[f"{s}_bull"] - d * q.beta.fillna(1.0) * q.market
    return q
