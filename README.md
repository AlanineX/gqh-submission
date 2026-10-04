# Filing-aware options study

This submission asks whether a pre-filing options signal becomes more useful when paired with an 8-K disclosure. It uses SEC Item 7.01 filings as event timestamps (Item 7.01 is the Regulation FD section of Form 8-K, used for broad public disclosure after selective communication) and ranks companies by unusual call-versus-put implied volatility before the filing. The filing supplies context; it does not set trade direction.

The main notebook is [`strategy.ipynb`](strategy.ipynb). It follows the provided notebook workflow and imports the event, pricing, signal, and portfolio routines from `skew8k/`. It builds the event and matched-placebo samples, attaches the pre-filing signal, prices the five standard structures, compares advanced structures, and checks costs, years, and portfolio summaries. `skew8k/engine.py`, `skew8k/signal.py`, `skew8k/study.py`, and `skew8k/pipeline.py` contain reusable implementation; the notebook keeps the research decisions visible.

## Main result

In the saved 2022–2024 development results, the 8-K plus top-skew group has higher average modeled P&L than matched ordinary-day controls for several structures. For the protective put, the event-minus-placebo difference is 0.35 percentage points of entry spot at 10 sessions and 0.40 points at 21 sessions; the corresponding t-statistics are 0.62 and 0.44. This is a positive but statistically weak in-sample result, not evidence of a proven or consistently profitable edge. The five standard structures are long call, covered call, protective put, collar, and cash-secured put. The advanced comparisons are risk reversal, bull call spread, short strangle, and short straddle; none beats the protective put in the saved top-skew event means.

The monthly-cohort protective-put portfolio has an annualized Sharpe of 0.45 over 33 cohorts, 11.6% summed cohort P&L, 6.54% maximum drawdown, and a 42% positive-cohort rate. These are modeled research statistics, not a live-account return, and are preliminary pending a fresh run with the current end-date guard. The strategy does not meet the requested Sharpe threshold, and the evidence does not establish statistically significant improvement from the 8-K feature. Item 7.01 is the Regulation FD disclosure section of Form 8-K; its varied subject matter makes it event context rather than a directional label. The reserved evaluation remains sealed; this package reports no evaluation results.

## Reproduce the study

Use Python 3.11 or 3.12, install the pinned dependencies, and provide a Massive API key through `MASSIVE_API_KEY` or a local `.env` file. The notebook's in-sample filing/signal window is March 7, 2022 through December 31, 2024. A reserved evaluation configuration runs January 2, 2025 through October 2, 2026, with 100 calendar days of earlier IV data for the 60-session signal warm-up. It is disabled and has not been executed. Its API calls are cached locally under `.massive_cache/`; credentials and cache files are excluded from version control. The notebook's `S.item_events`, `S.placebo`, `load_iv`, `S.price`, and `S.pnl` calls expose the main pipeline stages. Set the requested start/end dates in the configuration cell before running a new authorized study.

The study uses a static large-cap universe, daily option bars for trade marks, a 3–6 month expiry, and a 2% option-premium haircut per leg per side plus 3 basis points per stock side. The IV180 panel uses a standard listed expiry nearest 180 calendar days (within 150–210), a paired call/put at the strike nearest spot, and a valid NBBO midpoint no more than 60 seconds old at 15:55 ET. QuantLib solves American IV with prior Treasury yields and trailing paid cash dividends as carry. IV quotes form the predictor; daily option bars mark modeled P&L. The signal uses 180-day call-minus-put IV after removing a 60-session name baseline, then ranks the residual cross-sectionally. The event is tradable only from the first session after the filing date. These choices and limitations are visible in the notebook and `skew8k/` modules.

## Package contents

- `strategy.ipynb` — primary, step-by-step submission notebook.
- `skew8k/` — reusable event study, IV signal, pricing, and strategy library.
- `k8/` — shared Massive API and options-pricing components.
- `results/` — saved aggregate development results used in the note; not a fresh blind evaluation.
- `note/QUANT_NOTE.md` and `note/QUANT_NOTE.pdf` — concise reader summary, portfolio-manager hypothesis, construction diagram, and in-sample results figures.
- `requirements.txt`, `.env.example`, `.gitignore` — environment and credential handling.

No API key, user-specific path, or account identifier is needed in the code. The notebook contains no run-specific credentials.
