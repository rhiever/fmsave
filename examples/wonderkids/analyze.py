"""Reproduce a local, single-player FM26 wonderkid analysis without embedded data.

Run from the repository root; see README.md beside this script. Generated results
must remain under the gitignored .local/ directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import fmsave

ROOT = Path(__file__).resolve().parents[2]
BACKGROUND = "#ffffff"
FOREGROUND = "#24333b"
MUTED = "#647078"
ACCENT = "#146d7a"


def eligible_population(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the complete, positive-value age 15-21 fitting population."""
    usable = (
        frame.age.between(15, 21)
        & frame.name.notna()
        & frame.name.fillna("").str.strip().ne("")
        & frame.ca.notna()
        & frame.pa.notna()
        & frame.pa_range.isna()
        & frame.value_state.eq("ok")
        & frame.value.gt(0)
    )
    selected = frame.loc[usable].sort_values("uid").reset_index(drop=True).copy()
    if selected.uid.duplicated().any():
        raise ValueError("Player UIDs must be unique")
    if len(selected) < 5:
        raise ValueError("At least five eligible players are needed")
    if not np.isfinite(selected[["age", "ca", "pa", "value"]].to_numpy()).all():
        raise ValueError("Model input contains nonfinite values")
    return selected


def design_matrix(frame: pd.DataFrame) -> np.ndarray:
    features = frame[["age", "ca", "pa"]].to_numpy(dtype=float)
    # Centering improves conditioning without changing the model specification.
    return np.column_stack([np.ones(len(frame)), features - features.mean(axis=0)])


def fit_model(population: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """OLS: log(value) ~ intercept + age + CA + PA; residual ranks bargains."""
    design = design_matrix(population)
    values = population.value.to_numpy(dtype=float)
    # Normalize by a reference value: changing currency cancels before taking logs.
    target = np.log(values / values[0])
    coefficients, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank != design.shape[1]:
        raise ValueError("Age/CA/PA model is rank deficient")
    predicted = design @ coefficients
    residual = predicted - target
    total_variation = float(np.sum((target - target.mean()) ** 2))
    if total_variation == 0:
        raise ValueError("No value variation to model")
    scored = population.copy()
    scored["bargain_score"] = residual
    scored["expected_value_multiple"] = np.exp(residual)
    scored["predicted_value"] = np.exp(predicted) * values[0]
    return scored, 1 - float(np.sum(residual**2)) / total_variation


def rank_elite(scored: pd.DataFrame) -> pd.DataFrame:
    elite = scored.loc[scored.pa.ge(150)].copy()
    # Numerical ties are resolved by UID, independent of source row order.
    elite["_rank_score"] = elite.bargain_score.round(10)
    return (
        elite.sort_values(["_rank_score", "uid"], ascending=[False, True])
        .drop(columns="_rank_score")
        .reset_index(drop=True)
    )


def verify_model(population: pd.DataFrame, ranked: pd.DataFrame, refits: int) -> dict:
    published = ranked.head(20)
    if len(published) < 20:
        raise ValueError("At least 20 qualifying elite prospects are needed for this demo")
    if not (
        ranked.age.between(15, 21).all()
        and ranked.ca.notna().all()
        and ranked.pa.ge(150).all()
        and ranked.pa_range.isna().all()
        and ranked.value.gt(0).all()
        and ranked.value_state.eq("ok").all()
        and ranked.name.str.strip().ne("").all()
    ):
        raise AssertionError("Published-row eligibility failed")
    for factor in (0.01, 1.234567, 1000.0):
        converted = population.copy()
        converted["value"] = converted.value * factor
        scaled, _ = fit_model(converted)
        scaled_rank = rank_elite(scaled)
        if scaled_rank.uid.tolist() != ranked.uid.tolist():
            raise AssertionError("Ranking changed under a common currency factor")
        np.testing.assert_allclose(
            scaled_rank.bargain_score, ranked.bargain_score, rtol=1e-10, atol=1e-10
        )
    shuffled, _ = fit_model(eligible_population(population.sample(frac=1, random_state=41)))
    if rank_elite(shuffled).uid.tolist() != ranked.uid.tolist():
        raise AssertionError("Ranking changed after shuffling the input")
    design = design_matrix(population)
    target = np.log(population.value.to_numpy(dtype=float) / float(population.value.iloc[0]))
    rng = np.random.default_rng(20260922)
    exact_order = same_members = 0
    baseline = published.uid.tolist()
    for _ in range(refits):
        indices = rng.integers(0, len(population), size=len(population))
        coefficients = np.linalg.lstsq(design[indices], target[indices], rcond=None)[0]
        trial = population.copy()
        trial["bargain_score"] = design @ coefficients - target
        result = rank_elite(trial).head(20).uid.tolist()
        exact_order += result == baseline
        same_members += set(result) == set(baseline)
    return {
        "published_rows_valid": True,
        "currency_factors_checked": [0.01, 1.234567, 1000.0],
        "input_order_invariant": True,
        "bootstrap_seed": 20260922,
        "bootstrap_refits": refits,
        "bootstrap_top20_same_order": exact_order,
        "bootstrap_top20_same_members": same_members,
    }


def read_save(path: Path) -> tuple[pd.DataFrame, str]:
    with fmsave.open(path, strict=True) as save:
        game_date = str(save.info.game_date)
        players = save.players()
        # Select only the columns the demo needs, keeping memory use bounded.
        frame = pd.DataFrame(
            {
                "uid": p.uid,
                "name": p.name,
                "club": p.club_short_name or p.club_name or "Unattached / unresolved",
                "age": p.age,
                "position": "/".join(p.natural_positions) or "-",
                "ca": p.ability.current,
                "pa": p.ability.potential,
                "pa_range": p.ability.potential_range_code,
                "value": p.transfer_value,
                "value_state": str(p.transfer_value_state),
                "acceleration": p.attributes.acceleration,
                "pace": p.attributes.pace,
                "determination": p.attributes.determination,
                "professionalism": p.personality.professionalism if p.personality else None,
            }
            for p in players
        )
    return frame, game_date


def canvas(kicker: str, title: str, subtitle: str):
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FOREGROUND})
    fig = plt.figure(figsize=(12, 15), dpi=150, facecolor=BACKGROUND)
    fig.text(0.065, 0.957, kicker, fontsize=18, weight="bold", color=ACCENT)
    fig.text(0.065, 0.921, title, fontsize=33, weight="bold", va="top", linespacing=1.12)
    fig.text(0.065, 0.827, subtitle, fontsize=20, color=MUTED, va="top", linespacing=1.25)
    return fig


