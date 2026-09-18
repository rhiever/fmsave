from __future__ import annotations

import copy
import csv
import dataclasses
import json
import pickle
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

import fmsave
from fmsave import Table, checks
from fmsave._layouts import GateBounds, LeagueTableLayout, find_layout
from fmsave._reader_stats import LeagueTableStats
from fmsave._save import LEAGUE_TABLES_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.checks import GateResult, check_league_tables, enforce, evaluate_league_tables
from fmsave.export import column_names, record_to_dict
from fmsave.models.league_tables import (
    LeagueTable,
    LeagueTableRow,
    LeagueTableSplit,
    MatchOutcome,
    Venue,
)
from fmsave.readers._common import GAME_DB_SECTION, SPAN_REGION
from fmsave.readers.league_tables import (
    build_league_tables,
    group_blocks,
    resolve_group_competitions,
)
from fmsave.readers.span import RawTableBlock, RawTableRow
from tests.fixtures.career import (
    ATHLETIC_TEAM_A,
    ATHLETIC_UID,
    DIVISION_CLUB_COUNT,
    DUPLICATE_TABLE_HEAD_BYTES,
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    OUT_OF_RANGE_TABLE_TEAM_ID,
    SOUTHPORT_TEAM,
    SOUTHPORT_UID,
    TABLE_HEAD_BYTES,
    TABLE_VOTE_FIXTURES,
    VENUE_EARLIER_SEASON_FIXTURES,
    VENUE_FIXTURES,
    VENUE_RESULTS,
    VENUE_TABLE_BLOCKS,
    VENUE_TABLE_TEAM_A,
    VENUE_TABLE_TEAM_B,
    ExampleFixture,
    ExampleResult,
    career_fragment,
    division_table_blocks,
    out_of_range_table_blocks,
    stored_index_head_bytes,
)

FILE_NAME = "career example.fm"
MEBIBYTE = 1024 * 1024
FULL_SIZE_SPAN_BYTES = 120 * MEBIBYTE
SMALL_SPAN_BYTES = 1 * MEBIBYTE
TABLE_LAYOUT: LeagueTableLayout = find_layout(LeagueTableLayout, SPAN_REGION, None, "").layout
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, 4000, "").layout

GATE_NAMES = (
    "table_blocks_minimum",
    "table_block_duplicates_minimum",
    "table_block_team_in_range",
    "table_groups_resolved",
    "double_round_robin_divisions",
    "table_venue_calendar_agreement",
)
# The venue check has no population when no table is in step with the calendar, so it is the
# one gate here an empty decode leaves unapplied rather than failed.
GATE_NAMES_AN_EMPTY_DECODE_FAILS = GATE_NAMES[:-1]
GROUP_A_CLUB_COUNT = 3
GROUP_B_CLUB_COUNT = 1
DEFAULT_BLOCK_COUNT = GROUP_A_CLUB_COUNT + GROUP_B_CLUB_COUNT
# Two clubs, two slots each, every one of them decided by the calendar.
VENUE_SLOT_COUNT = 4
# Bounds the example calendar cannot meet, so the fixture checks raise before this reader
# builds anything. The span threshold is lifted so the fixture gates apply to a small span.
UNMEETABLE_FIXTURE_BOUNDS = dataclasses.replace(
    BOUNDS, span_minimum_applies_from_bytes=0, fixtures_minimum=(1_000_000, None)
)


def write_career(tmp_path: Path, **fragment_arguments: object) -> Path:
    """The career fragment with the table-vote fixtures, written for one test."""
    return career_fragment(
        extra_fixtures=TABLE_VOTE_FIXTURES,
        **fragment_arguments,  # pyright: ignore[reportArgumentType]
    ).write(tmp_path / "Private Folder" / FILE_NAME)


def write_venue_career(
    tmp_path: Path,
    *,
    results: Sequence[ExampleResult] = VENUE_RESULTS,
    extra_fixtures: Sequence[ExampleFixture] = (),
) -> Path:
    """A career whose third table accounts for exactly the two matches its clubs have played.

    `results` narrows which of the two meetings carry a score, and `extra_fixtures` adds
    calendar records that take the table out of step.
    """
    return career_fragment(
        extra_fixtures=(*TABLE_VOTE_FIXTURES, *VENUE_FIXTURES, *extra_fixtures),
        extra_table_groups=(VENUE_TABLE_BLOCKS,),
        span_results=results,
    ).write(tmp_path / "Private Folder" / FILE_NAME)


