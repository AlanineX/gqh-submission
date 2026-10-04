# GQH Massive track submission checklist

The organizer starter asks for a clean-kernel notebook with explicit start/end inputs; a write-up of no more than two pages covering hypothesis, method, results with uncertainty, failure conditions, and trade specification; and sensitivity checks for expiry, OTM distance, entry, horizon, and filing category. The track rubric covers novelty, analytical rigor, sealed-window replication, trade realism, and communication. The starter notebook is the local source of these requirements; the track web page was inaccessible during this review.

## Deliverables and verification

| Requirement | Status | Evidence or remaining work |
|---|---|---|
| Notebook uses the supplied workflow and shows key execution steps | Prepared | `strategy.ipynb` shows event/placebo construction, IV180 signal, option marks, five standard strategies, bonus structures, costs, and result summaries; reusable code is imported from `skew8k/` and `k8/`. |
| Five standard strategies | Prepared | Long call, covered call, protective put, collar, and cash-secured put are implemented in `skew8k/study.py`. |
| 8-K feature and IV180 construction explained | Prepared | Notebook and quant note define Item 7.01, quote/contract selection, American IV calculation, carry inputs, the 60-session residual, and how this differs from P&L marks. |
| In-sample window | Configured | Filing/signal dates: 2022-03-07 through 2024-12-31. The note reports the reproduced in-sample results with exit marks bounded to the same end date. |
| Sealed evaluation configuration and warm-up | Configured, not run | 2025-01-02 through 2026-10-02; feature warm-up begins 100 calendar days before the start. `RUN_EVALUATION=False`; no evaluation results are in the notebook or note. Final horizons near the end date are incomplete until their exit marks occur. |
| No forward marks past a requested end date | Verified in executed workflow | `skew8k.study.price(..., data_end=...)` passes the limit into `skew8k.engine.price_event`; `skew8k.pipeline.run_study` bounds option bars to `end`. |
| Full in-sample notebook execution | Verified with input data | All 13 code cells completed using the pinned dependencies, original in-sample IV panel and date-bounded API/cache option data. A fresh full historical API-only IV rebuild was not repeated; a one-day API fallback test passed and matched IVs to six decimals. |
| Quant note (maximum two pages) and figures | Rendered and checked | `note/QUANT_NOTE.md` covers the five required topics and embeds two figures. `note/QUANT_NOTE.pdf` is checked after rendering for two pages. |
| Results with uncertainty | Partial | Saved core comparison, t-statistics, horizon intervals, year summaries, and monthly-cohort statistics are documented. Protective-put event/placebo gaps are +0.39 percentage points (t=0.67) at 10 sessions and +0.56 points (t=0.61) at 21 sessions; this is not statistically reliable. |
| Bonus structures | Included as comparisons | Risk reversal beats some weaker standard structures in the saved means, but not the protective put. No claim that an advanced structure beats the best standard strategy. |
| Required sensitivity dimensions | Incomplete | Existing saved checks vary OTM distance, option-cost haircut, and horizon. Expiry bucket, entry timing, and filing-category comparisons still need a bounded in-sample run. |
| Point-in-time universe | Limitation disclosed | The current large-cap list is static, not historical membership, so survivorship bias may affect 2022–2024 estimates. |
| Dependencies and credentials | Prepared | `requirements.txt` pins QuantLib; `.env` and `.massive_cache/` are ignored. IV parquet and private evaluation artifacts are excluded from the public allowlist. |
| Portable content scan | Checked before publication | Notebook inputs and executed outputs are scanned for local paths, credentials, account identifiers and unrelated platform terms before publication. |
| Public repository | Complete | `https://github.com/AlanineX/gqh-submission` is public; the clean submission package is pushed to `main`. |
| Devpost entry | Pending | Attach the two-page PDF and public repository URL before the deadline. |

## Reproduced result context

The current comparison uses outcome marks no later than 2024-12-31. Protective-put means are 0.73% and 1.25% of entry spot at 10 and 21 sessions, versus 0.34% and 0.69% for matched high-skew controls. The annualized monthly-cohort Sharpe is 0.42, summed cohort P&L 10.85%, cohort-index drawdown 6.54%, and positive-cohort rate 42%. Results remain statistically weak and below the requested Sharpe target. The earlier tables used a different dependency environment or outcomes after the cutoff; see `results/REPRODUCTION.md`.

## Public-package allowlist

Include `strategy.ipynb`, `skew8k/`, `k8/`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, this checklist, the quant note/PDF, and approved aggregate in-sample results. Exclude `.env`, `.massive_cache/`, `data/*.parquet`, `trade_the_8k_item502.ipynb`, and `results/is_vs_oos_private.md`.
