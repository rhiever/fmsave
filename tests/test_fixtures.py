from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Sequence
from datetime import date, time
from pathlib import Path

import pytest

import fmsave
from fmsave import Table
from fmsave._layouts import (
    FULL_SAVE_MINIMUM_SPAN_BYTES,
    FixtureCalendarLayout,
    GateBounds,
    find_layout,
)
from fmsave._reader_stats import FixtureStats, ResultStats
from fmsave._save import FIXTURES_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.checks import GateResult, check_fixtures, enforce, evaluate_fixtures
from fmsave.export import column_names, record_to_dict
from fmsave.models.competitions import CompetitionRound
from fmsave.models.fixtures import Fixture
from fmsave.readers._common import GAME_DB_SECTION, SPAN_REGION
from fmsave.readers.fixtures import kick_off_time_of, largest_cluster
from fmsave.readers.span import RawFixture
from tests.fixtures.career import (
    ATHLETIC_UID,
    CUP_FIXTURE_STAGE_ID,
    DUPLICATE_STRAY_FIXTURE,
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    FIXTURE_DATE2,
    FIXTURE_LEG,
    FIXTURE_MATCH_RULES_TEMPLATE,
    FIXTURE_PHASE,
    FIXTURE_R39_42,
    FIXTURE_R47_54,
    FIXTURE_SEASON_START_YEAR,
    NEUTRAL_VENUE_MINIMUM_FIXTURES,
    NORTHBRIDGE_UID,
    PAST_MIDNIGHT_FIXTURE,
    SECOND_COMPETITION_ID,
    SOUTHPORT_UID,
    STRAY_FIXTURE_STAGE_ID,
    UNREGISTERED_FIXTURE_TEAM_ID,
    UNRESOLVED_FIXTURE_STAGE_ID,
    UNRESOLVED_TEAM_FIXTURE,
    ExampleFixture,
    career_fragment,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

FILE_NAME = "career example.fm"
MEBIBYTE = 1024 * 1024
FULL_SIZE_SPAN_BYTES = 120 * MEBIBYTE
SMALL_SPAN_BYTES = 1 * MEBIBYTE
FIXTURE_GATE_NAMES = (
    "fixtures_minimum",
    "fixture_cluster_share",
    "fixture_strays_minimum",
    "fixture_stage_resolved",
    "fixture_teams_resolved",
    "fixture_stadiums_resolved",
)
FIXTURE_LAYOUT: FixtureCalendarLayout = find_layout(
    FixtureCalendarLayout, SPAN_REGION, None, ""
).layout
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, 4000, "").layout

CALENDAR_FIXTURE_COUNT = 6
STRAY_FIXTURE_COUNT = 2
# Four of the six calendar records are marked played; the cup tie and the unresolved-stage
# match are not.
PLAYED_FIXTURE_COUNT = 4
# The calendar in the order the reader must return it: the six records sorted by date.
EXPECTED_DATES = (
    date(2031, 2, 6),
    date(2031, 2, 13),
    date(2031, 2, 20),
    date(2031, 2, 27),
    date(2031, 3, 6),
    date(2031, 3, 13),
)
LEAGUE_KICK_OFF = time(14, 15)
CUP_KICK_OFF = time(16, 0)
# Positions in the sorted calendar.
FIRST_LEAGUE_MATCH = 2
AWAY_LEAGUE_MATCH = 3
NEUTRAL_CUP_TIE = 4
UNRESOLVED_STAGE_MATCH = 5
NORTHBRIDGE_HOME_MATCHES = 5
LEAGUE_MATCH_COUNT = 4
# With the extra records that pin the neutral-venue minimum: Example Athletic plays exactly
# the minimum at home and Southport one short of it, so both clubs sit on the boundary.
ATHLETIC_HOME_MATCHES = 4
SOUTHPORT_HOME_MATCHES = 3
NEUTRAL_VENUE_VOTES_ON_THE_BOUNDARY = 2
EXPECTED_COLUMNS = (
    "stage_id",
    "competition_id",
    "competition_name",
    "round",
    "round_code",
    "round_index",
    "date",
    "kick_off_time",
    "season_start_year",
    "home_team_id",
    "home_club_uid",
    "home_club_name",
    "home_club_short_name",
    "home_team_slot",
    "away_team_id",
    "away_club_uid",
    "away_club_name",
    "away_club_short_name",
    "away_team_slot",
    "home_goals",
    "away_goals",
    "played",
    "is_neutral_venue",
    "stadium_uid",
    "match_record_id",
    "match_rules_template",
    "unknown_date2",
    "unknown_phase",
    "unknown_leg",
    "unknown_r39_42",
    "unknown_r47_54",
    "unknown_result_r22",
)