def built_with_layout(
    career_save: fmsave.Save, layout: LeagueTableLayout
) -> tuple[tuple[LeagueTable, ...], LeagueTableStats]:
    """The tables and their counts, built straight from the save's own shared indexes."""
    context = career_save._context  # pyright: ignore[reportPrivateUsage]
    fixtures_table = career_save.fixtures()
    club_index = context.club_index()
    competition_index = context.competition_index()
    return build_league_tables(
        context.span_records(), fixtures_table, competition_index, club_index, layout
    )


def built_from(career_save: fmsave.Save) -> tuple[tuple[LeagueTable, ...], LeagueTableStats]:
    return built_with_layout(career_save, TABLE_LAYOUT)


def gate_named(results: tuple[GateResult, ...], name: str) -> GateResult:
    return next(result for result in results if result.name == name)


def raw_block(
    team_id: int, span_offset: int, *, rounds_per_venue: int = 1, stored_index: int = 0
) -> RawTableBlock:
    """A block these tests care about for its team id, its stored index and where it sits."""
    row = RawTableRow(
        key=TABLE_LAYOUT.unplayed_key,
        played=1,
        won=1,
        drawn=0,
        lost=0,
        goals_for=1,
        goals_against=0,
        points=3,
        flag=0,
    )
    return RawTableBlock(
        span_offset=span_offset,
        team_id=team_id,
        head_bytes=tuple(stored_index_head_bytes(stored_index)),
        aggregates=(row,) * 5,
        rounds_per_venue=rounds_per_venue,
        matches=(row,) * (2 * rounds_per_venue),
    )


# A block, group and slot population invented here, so that no count in this file comes from a
# real save. Each is round, so every share below is an exact count, and the shape is the one a
# sound decode gives: ten thousand blocks kept and nearly as many again dropped as repeats,
# grouped into a thousand tables of which almost all are voted a competition.
HEALTHY_BLOCKS = 10_000
HEALTHY_DUPLICATE_BLOCKS = 8_000
HEALTHY_GROUPS = 1_000
HEALTHY_VENUE_SLOTS = 10_000
# The floors these counts are judged against, named here so each case below straddles one of
# them by a single block, group, division or slot rather than by a figure written out by hand.
BLOCK_FLOOR = 200
DUPLICATE_FLOOR = 100
TEAM_IN_RANGE_FLOOR = 0.99
GROUPS_RESOLVED_FLOOR = 0.70
DIVISION_FLOOR = 5
VENUE_AGREEMENT_FLOOR = 0.95
# What the parity scores read the other way round, in the layout's own record of it: a fifth of
# a percent of the slots the calendar decides. A share is a property of the format rather than a
# count from any one save.
FLIPPED_PARITY_AGREEMENT_SHARE = 0.0024


def healthy_stats() -> LeagueTableStats:
    """An invented span the shape a sound decode gives, inside every bound."""
    return LeagueTableStats(
        blocks=HEALTHY_BLOCKS,
        duplicate_blocks=HEALTHY_DUPLICATE_BLOCKS,
        block_candidates=100 * HEALTHY_BLOCKS,
        groups=HEALTHY_GROUPS,
        groups_resolved=HEALTHY_GROUPS,
        blocks_in_resolved_groups=HEALTHY_BLOCKS,
        team_id_in_range=HEALTHY_BLOCKS,
        team_resolved=4 * HEALTHY_BLOCKS // 5,
        double_round_robin_divisions=HEALTHY_GROUPS // 10,
        in_sync_tables=HEALTHY_GROUPS // 5,
        venue_slots_decided=HEALTHY_VENUE_SLOTS,
        venue_slots_agreeing=HEALTHY_VENUE_SLOTS,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def with_gate_bounds(monkeypatch: pytest.MonkeyPatch, bounds: GateBounds) -> None:
    """Judge the next save's readers against these bounds instead of the registered ones."""
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: bounds)


def test_each_group_of_blocks_becomes_one_table_in_stored_order(tmp_path: Path) -> None:
    """A group is one table, and a row's position is its place in the order the save stores."""
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()

    assert len(tables) == 2
    assert [table.club_count for table in tables] == [GROUP_A_CLUB_COUNT, GROUP_B_CLUB_COUNT]
    assert [row.position for row in tables[0].rows] == [1, 2, 3]
    assert [row.team_id for row in tables[0].rows] == [
        NORTHBRIDGE_TEAM_A,
        SOUTHPORT_TEAM,
        ATHLETIC_TEAM_A,
    ]
    assert tables[1].rows[0].team_id == NORTHBRIDGE_TEAM_B


