# Input data and outputs

No Massive raw-data files or API cache are bundled. The strategy builds the IV180 panel on demand from Massive using `MASSIVE_API_KEY`; see `skew8k.signal.load_iv` and `k8.inputs.build`. The configured in-sample filing/signal dates are 2022-03-07 through 2024-12-31. The reserved evaluation dates are configured separately, disabled, and not included in the results.

The `results/` directory contains the saved aggregate in-sample tables used by the note, and `note/figs/` contains the matching figures. These are saved research outputs, not a newly executed clean-kernel run.
