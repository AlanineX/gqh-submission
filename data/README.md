# Input data and outputs

No Massive raw-data files or API cache are bundled. `skew8k.signal.load_iv` accepts an optional five-column IV180 parquet panel; if absent, it calls `k8.inputs.build` with `MASSIVE_API_KEY`. The full local reproduction used the original in-sample IV panel (71,000 rows, 100 tickers, 2022-03-07 through 2024-12-31), while a separate fresh API-builder test matched call and put IV on an in-sample day to six decimal places. A complete historical API-only rebuild was not repeated.

The `results/` directory contains regenerated aggregate in-sample tables. The notebook keeps reserved evaluation execution disabled and supplies no evaluation results.