def test_the_calendar_vote_names_one_group_and_leaves_the_other_empty(tmp_path: Path) -> None:
    """A group whose members never appear in a fixture keeps no competition, and is returned."""
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()

    assert tables[0].competition_id == FIRST_COMPETITION_ID
    assert tables[1].competition_id is None
    assert tables[1].club_count == GROUP_B_CLUB_COUNT


def test_a_row_joins_to_its_club_name_and_team_slot(tmp_path: Path) -> None:
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        first_row = career_save.league_tables()[0].rows[0]
        reserve_row = career_save.league_tables()[1].rows[0]

    assert first_row.club_uid == NORTHBRIDGE_UID
    assert first_row.club_name == "Northbridge FC"
    assert first_row.club_short_name == "Northbridge"
    assert first_row.team_slot == 0
    # A club's later team slots keep their position in its own team list.
    assert reserve_row.club_uid == NORTHBRIDGE_UID
    assert reserve_row.team_slot == 1


def test_the_totals_and_the_four_splits_come_from_the_five_aggregates(tmp_path: Path) -> None:
    """The total aggregate becomes the row's own counters and the other four become splits."""
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        first_row = career_save.league_tables()[0].rows[0]

    assert (first_row.played, first_row.won, first_row.drawn, first_row.lost) == (4, 3, 0, 1)
    assert (first_row.goals_for, first_row.goals_against, first_row.points) == (9, 4, 9)
    assert first_row.home == LeagueTableSplit(2, 2, 0, 0, 5, 2, 6)
    assert first_row.away == LeagueTableSplit(2, 1, 0, 1, 4, 2, 3)
    assert first_row.first_half.played == 2
    assert first_row.second_half.points == 3
    assert first_row.rounds_per_venue == 2
    # Goal difference is derived, not stored.
    assert first_row.goals_for - first_row.goals_against == 5


def test_a_slot_carries_its_outcome_points_and_opponent_or_keeps_its_place_empty(
    tmp_path: Path,
) -> None:
    """Each of the three outcomes is read from the row's own counters, never from a code.

    A slot never played must survive too, so the shape of the season is not lost: it keeps its
    place in the list with every field of its own empty.
    """
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()
        first_row = tables[0].rows[0]
        drawn = tables[1].rows[0].matches[0]

    assert len(first_row.matches) == 2 * first_row.rounds_per_venue
    assert [match_row.slot for match_row in first_row.matches] == [0, 1, 2, 3]
    won, lost = first_row.matches[0], first_row.matches[3]
    for match_row, outcome, points, opponent_uid in (
        (won, MatchOutcome.WIN, 3, SOUTHPORT_UID),
        (lost, MatchOutcome.LOSS, 0, ATHLETIC_UID),
        (drawn, MatchOutcome.DRAW, 1, NORTHBRIDGE_UID),
    ):
        assert match_row.outcome is outcome
        assert match_row.points == points
        assert match_row.opponent_club_uid == opponent_uid
        assert match_row.opponent_club_short_name is not None

    unplayed = first_row.matches[2]
    assert unplayed.opponent_team_id is None
    assert unplayed.opponent_club_uid is None
    assert unplayed.goals_for is None
    assert unplayed.goals_against is None
    assert unplayed.outcome is None
    assert unplayed.points is None


def test_every_slot_alternates_its_venue_from_the_even_slot_home(tmp_path: Path) -> None:
    """Even slots are home matches, so a row's venues alternate from the first slot on.

    A slot never played keeps a venue too: the parity is a property of the slot, not of what
    happened in it, so the shape of the season stays readable where the season is unplayed.
    """
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        first_row = career_save.league_tables()[0].rows[0]

    assert TABLE_LAYOUT.home_slot_parity == 0
    assert [match_row.home_or_away for match_row in first_row.matches] == [
        Venue.HOME,
        Venue.AWAY,
        Venue.HOME,
        Venue.AWAY,
    ]
    assert first_row.matches[2].opponent_team_id is None
    assert first_row.matches[2].home_or_away is Venue.HOME
    assert field_status(fmsave.LeagueTableMatch, "home_or_away") == "verified"


