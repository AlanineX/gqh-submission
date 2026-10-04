# Filing-aware options study

This submission tests whether unusual pre-filing option-implied skew becomes more useful when paired with an 8-K disclosure. Item 7.01 is the Regulation FD section of Form 8-K: companies may use it to make information broadly public. Its varied subject matter supplies event context; it does not determine trade direction.

Open `strategy.ipynb` in a Jupyter environment after installing `requirements.txt` and setting `MASSIVE_API_KEY` in the environment or a local `.env`. The notebook follows the provided workflow and imports reusable event, IV, pricing, strategy-library, and date-bounded pipeline code from `skew8k/` and `k8/`. It shows the event/control samples, key transformations, five standard structures, four advanced structures, fixed-horizon results, costs, and monthly cohort statistics.

## Reproduced results

The full 2022-03-07 through 2024-12-31 in-sample notebook completed all 13 code cells. It contains 691 filing events and 600 same-company placebo sessions; the option engine priced 649 events and 543 controls before filtering for the IV signal and each exit horizon.

The high-skew protective put earns mean net P&L of 0.73% of entry spot at 10 sessions versus 0.34% for high-skew placebo sessions: a 0.39 percentage-point gap, t = 0.67. At 21 sessions, the gap is 0.56 points, t = 0.61. The 33-month cohort Sharpe is 0.42, summed cohort P&L 10.85%, cohort-index drawdown 6.54%, and positive-cohort rate 42%. These effects are statistically weak and do not meet the requested Sharpe target. Monthly cohort statistics are not a complete self-financing portfolio return.

Risk reversal outperforms four of the five standard structures at 21 sessions in this sample, but remains below protective put (0.93% versus 1.25% of entry spot). The five standard structures are long call, covered call, protective put, collar, and cash-secured put. The other advanced comparisons are bull call spread, short strangle, and short straddle.

## Data and execution

The optional `data/iv180_top100.parquet` input contains `date`, `ticker`, `call_iv_180`, `put_iv_180`, and `iv_valid`. If absent, `skew8k.signal.load_iv` builds it through the Massive API. The full validation used the original 71,000-row in-sample IV panel for 100 names and API/cache option data. A separate API-builder test for an in-sample day reproduced call and put IV to six decimal places. A complete fresh historical redownload was not repeated.

IV180 uses the standard listed expiry nearest 180 calendar days within 150–210 days, the paired call and put at the strike nearest spot, and valid recent quote midpoints at 15:55 ET. QuantLib solves American IV using prior Treasury yields and trailing paid dividends as carry. The signal subtracts each name's prior 60-session average call-minus-put IV, then standardizes the residual across names. Predictor quotes and later daily-bar trade marks are separate inputs. The static large-cap universe can introduce survivorship bias.

`skew8k.pipeline.run_study(start, end, ...)` is the reusable entry point. It includes 100 calendar days of prior IV feature history and caps option-bar marks at the requested end date. The reserved evaluation configuration is 2025-01-02 through 2026-10-02, with warm-up from 2024-09-24; execution is disabled and no evaluation outputs are supplied. API credentials, raw Massive data, and caches are excluded from the repo. Workers are capped at six.

Pandas 2.2.3 and NumPy 2.2.6 are pinned because newer Pandas changed tied ticker-count ordering and therefore seeded placebo draws. Early saved tables also used exits after the in-sample cutoff; the current outputs enforce the cutoff. See `results/REPRODUCTION.md` for the validation scope.

## Files

- `strategy.ipynb` — primary notebook, including visible execution results.
- `skew8k/` — reusable event, signal, pricing and strategy-study modules.
- `k8/` — Massive input and American-IV building components.
- `results/` — regenerated aggregate in-sample outputs.
- `note/QUANT_NOTE.md` and `note/QUANT_NOTE.pdf` — hypothesis, data construction, figures, results and limitations.
- `SUBMISSION_CHECKLIST.md` — verified coverage and remaining competition checks.
