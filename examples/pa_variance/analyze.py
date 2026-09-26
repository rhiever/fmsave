"""Measure how much young players' PA changes between fresh FM26 saves, without embedded data.

Run from the repository root; see README.md beside this script. Generated results
must remain under the gitignored .local/ directory.
"""

from __future__ import annotations

import argparse
import itertools
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
SAME = "#b9c1c6"
IDENTITY = ["name", "birth_date", "nation_id"]
# Change in PA between two saves, grouped into bars; the ends are open-ended.
BINS = [
    (-999, -15, "≤ −15"),
    (-14, -10, "[−14, −10]"),
    (-9, -5, "[−9, −5]"),
    (-4, -1, "[−4, −1]"),
    (0, 0, "Same"),
    (1, 4, "[+1, +4]"),
    (5, 9, "[+5, +9]"),
    (10, 14, "[+10, +14]"),
    (15, 999, "≥ +15"),
]


def read_save(path: Path) -> tuple[pd.DataFrame, str]:
    """Players with a usable identity and a positive PA, one row each."""
    with fmsave.open(path) as save:
        game_date = save.info.game_date.isoformat()
        players = save.players().to_pandas()
    frame = players[[*IDENTITY, "age", "ability_potential"]].rename(
        columns={"ability_potential": "pa"}
    )
    frame = frame.assign(
        birth_date=pd.to_datetime(frame.birth_date, errors="coerce"),
        age=pd.to_numeric(frame.age, errors="coerce"),
        pa=pd.to_numeric(frame.pa, errors="coerce"),
    )
    frame = frame.dropna(subset=[*IDENTITY, "age", "pa"])
    frame = frame[frame.name.str.strip().ne("") & frame.pa.gt(0)]
    # A name, birth date and nationality shared by two people identifies neither of them.
    return frame.drop_duplicates(IDENTITY, keep=False).reset_index(drop=True), game_date


def compare(first: pd.DataFrame, second: pd.DataFrame, max_age: int) -> pd.DataFrame:
    """The same players in two saves, matched by identity rather than uid.

    Player uids are not stable between separately started games, so a uid join would
    pair different people. Age is taken from the first save.
    """
    both = first.merge(second[[*IDENTITY, "pa"]], on=IDENTITY, suffixes=("_1", "_2"))
    both = both[both.age.le(max_age)].copy()
    both["change"] = both.pa_2 - both.pa_1
    return both


def summarize(pairs: dict[str, pd.DataFrame], threshold: int) -> dict:
    """Every pair once for the change distribution; both directions for the threshold question."""
    pooled = pd.concat(pairs.values(), ignore_index=True)
    change = pooled.change.abs()
    per_pair, crossings = {}, []
    for label, both in pairs.items():
        for before, after in (("pa_1", "pa_2"), ("pa_2", "pa_1")):
            above = both[both[before].ge(threshold)]
            crossings.append((len(above), int(above[after].lt(threshold).sum())))
        per_pair[label] = {"players": len(both), "share_changed": float(both.change.ne(0).mean())}
    above_total = sum(n for n, _ in crossings)
    return {
        "comparisons": len(pooled),
        "share_changed": float(change.gt(0).mean()),
        "mean_absolute_change": float(change.mean()),
        "share_changed_10_plus": float(change.ge(10).mean()),
        "share_changed_20_plus": float(change.ge(20).mean()),
        "share_rising": float(pooled.change.gt(0).mean()),
        "share_falling": float(pooled.change.lt(0).mean()),
        f"pa_{threshold}_plus_in_one_save": above_total,
        f"share_of_those_below_{threshold}_in_another": sum(k for _, k in crossings) / above_total
        if above_total
        else None,
        "pairs": per_pair,
    }


def bin_shares(change: pd.Series) -> list[float]:
    return [float(change.between(lo, hi).mean()) for lo, hi, _ in BINS]


def canvas(title: str, subtitle: str):
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FOREGROUND})
    fig = plt.figure(figsize=(12, 12), dpi=150, facecolor=BACKGROUND)
    fig.text(0.065, 0.95, title, fontsize=33, weight="bold", va="top", linespacing=1.12)
    fig.text(0.065, 0.83, subtitle, fontsize=19, color=MUTED, va="top", linespacing=1.25)
    return fig


def footer(fig, saves: int):
    fig.text(
        0.065,
        0.02,
        f"Source: {saves} FM26 saves, parsed via fmsave v{fmsave.__version__}",
        fontsize=13,
        color=MUTED,
    )
    fig.text(
        0.935, 0.02, "Dr. Randal S. Olson | randalolson.com", ha="right", fontsize=13, color=MUTED
    )


def save_figure(fig, output: Path, name: str):
    import matplotlib.pyplot as plt

    fig.savefig(output / name, facecolor=BACKGROUND, dpi=150)
    plt.close(fig)