def test_a_layout_with_no_parity_leaves_every_venue_empty_and_checks_nothing(
    tmp_path: Path,
) -> None:
    """A build that has not settled the parity returns no venue and decides no slot.

    The check then has no population at all, which is reported rather than failed: there is
    nothing wrong with a save read by a layout that names no parity.
    """
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables, stats = built_with_layout(
            career_save, dataclasses.replace(TABLE_LAYOUT, home_slot_parity=None)
        )

    assert all(
        match_row.home_or_away is None
        for table in tables
        for row in table.rows
        for match_row in row.matches
    )
    assert (stats.in_sync_tables, stats.venue_slots_decided, stats.venue_slots_agreeing) == (
        0,
        0,
        0,
    )
    venue_gate = gate_named(
        evaluate_league_tables(stats, BOUNDS, FULL_SIZE_SPAN_BYTES),
        "table_venue_calendar_agreement",
    )
    assert not venue_gate.applied


def test_the_calendar_decides_the_venue_of_every_slot_of_an_in_step_table(
    tmp_path: Path,
) -> None:
    """A table whose rows account for one season's matches is checked against the calendar.

    Both meetings of these two clubs are played, so neither slot is decided by there being
    only one meeting: each is decided because exactly one of the two scores, oriented to the
    row's own club, is the score the slot carries. The calendar's own home team then names the
    venue, and it agrees with the parity on all four slots.
    """
    career_path = write_venue_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()
        _tables, stats = built_from(career_save)

    assert stats.in_sync_tables >= 1
    assert stats.venue_slots_decided == VENUE_SLOT_COUNT
    assert stats.venue_slots_agreeing == VENUE_SLOT_COUNT
    venue_table = tables[2]
    assert [row.team_id for row in venue_table.rows] == [VENUE_TABLE_TEAM_A, VENUE_TABLE_TEAM_B]
    assert [match_row.home_or_away for match_row in venue_table.rows[0].matches] == [
        Venue.HOME,
        Venue.AWAY,
    ]


def test_the_flipped_parity_agrees_with_the_calendar_on_no_slot_at_all(tmp_path: Path) -> None:
    """The check that keeps the parity honest: read the other way round, nothing agrees.

    On the corpus the same flip drops agreement from 0.998 to 0.002, so this is the failure the
    gate exists for, and here it is the whole population rather than a sample of it.
    """
    career_path = write_venue_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        _tables, stats = built_with_layout(
            career_save, dataclasses.replace(TABLE_LAYOUT, home_slot_parity=1)
        )

    assert stats.venue_slots_decided == VENUE_SLOT_COUNT
    assert stats.venue_slots_agreeing == 0
    # The fragment's own block counts are far below the floors, so the gate is judged here on a
    # full span's shape with this fragment's agreement put in place of that shape's own.
    flipped_on_a_full_save = dataclasses.replace(
        healthy_stats(),
        venue_slots_decided=stats.venue_slots_decided,
        venue_slots_agreeing=stats.venue_slots_agreeing,
    )
    results = evaluate_league_tables(flipped_on_a_full_save, BOUNDS, FULL_SIZE_SPAN_BYTES)
    assert failed_gate_names(results) == ["table_venue_calendar_agreement"]
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("league_tables", results, strict=True)
    assert "table_venue_calendar_agreement" in str(error_info.value)


def test_two_played_meetings_with_no_score_decide_nothing(tmp_path: Path) -> None:
    """Without the scores the two meetings are indistinguishable, so no slot is decided.

    Nothing is guessed from the order the save lists the slots in: that order is the very
    thing the check is there to judge.
    """
    career_path = write_venue_career(tmp_path, results=())

    with fmsave.open(career_path) as career_save:
        _tables, stats = built_from(career_save)

    assert stats.in_sync_tables >= 1
    assert stats.venue_slots_decided == 0
    assert stats.venue_slots_agreeing == 0


def test_one_scored_meeting_and_one_unscored_decide_nothing_either(tmp_path: Path) -> None:
    """Every played meeting must carry a score before a score may decide a slot.

    With one of the two meetings scored, the scored one matches a slot uniquely among the
    meetings that have a score -- and that is not the same as matching uniquely among the
    meetings that were played. Deciding on it would name a venue from an incomplete comparison,
    so the whole slot is left undecided, which is why this is the case that separates skipping
    an unscored meeting from refusing the slot outright.
    """
    career_path = write_venue_career(tmp_path, results=VENUE_RESULTS[:1])

    with fmsave.open(career_path) as career_save:
        _tables, stats = built_from(career_save)

    assert stats.in_sync_tables >= 1
    assert stats.venue_slots_decided == 0
    assert stats.venue_slots_agreeing == 0


