"""Synthetic regression checks; no real player names or save-derived fixtures."""

import numpy as np
import pandas as pd
from analyze import eligible_population, fit_model, rank_elite, verify_model

rng = np.random.default_rng(42)
n = 150
frame = pd.DataFrame(
    {
        "uid": np.arange(n),
        "name": [f"Synthetic player {i}" for i in range(n)],
        "age": rng.integers(15, 22, n),
        "ca": rng.integers(40, 145, n),
        "pa": rng.integers(150, 201, n),
        "pa_range": [None] * n,
        "value_state": ["ok"] * n,
        "value": np.exp(rng.normal(10, 2, n)),
    }
)
population = eligible_population(frame)
scored, _ = fit_model(population)
ranked = rank_elite(scored)
verify_model(population, ranked, refits=5)

# A deliberately very cheap player should have a larger bargain score.
cheaper = population.copy()
cheaper.loc[0, "value"] /= 100
cheap_scores, _ = fit_model(cheaper)
assert cheap_scores.bargain_score.iloc[0] > scored.bargain_score.iloc[0]

# Missing/range PA, boundary ages, values and blank names must not leak in.
bad = frame.iloc[:8].copy()
bad["uid"] += n
bad.loc[0, "age"] = 14
bad.loc[1, "age"] = 22
bad.loc[2, "pa"] = np.nan
bad.loc[3, "pa_range"] = -10
bad.loc[4, "value"] = 0
bad.loc[5, "value_state"] = "placeholder"
bad.loc[6, "name"] = "  "
bad.loc[7, "ca"] = np.nan
assert len(eligible_population(pd.concat([frame, bad], ignore_index=True))) == n
assert ranked.pa.ge(150).all()
print("Synthetic eligibility, residual direction, determinism and currency checks passed")
