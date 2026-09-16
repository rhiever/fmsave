from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import ResultStats
from fmsave.checks import GateResult, enforce, evaluate_results
from fmsave.models.fixtures import Fixture
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.results import (
    RawStageResult,
    apply_results,
    calendar_dates,
    find_result_layout,
    result_in_scope,
)
from tests.fixtures.career import (
    ATHLETIC_TEAM_A,
    CUP_FIXTURE_STAGE_ID,
    FIXTURE_KICK_OFF_YEAR,
    FIXTURE_STAGE_ID,
    MAIN_CLUSTER_FIXTURES,
    NORTHBRIDGE_TEAM_A,
    RESULT_R22,
    SOUTHPORT_TEAM,
    UNRESOLVED_FIXTURE_STAGE_ID,
    ExampleResult,
    career_fragment,
)

FILE_NAME = "career example.fm"
MEBIBYTE = 1024 * 1024
FULL_SIZE_SPAN_BYTES = 120 * MEBIBYTE
SMALL_SPAN_BYTES = 1 * MEBIBYTE
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, 4000, "").layout

RESULT_GATE_NAMES = ("result_records_minimum", "results_joined", "results_for_unplayed")
DECLARED_REGIONS = (
    "tc_record_man",
    "tc_extended_club_records_history_dt",
    "news",
    "extended_comp_records_dt",
)

CALENDAR_FIXTURE_COUNT = 6
# Positions in the calendar, which is sorted by date.
FIRST_MATCH = 0
SECOND_LEAGUE_MATCH = 1
FIRST_LEAGUE_MATCH = 2
AWAY_LEAGUE_MATCH = 3
UNPLAYED_CUP_TIE = 4
# The days of the year those matches are played on, and the dates they decode to.
FIRST_MATCH_DAY = 37
LEAGUE_MATCH_DAY = 51
AWAY_MATCH_DAY = 58
CUP_TIE_DAY = 65
# A day inside the calendar's range that no match is played on.
EMPTY_DAY = 45
CALENDAR_FIRST_DATE = date(2031, 2, 6)
CALENDAR_LAST_DATE = date(2031, 3, 13)
LEAGUE_MATCH_DATE = date(2031, 2, 20)

HOME_GOALS = 2
AWAY_GOALS = 1
# Counts that put one gate, and only that gate, on the wrong side of its own bound.
RECORDS_AT_THE_FLOOR = 100
JOINING_HALF = 50
UNPLAYED_ABOVE_THE_CEILING = 2


def write_career(tmp_path: Path, **fragment_arguments: object) -> Path:
    return career_fragment(**fragment_arguments).write(  # pyright: ignore[reportArgumentType]
        tmp_path / "Private Folder" / FILE_NAME
    )


def fixtures_of(career_path: Path) -> tuple[Fixture, ...]:
    with fmsave.open(career_path) as career_save:
        return tuple(career_save.fixtures())


def anomalies_of(career_path: Path) -> dict[str, int]:
    with fmsave.open(career_path) as career_save:
        career_save.fixtures()
        reader_check = career_save._reader_check("fixtures")  # pyright: ignore[reportPrivateUsage]
    assert reader_check is not None
    return dict(reader_check.anomalies)


def league_result(**overrides: int) -> ExampleResult:
    """A record for the played league match, with any field overridden."""
    fields: dict[str, int] = {
        "stage_id": FIXTURE_STAGE_ID,
        "home_team_id": NORTHBRIDGE_TEAM_A,
        "away_team_id": SOUTHPORT_TEAM,
        "day_of_year": LEAGUE_MATCH_DAY,
        "home_goals": HOME_GOALS,
        "away_goals": AWAY_GOALS,
    }
    fields.update(overrides)
    return ExampleResult(**fields)