def write_career(tmp_path: Path, extra_fixtures: Sequence[ExampleFixture] = ()) -> Path:
    return career_fragment(extra_fixtures=extra_fixtures).write(
        tmp_path / "Private Folder" / FILE_NAME
    )


def built_from(career_save: fmsave.Save) -> tuple[tuple[Fixture, ...], FixtureStats]:
    """The calendar and its counts, built straight from the save's own shared indexes."""
    from fmsave.readers.fixtures import build_fixtures

    context = career_save._context
    with context.section(GAME_DB_SECTION):
        club_index = context.club_index()
        stage_index = context.stage_index()
        competition_index = context.competition_index()
        stadium_index = context.stadium_index()
    return build_fixtures(
        context.span_records(),
        stage_index,
        competition_index,
        club_index,
        stadium_index,
        FIXTURE_LAYOUT,
    )


def raw_fixture_at(span_offset: int) -> RawFixture:
    """A record whose only field this test cares about is where it sits in the span."""
    return RawFixture(
        span_offset=span_offset,
        stage_id=1,
        stadium_ordinal=0,
        home_team_id=1,
        away_team_id=2,
        packed_kick_off=0,
        kick_off_year=2031,
        season_start_year=2030,
        match_record_id=None,
        round_index=0,
        played=False,
        date2=0,
        phase=0,
        leg=0,
        r39_42=0,
        match_rules_template=(0, 0, 0),
        r47_54=0,
    )


def healthy_fixture_stats() -> FixtureStats:
    """Counts with every rate comfortably inside its bound."""
    return FixtureStats(
        span_records=106_600,
        cluster_records=105_546,
        clusters=18,
        strays_without_a_copy=150,
        with_stage=105_000,
        stage_resolved=104_800,
        home_team_resolved=105_400,
        away_team_resolved=105_400,
        undated=0,
        bad_kick_off_slots=0,
        neutral_venue_votes=600,
        with_stadium=104_331,
        stadium_resolved=104_265,
    )


def consistent_stats(cluster_records: int) -> FixtureStats:
    """Counts that stay internally consistent at any size, so only the floor can fail."""
    return FixtureStats(
        span_records=cluster_records + 200,
        cluster_records=cluster_records,
        clusters=2,
        strays_without_a_copy=150,
        with_stage=cluster_records,
        stage_resolved=cluster_records,
        home_team_resolved=cluster_records,
        away_team_resolved=cluster_records,
        undated=0,
        bad_kick_off_slots=0,
        neutral_venue_votes=10,
        with_stadium=cluster_records,
        stadium_resolved=cluster_records,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


# This save carries no result record, so every result count is zero and only the calendar's own
# counts are under test here. The result gates are judged in tests/test_results.py.
NO_RESULT_STATS = ResultStats(
    candidates=0,
    accepted=0,
    joined=0,
    unjoined=0,
    ambiguous=0,
    score_for_unplayed=0,
    score_disagreements=0,
    played_fixtures=PLAYED_FIXTURE_COUNT,
    scored_fixtures=0,
)


def with_gate_bounds(monkeypatch: pytest.MonkeyPatch, bounds: GateBounds) -> None:
    """Judge the next save's readers against these bounds instead of the registered ones."""
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: bounds)


