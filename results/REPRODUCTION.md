# Local reproduction verification

The exact public repository was downloaded into a separate local checkout and executed in a fresh environment. The full in-sample notebook completed all 13 code cells without errors. Every one of the five generated CSV tables was byte-identical on a repeat run with the pinned dependencies.

| Check | Result |
|---|---|
| In-sample filing/signal and market-mark cutoff | 2022-03-07 through 2024-12-31; marks after the end date excluded |
| IV input | Original derived IV180 panel: 71,000 rows, 100 names, only the in-sample dates |
| Filing/control sample | 691 Item 7.01 filings across 83 names; 600 same-company controls |
| Priced entries | 649 filing events and 543 controls before signal/horizon availability filtering |
| Dependencies affecting seeded draws | Pandas 2.2.3, NumPy 2.2.6; QuantLib 1.40 |
| Regenerated files | Library comparison, fixed horizons, yearly comparison, cohort statistics, OTM/cost sensitivity |
| API fallback check | In-sample AAPL test on 2024-12-02: valid call/put IV, both matching the supplied panel to six decimals |
| Reserved evaluation | Disabled; no evaluation outcomes included |

## Corrections needed

The first API-backed execution exposed a misplaced worker cap in the input builder. That was removed from the stock-bar helper and retained in the actual worker configuration. The notebook's missing sensitivity cell was restored, the main comparison table made visible, and yearly sample counts corrected to count valid outcomes. The numeric-library pins prevent Pandas 3 tie ordering from changing seeded controls.

The earlier uploaded values cannot be reproduced under the strict end-date guard because they included some exits after the in-sample cutoff. The 2022 and 2023 year tables match those earlier values; only the 2024 entries and pooled statistics change after pinning the original dependencies. The current results and note now report the bounded run: protective-put gaps of 0.39 and 0.56 percentage points at 10 and 21 sessions, t-statistics 0.67 and 0.61, and monthly-cohort Sharpe 0.42. These remain weak findings, not evidence of consistent profitability.

## Verification scope

This is a full data-assisted in-sample reproduction using the original IV panel plus date-bounded Massive API/cache option inputs. The missing-panel API builder was tested on an in-sample day; a complete fresh redownload of all historical IV inputs was not repeated. No raw Massive data, cache, credential, or reserved-evaluation artifact is published. Expiry, entry-timing, and filing-category sensitivity remain separate outstanding competition checks.