def test_a_table_matching_two_seasons_is_turned_away_like_one_matching_none(
    tmp_path: Path,
) -> None:
    """Exactly one season may match, because two leave no season the row counts describe.

    These clubs played each other twice in each of two seasons, so the table's row counts hold
    in both and a slot cannot be matched to the meeting it records. On the corpus a handful of
    tables per save are in this position, and taking either season would compare half the slots
    against the wrong pair of matches.
    """
    career_path = write_venue_career(tmp_path, extra_fixtures=VENUE_EARLIER_SEASON_FIXTURES)

    with fmsave.open(career_path) as career_save:
        _tables, stats = built_from(career_save)

    assert stats.in_sync_tables == 0
    assert stats.venue_slots_decided == 0


def test_a_table_out_of_step_with_the_calendar_decides_nothing(tmp_path: Path) -> None:
    """Only a table that accounts for one season's matches may judge the parity.

    The example's first table is out of step in exactly the way most of the corpus is:
    Southport's row says four matches played where the calendar holds three of its league
    fixtures. Over every table rather than the tables in step, corpus agreement falls from
    0.998 to about 0.91, because an out-of-step table is compared against the wrong meetings.
    """
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()
        _tables, stats = built_from(career_save)

    southport_row = tables[0].rows[1]
    assert southport_row.team_id == SOUTHPORT_TEAM
    assert southport_row.played == 4
    assert stats.in_sync_tables == 0
    assert stats.venue_slots_decided == 0


def test_the_head_blob_ships_as_one_unknown_int_per_byte(tmp_path: Path) -> None:
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        first_row = career_save.league_tables()[0].rows[0]

    assert LeagueTableRow.UNKNOWN_KEYS[0] == "head_minus_19_00"
    assert LeagueTableRow.UNKNOWN_KEYS[-1] == "head_minus_19_18"
    assert len(LeagueTableRow.UNKNOWN_KEYS) == len(TABLE_HEAD_BYTES)
    assert first_row.unknown["head_minus_19_00"] == 0
    assert first_row.unknown["head_minus_19_18"] == 18
    assert field_status(LeagueTableRow, "unknown") == "unconfirmed"
    assert field_status(LeagueTableRow, "position") == "verified"
    assert field_status(LeagueTable, "competition_id") == "unconfirmed"


def test_a_competition_is_named_only_through_a_supplied_map(tmp_path: Path) -> None:
    """No save stores a competition name, so a name arrives through the database id or not at all."""
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as unnamed_save:
        without_map = [table.competition_name for table in unnamed_save.league_tables()]
    with fmsave.open(
        career_path, competition_names={FIRST_COMPETITION_DATABASE_ID: "Example League"}
    ) as named_save:
        with_map = [table.competition_name for table in named_save.league_tables()]

    assert without_map == [None, None]
    assert with_map == ["Example League", None]


def test_a_team_id_outside_the_range_leaves_the_club_fields_empty(tmp_path: Path) -> None:
    """An id no club can carry is still returned as a row, with nothing guessed onto it."""
    career_path = write_career(tmp_path, extra_table_groups=(out_of_range_table_blocks(),))

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()
        _tables, stats = built_from(career_save)

    assert len(tables) == 3
    stray_row = tables[2].rows[0]
    assert stray_row.team_id == OUT_OF_RANGE_TABLE_TEAM_ID
    assert stray_row.club_uid is None
    assert stray_row.club_name is None
    assert stray_row.club_short_name is None
    assert stray_row.team_slot is None
    assert stats.blocks == DEFAULT_BLOCK_COUNT + 1
    assert stats.team_id_in_range == DEFAULT_BLOCK_COUNT


def test_repeated_block_content_is_dropped_before_the_groups_are_built(tmp_path: Path) -> None:
    """The save stores each block several times; keeping the copies invents table rows.

    A copy differs from the block it repeats only in the 19 undecoded head bytes, so it passes
    every check the span pass makes. Left in, it puts one club in its table twice, and its own
    stored index is not the one the block it repeats carries, so it breaks the run and splits
    the table around it. The first copy in span order is the one kept.
    """
    career_path = write_career(tmp_path, table_duplicate_head_bytes=(DUPLICATE_TABLE_HEAD_BYTES,))

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()
        _tables, stats = built_from(career_save)

    assert stats.duplicate_blocks == 1
    assert stats.blocks == DEFAULT_BLOCK_COUNT
    assert len(tables) == 2
    assert tables[0].club_count == GROUP_A_CLUB_COUNT
    assert [row.team_id for row in tables[0].rows].count(NORTHBRIDGE_TEAM_A) == 1
    # The kept copy is the first, so its head bytes are the ones reported.
    assert tables[0].rows[0].unknown["head_minus_19_00"] == TABLE_HEAD_BYTES[0]