def raw_result(
    day_of_year: int,
    home_team_id: int,
    away_team_id: int,
    home_goals: int,
    away_goals: int,
    *,
    stage_id: int = FIXTURE_STAGE_ID,
    year: int = FIXTURE_KICK_OFF_YEAR,
    r22: int = RESULT_R22,
) -> RawStageResult:
    return RawStageResult(
        date=date(year, 1, 1) + timedelta(days=day_of_year - 1),
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_goals=home_goals,
        away_goals=away_goals,
        r22=r22,
    )


def repeated(example: ExampleResult, count: int) -> tuple[ExampleResult, ...]:
    """The same record written `count` times over, as a save stores each match several times."""
    return tuple(example for _ in range(count))


# A record joining the played league match, one inside the calendar's dates that joins nothing,
# and one naming the cup tie the calendar has not played.
JOINING_RESULT = league_result()
UNJOINED_RESULT = league_result(day_of_year=EMPTY_DAY)
UNPLAYED_RESULT = league_result(
    day_of_year=CUP_TIE_DAY, away_team_id=ATHLETIC_TEAM_A, stage_id=CUP_FIXTURE_STAGE_ID
)


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_result_stats(**overrides: int) -> ResultStats:
    """Counts with every rate comfortably inside its bound."""
    fields: dict[str, int] = {
        "candidates": 600_000,
        "accepted": 190_000,
        "joined": 184_000,
        "unjoined": 6_000,
        "ambiguous": 0,
        "score_for_unplayed": 2,
        "score_disagreements": 0,
        "played_fixtures": 96_000,
        "scored_fixtures": 22_000,
    }
    fields.update(overrides)
    return ResultStats(**fields)


# Reading a score


def test_a_result_fills_its_match_score_and_the_word_beside_it(tmp_path: Path) -> None:
    career_path = write_career(tmp_path, span_results=(JOINING_RESULT,))

    fixtures = fixtures_of(career_path)

    assert len(fixtures) == CALENDAR_FIXTURE_COUNT
    scored = fixtures[FIRST_LEAGUE_MATCH]
    assert scored.date == LEAGUE_MATCH_DATE
    assert scored.home_goals == HOME_GOALS
    assert scored.away_goals == AWAY_GOALS
    assert scored.unknown["result_r22"] == RESULT_R22


def test_every_other_match_keeps_no_score_and_the_played_mark_it_had(tmp_path: Path) -> None:
    """A score reaches one match, and nothing else about the calendar moves."""
    career_path = write_career(tmp_path, span_results=(JOINING_RESULT,))
    unscored_calendar = fixtures_of(write_career(tmp_path / "plain"))

    fixtures = fixtures_of(career_path)

    for position, fixture in enumerate(fixtures):
        assert fixture.played == unscored_calendar[position].played, position
        if position == FIRST_LEAGUE_MATCH:
            continue
        assert fixture.home_goals is None, position
        assert fixture.away_goals is None, position


def test_a_result_in_a_named_section_is_read_and_one_in_the_game_database_is_not(
    tmp_path: Path,
) -> None:
    """The regions are the ones the layout names, so a score elsewhere must never be read.

    A whole-file scan would find the record written into the game database, which is what this
    reader is scoped to rule out.
    """
    career_path = write_career(
        tmp_path,
        news_results=(
            league_result(
                day_of_year=AWAY_MATCH_DAY,
                home_team_id=SOUTHPORT_TEAM,
                away_team_id=NORTHBRIDGE_TEAM_A,
                home_goals=3,
                away_goals=0,
            ),
        ),
        game_db_results=(league_result(day_of_year=FIRST_MATCH_DAY, home_goals=4, away_goals=4),),
    )

    fixtures = fixtures_of(career_path)

    assert fixtures[AWAY_LEAGUE_MATCH].home_goals == 3
    assert fixtures[AWAY_LEAGUE_MATCH].away_goals == 0
    assert fixtures[FIRST_MATCH].home_goals is None
    assert fixtures[FIRST_MATCH].away_goals is None


def test_the_regions_scanned_are_the_named_sections_and_never_the_game_database() -> None:
    layout = find_result_layout("")

    assert layout.regions == DECLARED_REGIONS
    assert GAME_DB_SECTION not in layout.regions