def footer(fig, text: str):
    fig.text(
        0.065,
        0.077,
        text,
        fontsize=18,
        color=MUTED,
        va="top",
        linespacing=1.25,
    )
    fig.text(0.065, 0.019, "Source: my FM26 save, fmsave 0.4.1", fontsize=15, color=MUTED)
    fig.text(
        0.935,
        0.019,
        "Dr. Randal S. Olson | randalolson.com",
        ha="right",
        fontsize=15,
        color=MUTED,
    )


def save_figure(fig, output: Path, name: str):
    import matplotlib.pyplot as plt

    fig.savefig(output / name, facecolor=BACKGROUND, dpi=150)
    plt.close(fig)


def render_hero(ranked: pd.DataFrame, metrics: dict, output: Path):
    from matplotlib import colors, ticker

    fig = canvas(
        "01 / FINDING FM26 BARGAINS",
        "FM values these wonderkids\nfar below similar players",
        f"{metrics['players']:,} players searched, {len(ranked):,} elite U21 prospects plotted\n"
        "The five labeled players lead the age + CA + PA model ranking",
    )
    ax = fig.add_axes((0.12, 0.215, 0.815, 0.525), facecolor=BACKGROUND)
    ax.set_box_aspect(1)
    points = ax.scatter(
        ranked.value,
        ranked.pa,
        s=ranked.ca * 0.55,
        c=ranked.age,
        cmap=colors.LinearSegmentedColormap.from_list("age", ["#b7d6d9", "#176879"]),
        norm=colors.Normalize(15, 21),
        alpha=0.65,
        edgecolors="none",
    )
    ax.set_xscale("log")
    ax.set_ylim(147, ranked.pa.max() + 3)
    ax.set_xlim(ranked.value.min() / 1.8, ranked.value.max() * 1.5)
    ax.set_xlabel(
        "FM estimated value (save units, log scale)",
        fontsize=20,
        color=FOREGROUND,
        labelpad=12,
    )
    ax.set_ylabel("Potential ability (PA, 1-200)", fontsize=22, color=FOREGROUND, labelpad=10)
    ax.xaxis.set_major_formatter(
        ticker.FuncFormatter(
            lambda v, _: f"{v / 1e6:g}m" if v >= 1e6 else f"{v / 1e3:g}k" if v >= 1e3 else f"{v:g}"
        )
    )
    ax.tick_params(colors=MUTED, labelsize=20, length=0, pad=8)
    ax.minorticks_off()
    ax.grid(axis="y", color="#e9edef", linewidth=0.7)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    # Label only the first five bargains; table supplies the full top ten.
    offsets = [(0, 40), (7, 15), (10, 8), (10, -23), (-170, 35)]
    for i, row in ranked.head(5).iterrows():
        label = f"{i + 1}. {row['name']}"
        if len(label) > 23:
            first, last = label.rsplit(" ", 1)
            label = f"{first}\n{last}"
        ax.annotate(
            label,
            (row.value, row.pa),
            xytext=offsets[i],
            textcoords="offset points",
            fontsize=20,
            color=FOREGROUND,
            weight="bold",
            arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.8},
        )
    cax = fig.add_axes((0.11, 0.124, 0.29, 0.008))
    cb = fig.colorbar(points, cax=cax, orientation="horizontal", ticks=[15, 17, 19, 21])
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelsize=18, length=0)
    fig.text(0.11, 0.147, "Age in years", fontsize=18, color=MUTED)
    fig.text(0.60, 0.12, "Point area =\ncurrent ability (CA)", fontsize=18, color=MUTED)
    footer(
        fig,
        "Undervalued by FM's estimated value, not an asking price.\n"
        "Exact CA and PA shown from my single-player save.",
    )
    save_figure(fig, output, "01_wonderkid_chart.png")