def render_distribution(change: pd.Series, summary: dict, saves: int, max_age: int, output: Path):
    shares = bin_shares(change)
    fig = canvas(
        f"Start a new save, and {summary['share_changed']:.0%} of young\nplayers get a different PA",
        f"Change in PA for every player aged {max_age} or under between 2 fresh FM26 saves",
    )
    ax = fig.add_axes((0.065, 0.2, 0.87, 0.54), facecolor=BACKGROUND)
    x = np.arange(len(BINS))
    ax.bar(
        x,
        [s * 100 for s in shares],
        width=0.78,
        color=[SAME if lo == 0 else ACCENT for lo, _, _ in BINS],
    )
    for xi, share in zip(x, shares):
        ax.text(
            xi,
            share * 100 + 0.4,
            f"{share:.0%}",
            ha="center",
            va="bottom",
            fontsize=18,
            weight="bold",
            color=MUTED if BINS[xi][0] == 0 else ACCENT,
        )
    ax.set_xticks(x, [label for _, _, label in BINS], fontsize=13, color=MUTED)
    ax.set_xlabel("Change in PA between 2 saves", fontsize=17, color=FOREGROUND, labelpad=12)
    ax.set_yticks([])
    ax.tick_params(length=0, pad=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c8cfd3")
    footer(fig, saves)
    save_figure(fig, output, "01_pa_change.png")


def render_players(saves: list[pd.DataFrame], names: list[str], max_age: int, output: Path):
    rows = []
    for name in names:
        # Common names repeat, so pick the one young player of that name, then follow
        # that identity (name, birth date, nationality) into the other saves.
        found = saves[0][saves[0].name.eq(name) & saves[0].age.le(max_age)]
        if len(found) != 1:
            print(f"Skipped {name!r}: not exactly one player aged {max_age} or under")
            continue
        key = found[IDENTITY].iloc[0]
        values = [frame.loc[(frame[IDENTITY] == key).all(axis=1), "pa"] for frame in saves]
        if all(len(v) == 1 for v in values):
            rows.append((name, [int(v.iloc[0]) for v in values]))
        else:
            print(f"Skipped {name!r}: not in every save")
    if not rows:
        return
    rows.sort(key=lambda row: max(row[1]) - min(row[1]))
    span = max(max(r[1]) - min(r[1]) for r in rows)
    fig = canvas(
        f"Wonderkid PA can swing up to\n{span} points between saves",
        f"PA of {len(rows)} wonderkids in {len(saves)} fresh FM26 saves; each dot is one save",
    )
    ax = fig.add_axes((0.36, 0.14, 0.46, 0.62), facecolor=BACKGROUND)
    for y, (name, pas) in enumerate(rows):
        ax.hlines(y, min(pas), max(pas), color=ACCENT, alpha=0.3, lw=12, zorder=1)
        ax.scatter(
            pas, [y] * len(pas), s=170, color=ACCENT, edgecolors="white", linewidths=1, zorder=2
        )
        label = "fixed" if min(pas) == max(pas) else f"{min(pas)}-{max(pas)}"
        ax.text(
            1.04,
            y,
            label,
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=17,
            color=FOREGROUND,
        )
    ax.set_yticks(range(len(rows)), [name for name, _ in rows], fontsize=17, color=FOREGROUND)
    ax.invert_yaxis()
    ax.set_xlabel("PA (1-200)", fontsize=16, color=FOREGROUND, labelpad=10)
    ax.tick_params(length=0, colors=MUTED, labelsize=15)
    ax.tick_params(axis="y", colors=FOREGROUND, labelsize=17)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color="#e9edef", linewidth=0.8)
    ax.set_axisbelow(True)
    footer(fig, len(saves))
    save_figure(fig, output, "02_wonderkids.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--save", type=Path, action="append", help="a fresh save; pass at least two"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "pa_variance")
    parser.add_argument("--max-age", type=int, default=21, help="oldest age included (default 21)")
    parser.add_argument(
        "--threshold", type=int, default=150, help="PA cutoff for the wonderkid question"
    )
    parser.add_argument(
        "--players", default="", help="semicolon-separated names for the per-player chart"
    )
    args = parser.parse_args()
    paths = args.save or [Path(p) for p in os.environ.get("SAVE_PATHS", "").split(os.pathsep) if p]
    if len(paths) < 2:
        parser.error("Pass --save at least twice, or set SAVE_PATHS to two or more saves")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".local"):
        parser.error("Generated save-derived results must remain under this repository's .local/")
    output.mkdir(parents=True, exist_ok=True)

    saves, dates = zip(*(read_save(path) for path in paths))
    pairs = {
        f"{i + 1}-{j + 1}": compare(saves[i], saves[j], args.max_age)
        for i, j in itertools.combinations(range(len(saves)), 2)
    }
    summary = summarize(pairs, args.threshold)
    change = pd.concat(pairs.values(), ignore_index=True).change
    metrics = {
        "fmsave_version": fmsave.__version__,
        "saves": len(saves),
        "game_dates": list(dates),
        "max_age": args.max_age,
        **summary,
        "bins": dict(zip([b[2] for b in BINS], bin_shares(change))),
    }
    # Private artifacts only: never add this directory to version control.
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    render_distribution(change, summary, len(saves), args.max_age, output)
    if args.players:
        render_players(
            list(saves),
            [n.strip() for n in args.players.split(";") if n.strip()],
            args.max_age,
            output,
        )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Local artifacts: {output}")


if __name__ == "__main__":
    main()