def test_a_save_without_the_named_sections_is_read_without_error(career_save_path: Path) -> None:
    """No save need carry every section, so an absent one is skipped rather than raised on."""
    fixtures = fixtures_of(career_save_path)

    assert len(fixtures) == CALENDAR_FIXTURE_COUNT
    assert all(fixture.home_goals is None for fixture in fixtures)


# Records that must not score anything


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"sentinel": 2}, id="a-sentinel-that-is-not-one"),
        pytest.param({"lead_byte": 2}, id="a-decoy-lead-byte"),
        pytest.param({"zero_byte": 1}, id="a-byte-the-locator-needs-zero"),
        pytest.param({"home_goals": 41}, id="more-goals-than-a-match-can-hold"),
        pytest.param({"stage_id": UNRESOLVED_FIXTURE_STAGE_ID}, id="a-stage-the-table-has-not"),
        pytest.param({"year": FIXTURE_KICK_OFF_YEAR + 2}, id="a-date-the-calendar-never-covers"),
    ],
)
def test_a_record_the_reader_does_not_accept_scores_nothing(
    tmp_path: Path, overrides: dict[str, int]
) -> None:
    career_path = write_career(tmp_path, span_results=(league_result(**overrides),))

    fixtures = fixtures_of(career_path)

    assert fixtures[FIRST_LEAGUE_MATCH].home_goals is None
    assert fixtures[FIRST_LEAGUE_MATCH].away_goals is None


def test_a_result_naming_no_match_is_counted_and_changes_nothing(career_save_path: Path) -> None:
    calendar = fixtures_of(career_save_path)

    scored, stats = apply_results(
        calendar,
        [raw_result(EMPTY_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 1, 0)],
        candidates=1,
    )

    assert stats.accepted == 1
    assert stats.joined == 0
    assert stats.unjoined == 1
    assert stats.scored_fixtures == 0
    assert scored == calendar


def test_a_result_naming_two_matches_at_once_fills_neither(tmp_path: Path) -> None:
    """A guessed attribution is a guessed value, so an ambiguous key scores nothing."""
    duplicated_match = MAIN_CLUSTER_FIXTURES[5]
    career_path = write_career(
        tmp_path,
        extra_fixtures=(duplicated_match,),
        span_results=(league_result(day_of_year=FIRST_MATCH_DAY),),
    )

    fixtures = fixtures_of(career_path)

    on_that_day = [fixture for fixture in fixtures if fixture.date == CALENDAR_FIRST_DATE]
    assert len(on_that_day) == 2
    assert all(fixture.home_goals is None for fixture in on_that_day)
    assert all(fixture.away_goals is None for fixture in on_that_day)
    assert anomalies_of(career_path)["ambiguous_results"] == 1


def test_a_result_for_an_unplayed_match_leaves_it_unscored(career_save_path: Path) -> None:
    calendar = fixtures_of(career_save_path)
    assert calendar[UNPLAYED_CUP_TIE].played is False

    scored, stats = apply_results(
        calendar,
        [
            raw_result(
                CUP_TIE_DAY,
                NORTHBRIDGE_TEAM_A,
                ATHLETIC_TEAM_A,
                1,
                0,
                stage_id=CUP_FIXTURE_STAGE_ID,
            )
        ],
        candidates=1,
    )

    assert stats.joined == 1
    assert stats.score_for_unplayed == 1
    assert stats.scored_fixtures == 0
    assert scored[UNPLAYED_CUP_TIE].home_goals is None
    assert scored[UNPLAYED_CUP_TIE].played is False


# The same match stored several times


