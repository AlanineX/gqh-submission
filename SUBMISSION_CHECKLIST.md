# GQH Massive track submission checklist

The organizer starter asks for a clean-kernel notebook with explicit start/end inputs; a write-up of no more than two pages covering hypothesis, method, results with uncertainty, failure conditions, and trade specification; and sensitivity checks for expiry, OTM distance, entry, horizon, and filing category. The track rubric covers novelty, analytical rigor, sealed-window replication, trade realism, and communication. The starter notebook is the local source of these requirements; the track web page was inaccessible during this review.

## Deliverables and verification

| Requirement | Status | Evidence or remaining work |
|---|---|---|
| Notebook uses the supplied workflow and shows key execution steps | Prepared | `strategy.ipynb` shows event/placebo construction, IV180 signal, option marks, five standard strategies, bonus structures, costs, and result summaries; reusable code is imported from `skew8k/` and `k8/`. |
| Five standard strategies | Prepared | Long call, covered call, protective put, collar, and cash-secured put are implemented in `skew8k/study.py`. |
| 8-K feature and IV180 construction explained | Prepared | Notebook and quant note define Item 7.01, quote/contract selection, American IV calculation, carry inputs, the 60-session residual, and how this differs from P&L marks. |
| In-sample window | Configured | Filing/signal dates: 2022-03-07 through 2024-12-31. The note reports only saved development summaries; these need a fresh bounded rerun before final performance claims. |
| Sealed evaluation configuration and warm-up | Configured, not run | 2025-01-02 through 2026-10-02; feature warm-up begins 100 calendar days before the start. `RUN_EVALUATION=False`; no evaluation results are in the notebook or note. Final horizons near the end date are incomplete until their exit marks occur. |
| No forward marks past a requested end date | Implemented, needs smoke verification | `skew8k.study.price(..., data_end=...)` passes the limit into `skew8k.engine.price_event`; `skew8k.pipeline.run_study` bounds option bars to `end`. |
| Clean-kernel notebook run with only an API key | Not verified | This pass will syntax-check notebook cells and import modules without API calls. Complete a full clean-kernel run on the authorized in-sample dates before claiming this requirement passed. |
| Quant note (maximum two pages) and figures | Prepared, verify rendering | `note/QUANT_NOTE.md` covers the five required topics and embeds two figures. `note/QUANT_NOTE.pdf` must be checked for exactly two pages after rendering. |
| Results with uncertainty | Partial | Saved core comparison, t-statistics, horizon intervals, year summaries, and monthly-cohort statistics are documented. Protective-put event/placebo gaps are +0.35 percentage points (t=0.62) at 10 sessions and +0.40 points (t=0.44) at 21 sessions; this is not statistically reliable. |
| Bonus structures | Included as comparisons | Risk reversal beats some weaker standard structures in the saved means, but not the protective put. No claim that an advanced structure beats the best standard strategy. |
| Required sensitivity dimensions | Incomplete | Existing saved checks vary OTM distance, option-cost haircut, and horizon. Expiry bucket, entry timing, and filing-category comparisons still need a bounded in-sample run. |
| Point-in-time universe | Limitation disclosed | The current large-cap list is static, not historical membership, so survivorship bias may affect 2022–2024 estimates. |
| Dependencies and credentials | Prepared | `requirements.txt` pins QuantLib; `.env` and `.massive_cache/` are ignored. IV parquet and private evaluation artifacts are excluded from the public allowlist. |
| Portable content scan | Pending final check | Notebook metadata and outputs were cleared. Run the final source-only scan for local paths, account identifiers, and unrelated platform terms before publication. |
| Public repository | Complete | `https://github.com/AlanineX/data-is-all-you-need` is public; the clean submission package is pushed to `main`. |
| Devpost entry | Pending | Attach the two-page PDF and public repository URL before the deadline. |

## Saved result context

The saved development comparison (from before the new end-date mark guard; refresh before final submission) reports high-skew Item 7.01 protective-put means of 0.72% of entry spot at 10 sessions and 1.15% at 21 sessions, versus 0.37% and 0.75% for matched high-skew placebo sessions. The 33-cohort annualized Sharpe is 0.45, with 11.6% summed cohort P&L, 6.54% maximum drawdown, and 42% positive cohorts. These are descriptive saved in-sample outputs, not proof of statistical significance, stable profitability, or the requested Sharpe threshold. The figures use the same saved result files.

## Public-package allowlist

Include `strategy.ipynb`, `skew8k/`, `k8/`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, this checklist, the quant note/PDF, and approved aggregate in-sample results. Exclude `.env`, `.massive_cache/`, `data/*.parquet`, `trade_the_8k_item502.ipynb`, and `results/is_vs_oos_private.md`.