def test_a_table_ends_where_its_stored_index_stops_counting_on() -> None:
    """The index each block keeps of its place in its table is what separates two tables.

    The distance between blocks is deliberately not consulted: the blocks of two adjacent
    tables sit as close together as the blocks inside one, so a rule on the gap runs tables
    together. Blocks far apart whose indexes carry on are one table, and neighbours whose
    index starts again are two.
    """
    first = raw_block(NORTHBRIDGE_TEAM_A, span_offset=1_000, stored_index=0)
    far_but_counting_on = raw_block(SOUTHPORT_TEAM, span_offset=900_000, stored_index=1)
    next_table = raw_block(ATHLETIC_TEAM_A, span_offset=900_100, stored_index=0)

    groups = group_blocks([first, far_but_counting_on, next_table], TABLE_LAYOUT)

    assert [len(group) for group in groups] == [2, 1]
    assert [block.team_id for block in groups[0]] == [NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM]
    assert group_blocks([], TABLE_LAYOUT) == ()


def test_the_vote_needs_half_the_members_and_reserves_no_competition() -> None:
    """A competition one member of three plays in must never name the whole table.

    One competition does name several tables, because a cup's group stage is one competition
    holding a table per group: the corpus has about 800 tables against about 520 competitions,
    so reserving a competition for the first table to claim it leaves most tables unnamed.
    """
    members = [raw_block(1, 100), raw_block(2, 200), raw_block(3, 300)]
    second_table = [raw_block(4, 9_000), raw_block(5, 9_100)]
    one_member_plays_it = {1: Counter({FIRST_COMPETITION_ID: 9})}
    every_member_plays_it = {team_id: Counter({FIRST_COMPETITION_ID: 4}) for team_id in range(1, 6)}

    assert resolve_group_competitions([members], one_member_plays_it) == (None,)
    assert resolve_group_competitions([members, second_table], every_member_plays_it) == (
        FIRST_COMPETITION_ID,
        FIRST_COMPETITION_ID,
    )


def test_a_division_is_counted_by_its_shape_alone(tmp_path: Path) -> None:
    """The shape rule needs no competition name, so it holds in any country.

    The same clubs one round short of playing each other twice keep the club count and lose
    the shape, which is what the division count has to notice.
    """
    division_path = write_career(
        tmp_path / "division",
        extra_table_groups=(division_table_blocks(),),
    )
    one_round_short_path = write_career(
        tmp_path / "one round short",
        extra_table_groups=(division_table_blocks(rounds_per_venue=DIVISION_CLUB_COUNT - 2),),
    )

    with fmsave.open(division_path) as division_save:
        division_tables = division_save.league_tables()
        _division_tables, division_stats = built_from(division_save)
    with fmsave.open(one_round_short_path) as short_save:
        short_tables = short_save.league_tables()
        _short_tables, short_stats = built_from(short_save)

    assert division_tables[2].club_count == DIVISION_CLUB_COUNT
    assert division_tables[2].rows[0].rounds_per_venue == DIVISION_CLUB_COUNT - 1
    assert division_stats.double_round_robin_divisions == 1
    assert short_tables[2].club_count == DIVISION_CLUB_COUNT
    assert short_tables[2].rows[0].rounds_per_venue == DIVISION_CLUB_COUNT - 2
    assert short_stats.double_round_robin_divisions == 0


def test_export_flattens_the_splits_and_keeps_the_rows_nested(tmp_path: Path) -> None:
    """A table's rows nest, so CSV puts them in one cell and JSON keeps them as an array."""
    assert column_names(LeagueTable) == ("competition_id", "competition_name", "club_count", "rows")
    row_columns = column_names(LeagueTableRow)
    for split_column in ("home_played", "away_won", "first_half_points", "second_half_lost"):
        assert split_column in row_columns, split_column
    assert "matches" in row_columns
    assert "unknown_head_minus_19_00" in row_columns

    career_path = write_career(tmp_path)
    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()

    as_dict = record_to_dict(tables[0], json_ready=True)
    nested_rows = as_dict["rows"]
    assert isinstance(nested_rows, list)
    first_nested_row = nested_rows[0]
    assert isinstance(first_nested_row, dict)
    assert first_nested_row["club_name"] == "Northbridge FC"
    # A row's splits nest here and flatten only into the row's own columns, above.
    home_split = first_nested_row["home"]
    assert isinstance(home_split, dict)
    assert home_split["played"] == 2
    assert tables.to_columns()["club_count"] == [GROUP_A_CLUB_COUNT, GROUP_B_CLUB_COUNT]

    csv_path = tmp_path / "league_tables.csv"
    tables.write_csv(csv_path)
    header_line, first_table_line = csv_path.read_text(encoding="utf-8").splitlines()[:2]
    assert header_line == "competition_id,competition_name,club_count,rows"
    rows_cell = next(csv.reader([first_table_line]))[-1]
    assert json.loads(rows_cell)[0]["club_name"] == "Northbridge FC"


