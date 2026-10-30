"""Corpus checks for Save.player_season_stats. Output never includes real save content.

Values read from a save never appear in an assert or a message: each check reduces to a
boolean, and failures are reported by file name and field name only.

The screen checks compare every figure the owner's screenshots recorded (squad statistics
screens and player profile panels, transcribed into the recorded values) with the rows the reader
returns for the save each screenshot was paired with. Those saves are live copies kept beside
the manifest's two, so a check whose save is not present is skipped rather than failed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

import fmsave
from fmsave import PlayerSeasonStats, SeasonStatsKind
from tests import conftest as corpus_conftest
from tests.corpus.reporting import CorpusMismatches

pytestmark = [pytest.mark.corpus, pytest.mark.corpus_full]

SCREENS_2037 = "squad_season_stats_shown"
SCREENS_2040 = "season_stats_screenshots_2026_09_28"
COLUMN_SCREENS_2040 = ("squad_stats_columns_2026_09_28_b", "squad_stats_columns_2026_09_28_c")
MILES_TO_KM = 1.609344

# The panel rows of the profile screens, by slot number as the recorded values key them.
PANEL_KINDS = {
    "0": SeasonStatsKind.NON_COMPETITIVE,
    "1": SeasonStatsKind.LEAGUE,
    "2": SeasonStatsKind.CUP,
    "3": SeasonStatsKind.CONTINENTAL,
    "4": SeasonStatsKind.INTERNATIONAL,
    "5": SeasonStatsKind.OVERALL,
}


def number(row: PlayerSeasonStats, field_name: str) -> float:
    """A field as a number, with None (a keeper's outfield word, or the reverse) read as the 0
    the game shows."""
    value = getattr(row, field_name)
    return 0 if value is None else value


def per_90(field_name: str) -> Callable[[PlayerSeasonStats], float]:
    """The row's own per-90 rate for a count, rounded as the game shows it."""
    return lambda row: round(number(row, f"{field_name}_per_90"), 1)


def count(field_name: str) -> Callable[[PlayerSeasonStats], float]:
    return lambda row: number(row, field_name)


def save_ratio(row: PlayerSeasonStats) -> float:
    return round(number(row, "save_percent"))


def pass_completion(row: PlayerSeasonStats) -> float:
    return round(number(row, "pass_completion_percent"))


# Each squad-screen column the transcriptions hold: how a row gives the figure it shows, and how
# a cell's text becomes that figure. Columns with no stored figure behind them are left out.
def as_number(text: str) -> float | None:
    cleaned = text.strip().rstrip("%")
    return None if cleaned in ("", "-") else float(cleaned)


def as_km(text: str) -> float | None:
    return round(float(text.removesuffix("mi")) * MILES_TO_KM, 1)


SQUAD_COLUMNS: dict[
    str, tuple[Callable[[PlayerSeasonStats], float], Callable[[str], float | None]]
] = {
    "Minutes": (count("minutes"), as_number),
    "Shots": (count("shots"), as_number),
    "ShT": (count("shots_on_target"), as_number),
    "Key": (count("key_passes"), as_number),
    "OP-Crs C": (count("open_play_crosses_completed"), as_number),
    "OP-Crs A": (count("open_play_crosses_attempted"), as_number),
    "Cr C": (count("crosses_completed"), as_number),
    "Cr A": (count("crosses_attempted"), as_number),
    "Sv %": (save_ratio, as_number),
    "xGP": (lambda row: round(row.expected_goals_prevented, 2), as_number),
    "PsP": (count("progressive_passes"), as_number),
    "Ps C": (count("passes_completed"), as_number),
    "Pas A": (count("passes_attempted"), as_number),
    "Hdrs A": (count("aerial_challenges_attempted"), as_number),
    "Hdrs": (count("headers_won"), as_number),
    "CCC": (count("clear_cut_chances_created"), as_number),
    "Off": (count("offsides"), as_number),
    "Drb": (count("dribbles"), as_number),
    "Distance": (lambda row: row.distance_km, as_km),
    "Svh": (count("saves_held"), as_number),
    "Svp": (count("saves_parried"), as_number),
    "Svt": (count("saves_tipped"), as_number),
    "Free Kick Shots": (count("free_kick_shots"), as_number),
    "Blk": (count("blocks"), as_number),
    "Tck C": (count("tackles_completed"), as_number),
    "Tck A": (count("tackles_attempted"), as_number),
    "Shts Blckd": (count("shots_blocked"), as_number),
    "Pres C": (count("pressures_completed"), as_number),
    "Pres A": (count("pressures_attempted"), as_number),
    "K Tck": (count("key_tackles"), as_number),
    "Itc": (count("interceptions"), as_number),
    "Clearances": (count("clearances"), as_number),
    "Shots From Outside The Box Per 90 minutes": (per_90("shots_outside_box"), as_number),
    "K Hdrs/90": (per_90("key_headers"), as_number),
    "OP-KP/90": (per_90("open_play_key_passes"), as_number),
    "Ch C/90": (per_90("clear_cut_chances_created"), as_number),
    "Poss Won/90": (per_90("possession_won"), as_number),
    "Sprints/90": (per_90("high_intensity_sprints"), as_number),
}
# Distance is shown in miles to one decimal, so a kilometre figure can differ by the rounding.
DISTANCE_TOLERANCE_KM = 0.1 * MILES_TO_KM


def appearances(text: str) -> tuple[int, int]:
    """(starts, substitute appearances) from "17" or "17 (9)"."""
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    return numbers[0], numbers[1] if len(numbers) > 1 else 0


def rows_by_name(rows: Iterable[PlayerSeasonStats]) -> dict[str, list[PlayerSeasonStats]]:
    grouped: dict[str, list[PlayerSeasonStats]] = defaultdict(list)
    for row in rows:
        if row.player_name is not None:
            grouped[row.player_name].append(row)
    return grouped


def overall_rows(
    grouped: dict[str, list[PlayerSeasonStats]], name: str, club_uid: int
) -> list[PlayerSeasonStats]:
    return [
        row
        for row in grouped.get(name, [])
        if row.kind == SeasonStatsKind.OVERALL and row.club_uid == club_uid
    ]


def open_paired_save(relative_name: str) -> fmsave.Save:
    save_path = corpus_conftest.corpus_root() / relative_name
    if not save_path.is_file():
        pytest.skip("paired live save not present")
    return fmsave.open(save_path)


def recorded_screens(recorded_values: dict[str, Any], key: str) -> tuple[str, dict[str, Any]]:
    for relative_name, entry in recorded_values.items():
        if isinstance(entry, dict) and key in entry.get("screens", {}):
            return relative_name, entry["screens"]
    pytest.skip("no recorded screenshots of this kind")


def test_the_2037_squad_screen_matches_every_column(recorded_values: dict[str, Any]) -> None:
    relative_name, recorded = recorded_screens(recorded_values, SCREENS_2037)
    mismatches = CorpusMismatches()
    label = Path(relative_name).name
    with open_paired_save(relative_name) as career_save:
        club_uid = next(iter(career_save.managed_clubs())).club_uid
        grouped = rows_by_name(career_save.player_season_stats())
    for shown in recorded[SCREENS_2037]["rows"]:
        candidates = overall_rows(grouped, shown["player"], club_uid)
        mismatches.check(label, "player found", len(candidates) == 1)
        if len(candidates) != 1:
            continue
        row = candidates[0]
        figures = {
            "starts": row.starts == shown["starts"],
            "substitute_appearances": row.substitute_appearances
            == (shown["substitute_appearances"] or 0),
            "minutes": row.minutes == shown["minutes"],
            "average_rating": row.average_rating is not None
            and round(row.average_rating, 2) == shown["average_rating"],
            "goals": row.goals == shown["goals"],
            "assists": row.assists == shown["assists"],
            "expected_goals": round(row.expected_goals, 2) == shown["xg"],
            "expected_assists": round(row.expected_assists, 2) == shown["xa"],
            "tackles_per_90": per_90("tackles_completed")(row) == shown["tackles_per_90"],
            "interceptions_per_90": per_90("interceptions")(row) == shown["interceptions_per_90"],
            "pass_completion": pass_completion(row) == shown["pass_completion_percent"],
        }
        for field_name, matched in figures.items():
            mismatches.check(label, field_name, matched)
    mismatches.fail_if_any()


def test_the_2040_squad_screens_match_every_column(recorded_values: dict[str, Any]) -> None:
    relative_name, recorded = recorded_screens(recorded_values, SCREENS_2040)
    screens = recorded[SCREENS_2040]
    mismatches = CorpusMismatches()
    label = Path(relative_name).name
    with open_paired_save(relative_name) as career_save:
        club_uid = next(iter(career_save.managed_clubs())).club_uid
        grouped = rows_by_name(career_save.player_season_stats())
    for name, figures in screens["main"].items():
        starts, subs, minutes, rating, goals, assists, xg, xa, tackles, interceptions, passes = (
            figures
        )
        candidates = overall_rows(grouped, name, club_uid)
        mismatches.check(label, "player found", len(candidates) == 1)
        if len(candidates) != 1:
            continue
        row = candidates[0]
        mismatches.check(
            label, "appearances", (row.starts, row.substitute_appearances) == (starts, subs)
        )
        mismatches.check(label, "minutes", row.minutes == minutes)
        mismatches.check(
            label,
            "average_rating",
            row.average_rating is not None and round(row.average_rating, 2) == rating,
        )
        mismatches.check(label, "goals and assists", (row.goals, row.assists) == (goals, assists))
        mismatches.check(label, "expected_goals", round(row.expected_goals, 2) == xg)
        mismatches.check(label, "expected_assists", round(row.expected_assists, 2) == xa)
        mismatches.check(label, "tackles_per_90", per_90("tackles_completed")(row) == tackles)
        mismatches.check(
            label, "interceptions_per_90", per_90("interceptions")(row) == interceptions
        )
        mismatches.check(label, "pass_completion", pass_completion(row) == passes)
    for name, (tackles_completed, fouls, tackles_attempted, yellow, red) in screens[
        "defending"
    ].items():
        for row in overall_rows(grouped, name, club_uid):
            mismatches.check(
                label,
                "defending",
                (
                    row.tackles_completed,
                    row.fouls_made,
                    row.tackles_attempted,
                    row.yellow_cards,
                    row.red_cards,
                )
                == (tackles_completed, fouls, tackles_attempted, yellow, red),
            )
    for name, (goals, shots, penalties_scored, penalties_taken) in screens["shooting"].items():
        for row in overall_rows(grouped, name, club_uid):
            mismatches.check(label, "shooting", (row.goals, row.shots) == (goals, shots))
            if penalties_taken is not None:
                mismatches.check(
                    label,
                    "penalties",
                    (row.penalties_scored, row.penalties_taken)
                    == (penalties_scored, penalties_taken),
                )
    for name, (
        _,
        attempted,
        mistakes,
        won,
        aerial,
        crosses_completed,
        crosses_attempted,
    ) in screens["passing"].items():
        for row in overall_rows(grouped, name, club_uid):
            mismatches.check(
                label,
                "passing",
                (
                    row.passes_attempted,
                    row.mistakes_leading_to_goal,
                    number(row, "headers_won"),
                    number(row, "aerial_challenges_attempted"),
                    row.crosses_completed,
                    row.crosses_attempted,
                )
                == (attempted, mistakes, won, aerial, crosses_completed, crosses_attempted),
            )
    for name, (clean_sheets, allowed, saves, _) in screens["goalkeeping"].items():
        for row in overall_rows(grouped, name, club_uid):
            mismatches.check(
                label,
                "goalkeeping",
                (row.clean_sheets, row.goals_allowed, save_ratio(row))
                == (clean_sheets, allowed, saves),
            )
    for key in COLUMN_SCREENS_2040:
        for image in recorded.get(key, {}).get("images", []):
            if image["kind"] != "data_table":
                continue
            for shown in image["rows"]:
                candidates = overall_rows(grouped, shown["player"], club_uid)
                mismatches.check(label, "player found", len(candidates) == 1)
                if len(candidates) != 1:
                    continue
                row = candidates[0]
                for column, cell in zip(image["columns"], shown["cells"], strict=True):
                    if column == "Appearances":
                        mismatches.check(
                            label,
                            column,
                            (row.starts, row.substitute_appearances) == appearances(cell),
                        )
                        continue
                    if column not in SQUAD_COLUMNS:
                        continue
                    read_row, read_cell = SQUAD_COLUMNS[column]
                    expected = read_cell(cell)
                    if expected is None:
                        continue
                    tolerance = DISTANCE_TOLERANCE_KM if column == "Distance" else 1e-9
                    mismatches.check(label, column, abs(read_row(row) - expected) <= tolerance)
    mismatches.fail_if_any()


def test_the_2040_profile_panels_match_every_competition_row(
    recorded_values: dict[str, Any],
) -> None:
    relative_name, recorded = recorded_screens(recorded_values, SCREENS_2040)
    panels = recorded[SCREENS_2040]["category_panels"]
    mismatches = CorpusMismatches()
    label = Path(relative_name).name
    with open_paired_save(relative_name) as career_save:
        team_by_uid = {player.uid: player.team_id for player in career_save.players()}
        grouped = rows_by_name(career_save.player_season_stats())
    for panel_key, slots in panels.items():
        name, which = panel_key.split("|")
        # A name some other player shares is matched by the panel itself: at least one of the
        # players so named must show every row of it.
        candidate_uids = {row.player_uid for row in grouped.get(name, [])}
        matched_by_any = False
        for player_uid in candidate_uids:
            own_team = team_by_uid.get(player_uid)
            rows = [
                row
                for row in grouped[name]
                if row.player_uid == player_uid and (row.team_id == own_team) == (which == "main")
            ]
            by_kind = {row.kind: row for row in rows}
            if all(
                panel_row_matches(by_kind.get(PANEL_KINDS[slot]), values)
                for slot, values in slots.items()
            ):
                matched_by_any = True
        mismatches.check(label, "profile panel", matched_by_any)
    mismatches.fail_if_any()


def panel_row_matches(row: PlayerSeasonStats | None, values: list[Any]) -> bool:
    """Whether a row shows what one panel row did; an outfield panel has 11 values, a keeper's 12."""
    if row is None:
        return False
    if len(values) == 12:
        (
            apps,
            allowed,
            goals,
            assists,
            clean_sheets,
            pom,
            yellow,
            red,
            passes,
            fouls,
            against,
            rating,
        ) = values
        shown = (row.starts + row.substitute_appearances, row.goals_allowed, row.clean_sheets)
        if shown != (apps, allowed, clean_sheets):
            return False
    else:
        starts, subs, goals, assists, pom, yellow, red, passes, fouls, against, rating = values
        if (row.starts, row.substitute_appearances) != (starts, subs):
            return False
    pass_share = row.pass_completion_percent
    return (
        (row.goals, row.assists, row.player_of_the_match, row.yellow_cards, row.red_cards)
        == (goals, assists, pom, yellow, red)
        and (row.fouls_made, row.fouls_against) == (fouls, against)
        and pass_share is not None
        and abs(pass_share - passes) < 0.051
        and row.average_rating is not None
        and abs(row.average_rating - rating) < 0.006
    )


def test_every_manifest_save_reads_strictly(corpus_save_paths: dict[str, Path]) -> None:
    """Every gate holds on every save the manifest lists, which a strict open turns into an error."""
    mismatches = CorpusMismatches()
    for relative_name, save_path in corpus_save_paths.items():
        with fmsave.open(save_path, strict=True) as career_save:
            try:
                rows = career_save.player_season_stats()
            except fmsave.ReaderCheckError:
                mismatches.check(Path(relative_name).name, "strict read", False)
                continue
        mismatches.check(Path(relative_name).name, "rows", len(rows) > 0)
    mismatches.fail_if_any()


def test_non_penalty_xg_differs_from_xg_only_by_the_penalties_taken(
    corpus_save_paths: dict[str, Path],
) -> None:
    """Every row's non-penalty xG equals its xG when no penalty was taken, and otherwise falls
    short of it by no more than a penalty's xG for each one taken."""
    largest_penalty_xg = 0.81
    mismatches = CorpusMismatches()
    for relative_name, save_path in corpus_save_paths.items():
        with fmsave.open(save_path) as career_save:
            rows = career_save.player_season_stats()
        label = Path(relative_name).name
        mismatches.check(
            label,
            "non_penalty_expected_goals",
            all(
                row.non_penalty_expected_goals == row.expected_goals
                if row.penalties_taken == 0
                else 0
                <= row.expected_goals - row.non_penalty_expected_goals
                <= largest_penalty_xg * row.penalties_taken + 1e-9
                for row in rows
            ),
        )
    mismatches.fail_if_any()
