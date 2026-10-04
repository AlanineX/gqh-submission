"""Date-bounded entry point for the filing-aware options study."""
import pandas as pd
from . import engine as E, study as S
from .signal import attach, load_iv, skew_z


def run_study(start, end, item="7.01", universe=None, n_placebo=600, seed=0,
              iv_path="data/iv180_top100.parquet", bucket="3-6m", otm=0.05,
              haircut=0.02, threads=6):
    """Build events, matched controls, pre-event IV signal, option marks, and net P&L.

    `start` and `end` bound filing/control and signal dates. Only organizer-provided
    dates should be used for evaluation; this function does not select a holdout window.
    A 100-calendar-day IV warm-up initializes the past-only 60-session feature.
    """
    universe = list(universe or E.TOP_100)
    events = S.item_events(item, start, end, universe).drop_duplicates(["ticker", "event_date"])
    controls = S.placebo(events, n_placebo, start, end, seed=seed)
    warm = (pd.Timestamp(start) - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
    iv = load_iv(warm, end, universe, iv_path)
    signal = skew_z(iv)
    events, controls = attach(events, signal), attach(controls, signal)
    all_rows = pd.concat([events, controls], ignore_index=True)
    legs = S.price(all_rows, buckets={bucket: E.EXPIRY_BUCKETS[bucket]}, otm=[otm],
                   threads=threads, data_end=end)
    pnl = S.pnl(legs, otm=otm, haircut=haircut, bucket=bucket)
    labels = all_rows[["ticker", "event_date", "kind", "tercile", "skew_z", "t_0"]]
    pnl = pnl.merge(labels, on=["ticker", "event_date", "kind"], how="left")
    pnl = pnl[pnl.tercile != "none"].reset_index(drop=True)
    return {"events": events, "placebo": controls, "iv": iv, "signal": signal,
            "legs": legs, "pnl": pnl}