def compact_value(value: float) -> str:
    """Display raw save currency units without assuming a currency symbol."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:g}"


def render_table(ranked: pd.DataFrame, output: Path):
    fig = canvas(
        "02 / THE TOP TEN",
        "Ten wonderkids the\nmodel rates as bargains",
        "Ages 15-21, fixed PA of at least 150\n"
        "Model / FM compares predicted value with FM's estimated value",
    )
    left = 0.065
    fig.text(left, 0.751, "PLAYER, CLUB, AGE, POSITION", fontsize=17, color=MUTED)
    columns = [
        (0.535, "CA"),
        (0.615, "PA"),
        (0.745, "FM VALUE"),
        (0.89, "MODEL / FM"),
    ]
    for x, label in columns:
        fig.text(x, 0.751, label, ha="center", fontsize=17, color=MUTED)
    for i, row in ranked.head(10).iterrows():
        y = 0.71 - i * 0.0565
        fig.text(left, y, f"{i + 1:02d}  {row['name']}", fontsize=24, weight="bold")
        details = f"{row.club}, {int(row.age)}, {row.position}"
        fig.text(left + 0.035, y - 0.024, details, fontsize=20, color=MUTED)
        vals = [
            int(row.ca),
            int(row.pa),
            compact_value(row.value),
            f"{row.expected_value_multiple:.1f}×",
        ]
        for (x, _), value in zip(columns, vals, strict=True):
            fig.text(
                x,
                y,
                str(value),
                ha="center",
                fontsize=24,
                color=ACCENT if x == 0.89 else FOREGROUND,
            )
        attributes = [row.acceleration, row.pace, row.determination, row.professionalism]
        for x, label, value in zip(
            (0.54, 0.66, 0.78, 0.90), ("Acc", "Pac", "Det", "Pro"), attributes, strict=True
        ):
            displayed = "-" if pd.isna(value) else str(int(value))
            fig.text(x, y - 0.024, f"{label} {displayed}", ha="center", fontsize=20, color=MUTED)
    fig.text(
        left,
        0.137,
        "Acc = Acceleration, Pac = Pace, Det = Determination, Pro = Professionalism\n"
        "Attributes: 1-20. FM value: save currency units, k = thousand, m = million.",
        fontsize=17,
        color=MUTED,
        linespacing=1.4,
    )
    footer(
        fig,
        "Undervalued by FM's estimated value. Actual transfer demands can differ.\n"
        "CA, PA and Professionalism are hidden player data.",
    )
    save_figure(fig, output, "02_top10_table.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=os.environ.get("SAVE_PATH"))
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "wonderkids")
    parser.add_argument("--bootstrap", type=int, default=100)
    args = parser.parse_args()
    if args.save is None:
        parser.error("Set SAVE_PATH or pass --save")
    if args.bootstrap < 1:
        parser.error("--bootstrap must be positive")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".local"):
        parser.error("Generated save-derived results must remain under this repository's .local/")
    output.mkdir(parents=True, exist_ok=True)
    frame, game_date = read_save(args.save)
    population = eligible_population(frame)
    scored, r_squared = fit_model(population)
    ranked = rank_elite(scored)
    metrics = {
        "fmsave_version": fmsave.__version__,
        "game_date": game_date,
        "players": len(frame),
        "age_15_to_21_players": int(frame.age.between(15, 21).sum()),
        "eligible_model_population": len(population),
        "elite_prospects": len(ranked),
        "log_value_r_squared": r_squared,
        **verify_model(population, ranked, args.bootstrap),
    }
    # Private artifacts only: never add this directory to version control.
    ranked.to_csv(output / "elite_ranking.csv", index=False)
    ranked.head(20).to_json(output / "top20.json", orient="records", indent=2)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    render_hero(ranked, metrics, output)
    render_table(ranked, output)
    print(json.dumps(metrics, indent=2))
    print(f"Local artifacts: {output}")


if __name__ == "__main__":
    main()
