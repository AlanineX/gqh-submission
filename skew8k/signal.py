"""Pre-filing skew signal. Daily 180-day at-the-money American implied volatility (call and put, 15:55 ET quotes) per name;
skew = call IV - put IV; signal = today's skew minus its own trailing 60-session mean, z-scored across names that day.
Subtracting the name's own history removes the slow carry part of the skew (dividends, borrow, early exercise), leaving fresh positioning."""
from pathlib import Path
import numpy as np, pandas as pd


def load_iv(start, end, tickers, path=None):
    """Load the daily IV panel from `path` if given and present; otherwise build it from the API (slow, cached)."""
    if path and Path(path).exists():
        # Predicate-push the requested window into the parquet reader so later rows are not materialized.
        p = pd.read_parquet(path, columns=["date", "ticker", "call_iv_180", "put_iv_180", "iv_valid"],
                            filters=[("date", ">=", start), ("date", "<=", end)])
        return p[p.ticker.isin(tickers)].reset_index(drop=True)
    from k8.inputs import build                                         # American IV construction, Massive quotes only
    warm = (pd.Timestamp(start) - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
    panel, _ = build(list(tickers), warm, end)
    return panel[["date", "ticker", "call_iv_180", "put_iv_180", "iv_valid"]]


def skew_z(iv, lookback=60):
    """Date x ticker frame of the own-history skew z-score, known at 15:55 ET of each date."""
    iv = iv[iv.iv_valid.astype(bool)]
    sk = (iv.pivot(index="date", columns="ticker", values="call_iv_180") - iv.pivot(index="date", columns="ticker", values="put_iv_180")).sort_index()
    inno = sk - sk.rolling(lookback, min_periods=lookback // 2).mean().shift(1)
    z = inno.sub(inno.mean(axis=1), axis=0).div(inno.std(axis=1), axis=0)
    z.index = pd.to_datetime(z.index)
    return z


def attach(ev, z, col="t_pre"):
    """Signal read at the session before the filing date; terciles at +-0.43 (standard-normal thirds)."""
    ev = ev.copy()
    ev["skew_z"] = [z.at[d, t] if d in z.index and t in z.columns else np.nan for d, t in zip(pd.to_datetime(ev[col]), ev.ticker)]
    ev["tercile"] = np.select([ev.skew_z > 0.43, ev.skew_z < -0.43], ["top", "bottom"], np.where(ev.skew_z.notna(), "mid", "none"))
    return ev
