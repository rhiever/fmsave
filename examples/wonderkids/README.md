# A local FM26 wonderkid analysis

This script reads your own single-player save and produces two phone-friendly PNGs:
a square scatter chart and a 4:5 top-ten table. It also writes the ranking and verification
metrics locally. No save data or notebook output is included in this example.

**Hidden-data spoilers:** the results show exact CA, PA and Professionalism. Do not
use them to gain an advantage in an online career. The tool reads the save; it does
not modify it. Never upload a save file for troubleshooting.

From the repository root, with Python 3.12 or newer:

```sh
python -m pip install 'fmsave[pandas]==0.4.1' matplotlib
export SAVE_PATH='/absolute/path/to/your/single-player-save.fm'
python examples/wonderkids/analyze.py
```

For a source checkout using uv:

```sh
SAVE_PATH='/absolute/path/to/your/single-player-save.fm' \
  uv run --with matplotlib examples/wonderkids/analyze.py
```

`--save` overrides `SAVE_PATH`. The default output is `.local/wonderkids/`; `--output`
can choose another directory underneath `.local/`, but cannot write save-derived
results outside it. Keep generated images, rankings and saves out of Git.

## Method

The fitting population has age 15-21, a nonempty name, current ability, fixed
potential ability (no negative potential range code), and a positive transfer
value with `transfer_value_state == OK`. The model is ordinary least squares:

```text
log(transfer value) ~ intercept + age + CA + PA
bargain score = predicted log value − actual log value
expected-value multiple = exp(bargain score)
```

The published ranking contains only PA ≥ 150 players. Ties, rounded to ten decimal
places to avoid floating-point noise, are resolved by player UID. Age, CA and PA
are centered for numerical stability; values are normalized to a reference value
before taking logs, which leaves the fitted residuals unchanged. This is the same
model, and ranking is invariant to a common currency conversion factor.

"Undervalued by FM's estimated value" means below the value this model predicts.
It does **not** mean available for that price. An estimated value is not an asking
price, release clause, work-permit assessment or guarantee a player is signable.
The predicted value is a model estimate on the logarithmic scale, exponentiated;
it is not a bias-corrected estimate of the arithmetic mean price. Country, club,
reputation, contract, role and league are not controls, so their differences may
explain apparent bargains. This analysis is descriptive, not a causal pricing model.

The chart uses raw save currency units, a logarithmic x-axis, PA on the y-axis,
point area proportional to CA, and age as color. Table position lists natural
positions. "Unattached / unresolved" means the club could not be resolved, not
necessarily that the player is a free agent. A missing attribute is shown as a dash.

Each run checks all published rows, deterministic ordering after input shuffling,
and currency factors 0.01, 1.234567 and 1000. The default 100 bootstrap refits use
seed 20260922 and report top-20 membership and exact-order stability separately.
Metrics are recomputed from the supplied save; no save-specific statistics are hardcoded.

Run the synthetic, save-independent regression checks with:

```sh
uv run python examples/wonderkids/check_model.py
```

Compatibility reports should start with `fmsave validate SAVE_PATH --json`.
Inspect diagnostics for private information before sharing; do not share the save.