# Stadium bounds this fragment's own table meets. Lowering the game database threshold turns
# on every check that judges it, the stadium table's among them, and that table is 101 rows
# where a full save holds tens of thousands. Relaxing the two floors it cannot reach keeps a
# check this file is not about from raising first.
FRAGMENT_STADIUM_BOUNDS = {
    "stadium_rows_minimum": (1, None),
    "stadium_owners_resolved": (0.5, None),
}

# Bounds the example save cannot meet: its stage table names three competitions, not a
# thousand. The span threshold is left alone, so the fixture gates stay out of the way and a
# raise can only have come from the competition checks.
UNMEETABLE_COMPETITION_BOUNDS = dataclasses.replace(
    BOUNDS,
    minimum_applies_from_bytes=0,
    competitions_minimum=(1_000, None),
    **FRAGMENT_STADIUM_BOUNDS,
)


def test_only_the_largest_run_of_records_becomes_the_calendar(career_save_path: Path) -> None:
    """The stray run is a copy of the calendar, not career data, and must never be returned.

    Every real save carries a fixed block of template records dated years off the clock, with
    the same count on each one; keeping it would put those same phantom matches on every
    career. The strays here are dated before the whole calendar, so a reader that keeps them
    lists them first rather than quietly at the end.
    """
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    assert len(fixtures_table) == CALENDAR_FIXTURE_COUNT
    assert stats.clusters == 2
    assert stats.span_records == CALENDAR_FIXTURE_COUNT + STRAY_FIXTURE_COUNT
    assert stats.cluster_records == CALENDAR_FIXTURE_COUNT
    assert STRAY_FIXTURE_STAGE_ID not in {fixture.stage_id for fixture in fixtures_table}
    # This save carries no result record at all, so no match has a score, played or not.
    assert all(
        fixture.home_goals is None and fixture.away_goals is None for fixture in fixtures_table
    )


def test_two_runs_of_the_same_length_keep_the_earlier_one() -> None:
    """Which run wins may never rest on the order the span happened to hold them in."""
    gap = FIXTURE_LAYOUT.cluster_gap_bytes
    records = [
        raw_fixture_at(0),
        raw_fixture_at(100),
        raw_fixture_at(100 + 2 * gap),
        raw_fixture_at(200 + 2 * gap),
    ]

    kept = largest_cluster(records, gap)

    assert [record.span_offset for record in kept] == [0, 100]
    assert largest_cluster([], gap) == ()


def test_the_calendar_is_sorted_by_date_then_kick_off_then_teams(career_save_path: Path) -> None:
    """File order is neither sorted nor a rotation of a sorted order, so the reader sorts."""
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()

    assert tuple(fixture.date for fixture in fixtures_table) == EXPECTED_DATES
    assert fixtures_table[FIRST_LEAGUE_MATCH].kick_off_time == LEAGUE_KICK_OFF
    assert fixtures_table[NEUTRAL_CUP_TIE].kick_off_time == CUP_KICK_OFF


@pytest.mark.parametrize(
    ("time_slot", "expected_time"),
    [
        pytest.param(34, time(14, 15), id="an-afternoon-league-slot"),
        pytest.param(41, time(16, 0), id="an-evening-cup-slot"),
        pytest.param(0, time(5, 45), id="the-earliest-slot"),
        pytest.param(73, None, id="a-slot-that-reaches-a-whole-day"),
    ],
)
def test_kick_off_time_of_converts_the_slot(time_slot: int, expected_time: time | None) -> None:
    """A slot is counted in quarter hours from a fixed offset; one that reaches a day is no time."""
    packed_kick_off = 51 | time_slot << 9

    assert kick_off_time_of(packed_kick_off, FIXTURE_LAYOUT) == expected_time