def test_records_survive_pickle_and_deepcopy(tmp_path: Path) -> None:
    """Every public record must survive both, which is what a round trip of each one shows.

    The pickled bytes are this test's own records, built moments earlier in this process, so
    nothing untrusted is ever unpickled.
    """
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        tables = career_save.league_tables()

    for example in (tables[0], tables[0].rows[0], tables):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_league_tables_returns_one_cached_table_and_raises_after_close(tmp_path: Path) -> None:
    career_path = write_career(tmp_path)
    career_save = fmsave.open(career_path)
    tables = career_save.league_tables()

    assert isinstance(tables, Table)
    assert tables.record_type is LeagueTable
    assert career_save.league_tables() is tables
    assert LEAGUE_TABLES_TABLE_CACHE_KEY == "table:league_tables"

    rows_before_close = list(tables)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.league_tables()
    assert list(tables) == rows_before_close


def test_a_failed_calendar_check_stops_the_tables_being_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vote may only run on a calendar whose own checks passed.

    A calendar that had shattered into fragments, or swallowed the template matches no save
    plays, would otherwise vote a competition onto hundreds of tables and raise nothing.
    """
    career_path = write_career(tmp_path)
    with_gate_bounds(monkeypatch, UNMEETABLE_FIXTURE_BOUNDS)

    with (
        fmsave.open(career_path, strict=True) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.league_tables()

    assert "fixtures_minimum" in str(error_info.value)


@pytest.mark.parametrize(
    ("evaluation_name", "reader_name"),
    [
        pytest.param("evaluate_clubs", "clubs", id="the-club-checks-failed"),
        pytest.param("evaluate_stages", "stages", id="the-stage-checks-failed"),
        pytest.param("evaluate_competitions", "competitions", id="the-competition-checks-failed"),
    ],
)
def test_a_failed_check_on_a_borrowed_index_stops_the_tables_being_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evaluation_name: str,
    reader_name: str,
) -> None:
    """An index may only be handed out through the accessor that enforces its own checks.

    This reader hands borrowed data straight out: a club name and a team slot on every row, a
    competition id on every table, and the stage joins the calendar vote runs on. Taking any of
    those three indexes from the context instead of from its reader would return thousands of
    names out of a decode whose checks never ran, and raise nothing at all, so each reader's
    failure has to stop this call.
    """

    def failing_evaluation(
        stats: object, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        return (GateResult("a_failed_gate", 0.5, 0.9, None, False, True),)

    monkeypatch.setattr(checks, evaluation_name, failing_evaluation)
    career_path = write_career(tmp_path)

    with (
        fmsave.open(career_path, strict=True) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.league_tables()

    assert str(error_info.value).startswith(f"{reader_name} failed checks: ")


def test_the_build_counts_exactly_what_the_checks_read(tmp_path: Path) -> None:
    """Every league-table gate and anomaly judges these counts, and only the build makes them."""
    career_path = write_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        _tables, stats = built_from(career_save)

    assert dataclasses.replace(stats, block_candidates=0) == LeagueTableStats(
        blocks=DEFAULT_BLOCK_COUNT,
        duplicate_blocks=0,
        block_candidates=0,
        groups=2,
        groups_resolved=1,
        blocks_in_resolved_groups=GROUP_A_CLUB_COUNT,
        team_id_in_range=DEFAULT_BLOCK_COUNT,
        team_resolved=DEFAULT_BLOCK_COUNT,
        double_round_robin_divisions=0,
        in_sync_tables=0,
        venue_slots_decided=0,
        venue_slots_agreeing=0,
    )
    assert stats.block_candidates >= stats.blocks
    reader_check = check_league_tables(stats, BOUNDS, SMALL_SPAN_BYTES)
    assert reader_check.reader == "league_tables"
    assert reader_check.record_count == 2
    assert dict(reader_check.anomalies) == {
        "duplicate_blocks": 0,
        "rejected_block_candidates": stats.block_candidates - DEFAULT_BLOCK_COUNT,
        "unresolved_groups": 1,
        "blocks_outside_resolved_groups": GROUP_B_CLUB_COUNT,
        "team_ids_out_of_range": 0,
        "unresolved_teams": 0,
        "in_sync_tables": 0,
        "venue_slots_decided": 0,
    }


# Each bound with the counts that meet it exactly. The failing side of every one of these is a
# case of `test_league_table_gates_fail_one_at_a_time`, one unit below the same bound, so the
# two together pin each floor from both sides.
GATE_FLOORS = (
    ("table_blocks_minimum", {"blocks": BLOCK_FLOOR, "team_id_in_range": BLOCK_FLOOR}),
    ("table_block_duplicates_minimum", {"duplicate_blocks": DUPLICATE_FLOOR}),
    (
        "table_block_team_in_range",
        {"team_id_in_range": round(TEAM_IN_RANGE_FLOOR * HEALTHY_BLOCKS)},
    ),
    ("table_groups_resolved", {"groups_resolved": round(GROUPS_RESOLVED_FLOOR * HEALTHY_GROUPS)}),
    ("double_round_robin_divisions", {"double_round_robin_divisions": DIVISION_FLOOR}),
    (
        "table_venue_calendar_agreement",
        {"venue_slots_agreeing": round(VENUE_AGREEMENT_FLOOR * HEALTHY_VENUE_SLOTS)},
    ),
)


@pytest.mark.parametrize(
    ("gate_name", "replacements"),
    GATE_FLOORS,
    ids=[gate_name for gate_name, _replacements in GATE_FLOORS],
)
def test_each_league_table_gate_passes_exactly_on_its_floor(
    gate_name: str, replacements: dict[str, int]
) -> None:
    stats = dataclasses.replace(healthy_stats(), **replacements)

    results = evaluate_league_tables(stats, BOUNDS, FULL_SIZE_SPAN_BYTES)
    assert gate_named(results, gate_name).applied
    assert failed_gate_names(results) == []


def test_healthy_stats_pass_every_gate_and_a_small_span_applies_none() -> None:
    results = evaluate_league_tables(healthy_stats(), BOUNDS, FULL_SIZE_SPAN_BYTES)
    assert tuple(result.name for result in results) == GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("league_tables", results, strict=True)

    small_results = evaluate_league_tables(healthy_stats(), BOUNDS, SMALL_SPAN_BYTES)
    assert all(not result.applied and result.passed for result in small_results)


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(
            dataclasses.replace(
                healthy_stats(), blocks=BLOCK_FLOOR - 1, team_id_in_range=BLOCK_FLOOR - 1
            ),
            ["table_blocks_minimum"],
            id="one-block-below-the-block-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), duplicate_blocks=DUPLICATE_FLOOR - 1),
            ["table_block_duplicates_minimum"],
            id="one-block-below-the-duplicate-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), team_id_in_range=round(TEAM_IN_RANGE_FLOOR * HEALTHY_BLOCKS) - 1
            ),
            ["table_block_team_in_range"],
            id="one-block-below-the-team-in-range-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), groups_resolved=round(GROUPS_RESOLVED_FLOOR * HEALTHY_GROUPS) - 1
            ),
            ["table_groups_resolved"],
            id="one-group-below-the-resolved-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), double_round_robin_divisions=DIVISION_FLOOR - 1),
            ["double_round_robin_divisions"],
            id="one-division-below-the-division-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(),
                venue_slots_agreeing=round(VENUE_AGREEMENT_FLOOR * HEALTHY_VENUE_SLOTS) - 1,
            ),
            ["table_venue_calendar_agreement"],
            id="one-slot-below-the-venue-agreement-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(),
                venue_slots_agreeing=round(FLIPPED_PARITY_AGREEMENT_SHARE * HEALTHY_VENUE_SLOTS),
            ),
            ["table_venue_calendar_agreement"],
            id="the-slot-parity-is-the-wrong-way-round",
        ),
        pytest.param(
            LeagueTableStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            list(GATE_NAMES_AN_EMPTY_DECODE_FAILS),
            id="a-decode-that-found-nothing",
        ),
    ],
)
def test_league_table_gates_fail_one_at_a_time(
    stats: LeagueTableStats, expected_failures: Sequence[str]
) -> None:
    """A span pass that finds nothing fails every gate it has a population for, and each
    filter that stopped filtering fails its own gate alone.

    Every floor case sits one block, group, division or slot below its bound, so a bound that
    moved would leave the case on the wrong side of it and show up here. The last parity case
    carries the share reading the slots the other way round scores on every save measured.
    """
    results = evaluate_league_tables(stats, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == list(expected_failures)
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("league_tables", results, strict=True)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message