def test_a_second_copy_carrying_the_same_score_is_ordinary(career_save_path: Path) -> None:
    """A save stores each match about 1.8 times, so a repeat is normal and not an anomaly."""
    calendar = fixtures_of(career_save_path)
    one_copy = raw_result(LEAGUE_MATCH_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 2, 1)

    scored, stats = apply_results(calendar, [one_copy, one_copy, one_copy], candidates=3)

    assert stats.joined == 3
    assert stats.score_disagreements == 0
    assert stats.scored_fixtures == 1
    assert scored[FIRST_LEAGUE_MATCH].home_goals == 2
    assert scored[FIRST_LEAGUE_MATCH].away_goals == 1


def test_two_copies_disagreeing_on_the_score_leave_the_match_unscored(
    career_save_path: Path,
) -> None:
    """Arrival order must not settle a contradiction, and no later copy may revive it."""
    calendar = fixtures_of(career_save_path)
    first_copy = raw_result(LEAGUE_MATCH_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 2, 1)
    disagreeing_copy = raw_result(LEAGUE_MATCH_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 3, 1)

    scored, stats = apply_results(
        calendar, [first_copy, disagreeing_copy, first_copy], candidates=3
    )

    assert stats.score_disagreements == 1
    assert stats.scored_fixtures == 0
    assert scored[FIRST_LEAGUE_MATCH].home_goals is None
    assert scored[FIRST_LEAGUE_MATCH].away_goals is None


# The window and the shared scope rule


def test_the_window_is_the_calendars_own_first_and_last_date(career_save_path: Path) -> None:
    calendar = fixtures_of(career_save_path)

    assert calendar_dates(calendar) == (CALENDAR_FIRST_DATE, CALENDAR_LAST_DATE)
    assert calendar_dates(()) is None


def test_one_scope_rule_judges_the_span_and_the_sections_alike() -> None:
    """Both routes are judged by this one predicate, so neither can drift from the other."""
    in_range = raw_result(LEAGUE_MATCH_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 2, 1)
    stage_ids = {FIXTURE_STAGE_ID}

    assert result_in_scope(in_range, stage_ids, CALENDAR_FIRST_DATE, CALENDAR_LAST_DATE)
    assert not result_in_scope(in_range, set(), CALENDAR_FIRST_DATE, CALENDAR_LAST_DATE)
    before_the_calendar = raw_result(
        LEAGUE_MATCH_DAY, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 2, 1, year=FIXTURE_KICK_OFF_YEAR - 1
    )
    assert not result_in_scope(
        before_the_calendar, stage_ids, CALENDAR_FIRST_DATE, CALENDAR_LAST_DATE
    )


# Checks


def test_healthy_result_counts_pass_every_gate_and_a_small_span_applies_none() -> None:
    results = evaluate_results(healthy_result_stats(), BOUNDS, FULL_SIZE_SPAN_BYTES)
    assert tuple(result.name for result in results) == RESULT_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("fixtures", results)

    small_results = evaluate_results(healthy_result_stats(), BOUNDS, SMALL_SPAN_BYTES)
    assert all(not result.applied and result.passed for result in small_results)


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(
            healthy_result_stats(accepted=100, joined=100, unjoined=0, score_for_unplayed=0),
            [],
            id="at-the-record-floor",
        ),
        pytest.param(
            healthy_result_stats(accepted=99, joined=99, unjoined=0, score_for_unplayed=0),
            ["result_records_minimum"],
            id="below-the-record-floor",
        ),
        pytest.param(
            healthy_result_stats(accepted=1_000, joined=900, unjoined=100, score_for_unplayed=0),
            [],
            id="at-the-join-floor",
        ),
        pytest.param(
            healthy_result_stats(accepted=1_000, joined=850, unjoined=150, score_for_unplayed=0),
            ["results_joined"],
            id="below-the-join-floor",
        ),
        pytest.param(
            healthy_result_stats(accepted=1_000, joined=1_000, unjoined=0, score_for_unplayed=10),
            [],
            id="at-the-unplayed-ceiling",
        ),
        pytest.param(
            healthy_result_stats(accepted=1_000, joined=1_000, unjoined=0, score_for_unplayed=20),
            ["results_for_unplayed"],
            id="above-the-unplayed-ceiling",
        ),
        pytest.param(
            ResultStats(0, 0, 0, 0, 0, 0, 0, 0, 0),
            list(RESULT_GATE_NAMES),
            id="a-pass-that-found-nothing",
        ),
    ],
)
def test_result_gates_fail_one_at_a_time(stats: ResultStats, expected_failures: list[str]) -> None:
    """A pass that accepted nothing fails every gate rather than passing for want of a rate."""
    results = evaluate_results(stats, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == expected_failures
    if not expected_failures:
        enforce("fixtures", results)
        return
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("fixtures", results)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


def bounds_that_judge_only_the_results() -> GateBounds:
    """The registered result bounds, applied to a small span, with the calendar's own relaxed.

    Only the span's size threshold and the calendar's gates are moved. The three result bounds
    are exactly the ones that ship, so what fails below is a shipped bound meeting real counts.
    """
    return dataclasses.replace(
        BOUNDS,
        span_minimum_applies_from_bytes=0,
        fixtures_minimum=(0, None),
        fixture_cluster_share=(0.0, None),
        fixture_strays_minimum=(0, None),
        fixture_stage_resolved=(0.0, None),
        fixture_teams_resolved=(0.0, None),
    )


def with_result_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fmsave.Save, "_gate_bounds", lambda career_save: bounds_that_judge_only_the_results()
    )