def test_a_slot_past_midnight_leaves_no_time_and_is_counted(tmp_path: Path) -> None:
    career_path = write_career(tmp_path, (PAST_MIDNIGHT_FIXTURE,))

    with fmsave.open(career_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    assert len(fixtures_table) == CALENDAR_FIXTURE_COUNT + 1
    assert fixtures_table[-1].kick_off_time is None
    assert fixtures_table[-1].date == date(2031, 3, 27)
    assert stats.bad_kick_off_slots == 1


def test_an_unplayed_cup_tie_has_no_round_index_and_no_match_record(
    career_save_path: Path,
) -> None:
    """The no-round value is read as no round, and an unplayed match keeps no match record."""
    with fmsave.open(career_save_path) as career_save:
        cup_tie = career_save.fixtures()[NEUTRAL_CUP_TIE]

    assert cup_tie.stage_id == CUP_FIXTURE_STAGE_ID
    assert cup_tie.round_index is None
    assert cup_tie.played is False
    assert cup_tie.match_record_id is None
    assert cup_tie.competition_id == SECOND_COMPETITION_ID
    unnamed_round = cup_tie.round
    assert unnamed_round is not None
    assert unnamed_round.label is CompetitionRound.UNKNOWN


def test_an_unresolved_stage_leaves_the_competition_fields_empty(career_save_path: Path) -> None:
    """A stage the table does not hold names no competition, and is never guessed at."""
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    unresolved = fixtures_table[UNRESOLVED_STAGE_MATCH]
    assert unresolved.stage_id == UNRESOLVED_FIXTURE_STAGE_ID
    assert unresolved.competition_id is None
    assert unresolved.competition_name is None
    assert unresolved.round is None
    assert stats.with_stage == CALENDAR_FIXTURE_COUNT
    assert stats.stage_resolved == CALENDAR_FIXTURE_COUNT - 1


def test_teams_join_to_their_club_name_and_slot(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()

    home_match = fixtures_table[FIRST_LEAGUE_MATCH]
    assert home_match.home_club_uid == NORTHBRIDGE_UID
    assert home_match.home_club_name == "Northbridge FC"
    assert home_match.home_club_short_name == "Northbridge"
    assert home_match.home_team_slot == 0
    assert home_match.away_club_uid == SOUTHPORT_UID
    assert home_match.away_team_slot == 0
    # A club's later team slots keep their position in its own team list.
    third_team_match = fixtures_table[1]
    assert third_team_match.away_club_uid == ATHLETIC_UID
    assert third_team_match.away_team_slot == 2


def test_an_unresolved_team_leaves_the_club_fields_empty_and_is_counted(tmp_path: Path) -> None:
    career_path = write_career(tmp_path, (UNRESOLVED_TEAM_FIXTURE,))

    with fmsave.open(career_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    unresolved = fixtures_table[-1]
    assert unresolved.home_team_id == UNREGISTERED_FIXTURE_TEAM_ID
    assert unresolved.home_club_uid is None
    assert unresolved.home_club_name is None
    assert unresolved.home_club_short_name is None
    assert unresolved.home_team_slot is None
    assert stats.home_team_resolved == CALENDAR_FIXTURE_COUNT
    assert stats.away_team_resolved == CALENDAR_FIXTURE_COUNT + 1


def test_a_competition_is_named_only_through_a_supplied_map(career_save_path: Path) -> None:
    """No save stores a competition name, so a name arrives through the database id or not at all."""
    with fmsave.open(career_save_path) as unnamed_save:
        without_map = [fixture.competition_name for fixture in unnamed_save.fixtures()]
    with fmsave.open(
        career_save_path, competition_names={FIRST_COMPETITION_DATABASE_ID: "Example League"}
    ) as named_save:
        with_map = [fixture.competition_name for fixture in named_save.fixtures()]

    assert without_map == [None] * CALENDAR_FIXTURE_COUNT
    assert with_map == ["Example League"] * LEAGUE_MATCH_COUNT + [None, None]


def test_the_neutral_venue_vote_marks_the_odd_ground_out(career_save_path: Path) -> None:
    """A club's usual ground is the one it used most at home that season, and stays private.

    A club with too few home matches in a season has no usual ground, so none of its matches is
    called neutral rather than one of two being guessed at.
    """
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    assert fixtures_table[NEUTRAL_CUP_TIE].is_neutral_venue is True
    for position in (0, 1, FIRST_LEAGUE_MATCH, UNRESOLVED_STAGE_MATCH):
        assert fixtures_table[position].is_neutral_venue is False, position
    assert fixtures_table[AWAY_LEAGUE_MATCH].is_neutral_venue is None
    assert stats.neutral_venue_votes == 1
    # The ordinal the vote runs on is private: it reaches no public field.
    assert "stadium" not in set(column_names(Fixture))


def test_the_neutral_venue_vote_needs_the_layouts_minimum_home_fixtures(tmp_path: Path) -> None:
    """The minimum is pinned from both sides by two clubs sitting either side of it.

    Example Athletic plays it exactly and gets a usual ground; Southport plays one short and
    gets none. Raising the minimum by one takes Athletic's vote away and lowering it by one
    gives Southport one, so the vote count moves whichever way the constant moves.
    """
    career_path = write_career(tmp_path, NEUTRAL_VENUE_MINIMUM_FIXTURES)

    with fmsave.open(career_path) as career_save:
        fixtures_table = career_save.fixtures()
        _built, stats = built_from(career_save)

    athletic_at_home = fixtures_table.filter(lambda fixture: fixture.home_club_uid == ATHLETIC_UID)
    assert len(athletic_at_home) == ATHLETIC_HOME_MATCHES
    # Its last home match of the season was played away from the ground it used for the rest.
    assert [fixture.is_neutral_venue for fixture in athletic_at_home] == [False, False, False, True]
    southport_at_home = fixtures_table.filter(
        lambda fixture: fixture.home_club_uid == SOUTHPORT_UID
    )
    assert len(southport_at_home) == SOUTHPORT_HOME_MATCHES
    assert all(fixture.is_neutral_venue is None for fixture in southport_at_home)
    assert stats.neutral_venue_votes == NEUTRAL_VENUE_VOTES_ON_THE_BOUNDARY


def test_a_stray_that_repeats_a_kept_match_is_not_counted_as_a_loss(tmp_path: Path) -> None:
    """Dropping a copy of a match the calendar already lists costs nothing, and the count says so."""
    career_path = career_fragment(extra_strays=(DUPLICATE_STRAY_FIXTURE,)).write(
        tmp_path / "Private Folder" / FILE_NAME
    )

    with fmsave.open(career_path) as career_save:
        _fixtures, stats = built_from(career_save)

    assert stats.span_records == CALENDAR_FIXTURE_COUNT + STRAY_FIXTURE_COUNT + 1
    assert stats.cluster_records == CALENDAR_FIXTURE_COUNT
    # Three records were dropped; one repeats the calendar's first match, so two are a loss.
    assert stats.strays_without_a_copy == STRAY_FIXTURE_COUNT


def test_a_failed_competition_check_stops_a_name_reaching_the_calendar(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name may only come from a competition table whose own checks passed.

    A build that mis-paired entity ids with database ids would otherwise put another
    competition's name on every one of a hundred thousand rows and raise nothing at all.
    """
    with_gate_bounds(monkeypatch, UNMEETABLE_COMPETITION_BOUNDS)

    with (
        fmsave.open(
            career_save_path,
            strict=True,
            competition_names={FIRST_COMPETITION_DATABASE_ID: "Example League"},
        ) as named_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        named_save.fixtures()

    assert "competitions_minimum" in str(error_info.value)


def test_a_calendar_with_no_name_map_never_runs_the_competition_checks(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a map every name is None anyway, so nothing is read or judged on its account."""
    with_gate_bounds(monkeypatch, UNMEETABLE_COMPETITION_BOUNDS)

    with fmsave.open(career_save_path) as unnamed_save:
        fixtures_table = unnamed_save.fixtures()

    assert len(fixtures_table) == CALENDAR_FIXTURE_COUNT
    assert all(fixture.competition_name is None for fixture in fixtures_table)


def test_the_unknown_words_carry_the_undecoded_fields(career_save_path: Path) -> None:
    """The bytes with no known meaning ship as they are; the score word needs a result record."""
    with fmsave.open(career_save_path) as career_save:
        league_match = career_save.fixtures()[FIRST_LEAGUE_MATCH]

    assert dict(league_match.unknown) == {
        "date2": FIXTURE_DATE2,
        "phase": FIXTURE_PHASE,
        "leg": FIXTURE_LEG,
        "r39_42": FIXTURE_R39_42,
        "r47_54": FIXTURE_R47_54,
    }
    assert league_match.match_rules_template == FIXTURE_MATCH_RULES_TEMPLATE
    assert league_match.season_start_year == FIXTURE_SEASON_START_YEAR
    # The result word is declared, and stays empty on a save carrying no result record.
    assert Fixture.UNKNOWN_KEYS[-1] == "result_r22"
    assert record_to_dict(league_match, json_ready=True)["unknown"] == {
        "date2": FIXTURE_DATE2,
        "phase": FIXTURE_PHASE,
        "leg": FIXTURE_LEG,
        "r39_42": FIXTURE_R39_42,
        "r47_54": FIXTURE_R47_54,
        "result_r22": None,
    }


def test_export_columns_flatten_the_round_and_the_unknown_words(career_save_path: Path) -> None:
    assert column_names(Fixture) == EXPECTED_COLUMNS

    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()

    assert_matches_json_normalize(list(fixtures_table), Fixture)
    columns = fixtures_table.to_columns()
    assert columns["round"][FIRST_LEAGUE_MATCH] == "final"
    assert columns["round_code"][FIRST_LEAGUE_MATCH] == 19
    assert columns["round"][UNRESOLVED_STAGE_MATCH] is None
    assert columns["kick_off_time"][FIRST_LEAGUE_MATCH] == LEAGUE_KICK_OFF


def test_records_survive_pickle_and_deepcopy(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()

    for example in (fixtures_table[0], fixtures_table):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_fixtures_returns_one_cached_table_and_raises_after_close(career_save_path: Path) -> None:
    career_save = fmsave.open(career_save_path)
    fixtures_table = career_save.fixtures()

    assert isinstance(fixtures_table, Table)
    assert fixtures_table.record_type is Fixture
    assert career_save.fixtures() is fixtures_table
    assert FIXTURES_TABLE_CACHE_KEY == "table:fixtures"

    rows_before_close = list(fixtures_table)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.fixtures()
    assert list(fixtures_table) == rows_before_close


def test_table_queries_scope_the_calendar(career_save_path: Path) -> None:
    """A club's own view and a competition's own view are queries, not fields of their own."""
    with fmsave.open(career_save_path) as career_save:
        fixtures_table = career_save.fixtures()

    assert len(fixtures_table.where(competition_id=FIRST_COMPETITION_ID)) == LEAGUE_MATCH_COUNT
    at_home = fixtures_table.filter(lambda fixture: fixture.home_club_uid == NORTHBRIDGE_UID)
    assert len(at_home) == NORTHBRIDGE_HOME_MATCHES
    # A matchday is the stored index plus one, which is why the index itself ships.
    assert at_home[0].round_index == 4


def test_healthy_fixture_stats_pass_every_gate_and_a_small_span_applies_none() -> None:
    results = evaluate_fixtures(healthy_fixture_stats(), BOUNDS, FULL_SIZE_SPAN_BYTES)
    assert tuple(result.name for result in results) == FIXTURE_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("fixtures", results, strict=True)

    small_results = evaluate_fixtures(healthy_fixture_stats(), BOUNDS, SMALL_SPAN_BYTES)
    assert all(not result.applied and result.passed for result in small_results)
    assert BOUNDS.span_minimum_applies_from_bytes == FULL_SAVE_MINIMUM_SPAN_BYTES
    # A broken decode must fail, not slip through for want of a rate.
    empty_results = evaluate_fixtures(consistent_stats(0), BOUNDS, SMALL_SPAN_BYTES)
    assert all(not result.applied for result in empty_results)


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(consistent_stats(5_000), [], id="at-the-record-floor"),
        pytest.param(consistent_stats(4_999), ["fixtures_minimum"], id="below-the-record-floor"),
        pytest.param(
            dataclasses.replace(healthy_fixture_stats(), span_records=130_000),
            ["fixture_cluster_share"],
            id="the-kept-run-is-too-small-a-share",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_fixture_stats(),
                span_records=105_546,
                clusters=1,
                strays_without_a_copy=0,
            ),
            ["fixture_strays_minimum"],
            id="the-calendar-swallowed-every-stray-copy",
        ),
        pytest.param(
            dataclasses.replace(healthy_fixture_stats(), stage_resolved=98_700),
            ["fixture_stage_resolved"],
            id="too-few-stages-resolve",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_fixture_stats(), home_team_resolved=80_000, away_team_resolved=80_000
            ),
            ["fixture_teams_resolved"],
            id="too-few-teams-resolve",
        ),
        pytest.param(
            # The ground share is the one gate an empty decode leaves alone: a calendar
            # legitimately holds records that store no ground, so its own population being
            # empty is reported rather than failed. The record floor fails instead.
            FixtureStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            [name for name in FIXTURE_GATE_NAMES if name != "fixture_stadiums_resolved"],
            id="a-decode-that-found-nothing",
        ),
    ],
)
def test_fixture_gates_fail_one_at_a_time(
    stats: FixtureStats, expected_failures: list[str]
) -> None:
    """A span pass that finds nothing fails every gate rather than reporting an empty career."""
    results = evaluate_fixtures(stats, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == expected_failures
    if not expected_failures:
        enforce("fixtures", results, strict=True)
        return
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("fixtures", results, strict=True)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


def test_field_statuses_follow_the_fixture_coverage() -> None:
    for verified_field in ("stage_id", "competition_id", "round", "date", "kick_off_time"):
        assert field_status(Fixture, verified_field) == "verified", verified_field
    for unconfirmed_field in ("competition_name", "match_record_id", "match_rules_template"):
        assert field_status(Fixture, unconfirmed_field) == "unconfirmed", unconfirmed_field
    assert Fixture.UNKNOWN_KEYS == (
        "date2",
        "phase",
        "leg",
        "r39_42",
        "r47_54",
        "result_r22",
    )


def test_the_build_counts_exactly_what_the_checks_read(career_save_path: Path) -> None:
    """Every fixture gate and anomaly judges these counts, and only the build produces them."""
    with fmsave.open(career_save_path) as career_save:
        _fixtures, stats = built_from(career_save)

    assert stats == FixtureStats(
        span_records=CALENDAR_FIXTURE_COUNT + STRAY_FIXTURE_COUNT,
        cluster_records=CALENDAR_FIXTURE_COUNT,
        clusters=2,
        strays_without_a_copy=STRAY_FIXTURE_COUNT,
        with_stage=CALENDAR_FIXTURE_COUNT,
        stage_resolved=CALENDAR_FIXTURE_COUNT - 1,
        home_team_resolved=CALENDAR_FIXTURE_COUNT,
        away_team_resolved=CALENDAR_FIXTURE_COUNT,
        undated=0,
        bad_kick_off_slots=0,
        neutral_venue_votes=1,
        with_stadium=CALENDAR_FIXTURE_COUNT,
        stadium_resolved=CALENDAR_FIXTURE_COUNT,
    )
    reader_check = check_fixtures(stats, NO_RESULT_STATS, BOUNDS, SMALL_SPAN_BYTES)
    assert reader_check.reader == "fixtures"
    assert reader_check.record_count == CALENDAR_FIXTURE_COUNT
    assert dict(reader_check.anomalies) == {
        "stray_records": STRAY_FIXTURE_COUNT,
        "stray_clusters": 1,
        "strays_without_a_copy": STRAY_FIXTURE_COUNT,
        "fixtures_without_a_stage": 0,
        "unresolved_stages": 1,
        "unresolved_teams": 0,
        "undated_fixtures": 0,
        "bad_kick_off_slots": 0,
        "neutral_venue_votes": 1,
        "unresolved_stadiums": 0,
        "unjoined_results": 0,
        "ambiguous_results": 0,
        "score_disagreements": 0,
        "scored_fixtures": 0,
    }