@pytest.mark.parametrize(
    ("span_results", "failing_gate"),
    [
        pytest.param(
            (JOINING_RESULT,),
            "result_records_minimum",
            id="too-few-records-accepted",
        ),
        pytest.param(
            repeated(JOINING_RESULT, JOINING_HALF) + repeated(UNJOINED_RESULT, JOINING_HALF),
            "results_joined",
            id="too-few-of-them-join-a-match",
        ),
        pytest.param(
            repeated(JOINING_RESULT, RECORDS_AT_THE_FLOOR - UNPLAYED_ABOVE_THE_CEILING)
            + repeated(UNPLAYED_RESULT, UNPLAYED_ABOVE_THE_CEILING),
            "results_for_unplayed",
            id="scores-reach-matches-not-yet-played",
        ),
    ],
)
def test_each_result_gate_stops_the_reader_when_its_count_passes_its_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    span_results: Sequence[ExampleResult],
    failing_gate: str,
) -> None:
    """Every one of the three gates has to be able to fail on real counts and stop the reader.

    Each case drives one gate's own input past the bound that ships, leaving the other two
    comfortably inside theirs, so a gate that could never fire is caught here.
    """
    career_path = write_career(tmp_path, span_results=tuple(span_results))
    with_result_bounds(monkeypatch)

    with (
        fmsave.open(career_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.fixtures()

    message = str(error_info.value)
    assert failing_gate in message
    for other_gate in set(RESULT_GATE_NAMES) - {failing_gate}:
        assert other_gate not in message


def test_the_same_bounds_let_sound_counts_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the proof: these bounds pass when the counts are sound.

    Without this, the three failures above would be as consistent with a gate that can never
    pass as with one that works.
    """
    career_path = write_career(
        tmp_path, span_results=repeated(JOINING_RESULT, RECORDS_AT_THE_FLOOR)
    )
    with_result_bounds(monkeypatch)

    with fmsave.open(career_path) as career_save:
        fixtures = career_save.fixtures()

    assert fixtures[FIRST_LEAGUE_MATCH].home_goals == HOME_GOALS
    assert fixtures[FIRST_LEAGUE_MATCH].away_goals == AWAY_GOALS


def test_the_anomalies_report_what_the_join_left_behind(tmp_path: Path) -> None:
    career_path = write_career(
        tmp_path, span_results=(JOINING_RESULT, UNJOINED_RESULT, UNJOINED_RESULT)
    )

    anomalies = anomalies_of(career_path)

    assert anomalies["unjoined_results"] == 2
    assert anomalies["ambiguous_results"] == 0
    assert anomalies["score_disagreements"] == 0
    assert anomalies["scored_fixtures"] == 1
