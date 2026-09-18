from __future__ import annotations

import copy
import dataclasses
import pickle
from array import array
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave import Table
from fmsave._layouts import GateBounds, MatchRecordLayout, PlayerRecordLayout, find_layout
from fmsave._reader_stats import MatchStats
from fmsave._save import PLAYER_MATCH_STATS_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.checks import (
    GateResult,
    check_player_match_stats,
    enforce,
    evaluate_player_match_stats,
)
from fmsave.export import column_names
from fmsave.models.matches import MatchPosition, PlayerMatchStats
from fmsave.models.players import Player
from fmsave.readers.clubs import ClubIndex, find_club_layouts, read_club_index
from fmsave.readers.matches import (
    UNOWNED_POSITION,
    RawMatchRecord,
    build_player_match_stats,
    find_match_record_layout,
    locate_match_records,
)
from fmsave.readers.player_scan import PlayerRecords
from fmsave.readers.stages import StageIndex, find_stage_layout, read_stage_index
from tests.fixtures.career import (
    ATHLETIC_UID,
    EXAMPLE_CLUBS,
    FIRST_COMPETITION_ID,
    FIRST_MATCH_ASSISTS,
    FIRST_MATCH_GOALS,
    FIRST_MATCH_LEFT_AT,
    FIRST_MATCH_MINUTES,
    FIRST_MATCH_PASSES_ATTEMPTED,
    FIRST_MATCH_PASSES_COMPLETED,
    FIRST_MATCH_POSITION_MASK,
    FIRST_MATCH_ROLE_CODE,
    MATCH_YEAR,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_UID,
    OUT_OF_RANGE_MATCH_GOALS,
    OUT_OF_RANGE_MATCH_MINUTES,
    PLAYER_A_MATCH_COUNT,
    PLAYER_A_UID,
    UNLISTED_MATCH_COMPETITION_ID,
    UNNAMED_POSITION_MASK,
    career_stage_rows,
    clubs_region_bytes,
)
from tests.fixtures.game_db import match_record_bytes, stage_table_bytes
from tests.helpers.export_asserts import assert_matches_json_normalize

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 300 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
# The in-game date of the example career, which is what the year window is built from.
CLOCK = date(2031, 3, 1)
MATCH_GATE_NAMES = (
    "per_match_competition_in_stage_space",
    "per_match_minutes_in_range",
    "per_match_rating_in_range",
)
# Offsets inside a record, written here rather than read from the layout so a layout that moves
# one of them has to fail a test built from this module.
BODY_FLAG_OFFSET = 14
POSITION_MASK_OFFSET = 17
MATCH_RECORD_HEADER_BYTES = 15
# How far before a player's record start his window opens, which is where a search begins.
OWNER_BACK_OFFSET = 30
# Where the hand-built buffers below put their one player record and their match records.
PLAYER_RECORD_OFFSET = 200
MATCH_RECORD_OFFSET = 400
SYNTHETIC_FIRST_UID = 900_100

EXPECTED_COLUMNS = (
    "player_uid",
    "player_name",
    "date",
    "competition_id",
    "opponent_team_id",
    "opponent_club_uid",
    "opponent_club_name",
    "opponent_club_short_name",
    "opponent_team_slot",
    "has_stats",
    "position",
    "position_code",
    "minutes",
    "left_at_minute",
    "goals",
    "assists",
    "rating",
    "passes_attempted",
    "passes_completed",
    "stats_in_range",
    "unknown_tag",
    "unknown_role_code",
    "unknown_rating_raw",
)


def registered_gate_bounds() -> GateBounds:
    return find_layout(GateBounds, "game_db", GAME_DB_SCHEMA, "").layout


def registered_match_layout() -> MatchRecordLayout:
    return find_match_record_layout(GAME_DB_SCHEMA, "")


BOUNDS = registered_gate_bounds()
EXAMPLE_CLUB_INDEX: ClubIndex = read_club_index(
    clubs_region_bytes(EXAMPLE_CLUBS), find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME
)
EXAMPLE_STAGE_INDEX: StageIndex = read_stage_index(
    stage_table_bytes(career_stage_rows()), find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME
)
NO_PLAYERS: Table[Player] = Table((), Player)


def healthy_stats(records: int = 20_000) -> MatchStats:
    """Counts with every rate comfortably inside its bound."""
    with_body = records * 3 // 5
    return MatchStats(
        records=records,
        with_body=with_body,
        players_with_records=records // 20,
        competition_in_stage_space=records,
        minutes_in_range=with_body,
        rating_in_range=with_body,
        body_valid=with_body,
        opponent_resolved=records - 10,
        unowned=0,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def synthetic_player_records(record_offsets: tuple[int, ...]) -> PlayerRecords:
    return PlayerRecords(
        record_offsets=array("Q", record_offsets),
        pindexes=array("I", range(len(record_offsets))),
        uids=array("I", range(SYNTHETIC_FIRST_UID, SYNTHETIC_FIRST_UID + len(record_offsets))),
        markerless_count=0,
        position_by_pindex={},
        position_by_uid={},
        layout=find_layout(PlayerRecordLayout, "game_db", GAME_DB_SCHEMA, "").layout,
    )


def buffer_with_records(offset: int, records: bytes, *, buffer_length: int = 1000) -> bytes:
    buffer = bytearray(buffer_length)
    buffer[offset : offset + len(records)] = records
    return bytes(buffer)


def match_bytes(
    *,
    day_of_year: int = 51,
    year: int = MATCH_YEAR,
    opponent_team_id: int = NORTHBRIDGE_TEAM_A,
    competition_id: int = FIRST_COMPETITION_ID,
    played: bool = True,
    position_mask: int = FIRST_MATCH_POSITION_MASK,
    minutes: int = 90,
    left_at: int = 90,
    rating_x10: int = 70,
    goals: int = 0,
) -> bytes:
    """One sound match record, with only the field a test is about changed."""
    return match_record_bytes(
        day_of_year=day_of_year,
        year=year,
        opponent_team_id=opponent_team_id,
        competition_id=competition_id,
        played=played,
        position_mask=position_mask,
        minutes=minutes,
        left_at=left_at,
        rating_x10=rating_x10,
        goals=goals,
    )


def located(
    records: bytes,
    *,
    record_offset: int = MATCH_RECORD_OFFSET,
    player_offsets: tuple[int, ...] = (PLAYER_RECORD_OFFSET,),
) -> tuple[tuple[PlayerMatchStats, ...], MatchStats]:
    """Search a hand-built buffer and join what it finds, with no save in the way."""
    layout = registered_match_layout()
    player_records = synthetic_player_records(player_offsets)
    return build_player_match_stats(
        locate_match_records(
            buffer_with_records(record_offset, records), player_records, layout, CLOCK
        ),
        player_records,
        NO_PLAYERS,
        EXAMPLE_CLUB_INDEX,
        EXAMPLE_STAGE_INDEX,
        layout,
    )


@pytest.fixture
def match_rows(career_save_path: Path) -> tuple[PlayerMatchStats, ...]:
    with fmsave.open(career_save_path) as career_save:
        return tuple(career_save.player_match_stats())


def reader_validation(career_save_path: Path) -> fmsave.ReaderValidation:
    with fmsave.open(career_save_path) as career_save:
        report = fmsave.validate_save(career_save)
    return next(reader for reader in report.readers if reader.reader == "player_match_stats")


def test_every_match_of_one_player_is_listed_in_the_order_the_save_stores_them(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    assert len(match_rows) == PLAYER_A_MATCH_COUNT
    assert {row.player_uid for row in match_rows} == {PLAYER_A_UID}
    # Stored order, which is not date order: the save writes the newest match first.
    assert [row.date for row in match_rows] == [
        date(2031, 2, 20),
        date(2031, 2, 13),
        date(2031, 2, 6),
        date(2031, 1, 30),
    ]


def test_a_match_with_a_body_carries_every_field_the_body_holds(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    first_match = match_rows[0]
    assert first_match.has_stats is True
    assert first_match.competition_id == FIRST_COMPETITION_ID
    assert first_match.goals == FIRST_MATCH_GOALS
    assert first_match.assists == FIRST_MATCH_ASSISTS
    assert first_match.minutes == FIRST_MATCH_MINUTES
    assert first_match.left_at_minute == FIRST_MATCH_LEFT_AT
    assert first_match.rating == 7.8
    assert first_match.passes_attempted == FIRST_MATCH_PASSES_ATTEMPTED
    assert first_match.passes_completed == FIRST_MATCH_PASSES_COMPLETED
    assert first_match.stats_in_range is True


def test_a_named_mask_bit_labels_the_position_and_keeps_its_raw_mask(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    position = match_rows[0].position
    assert position is not None
    assert position.raw == FIRST_MATCH_POSITION_MASK
    assert position.label is MatchPosition.GOALKEEPER
    assert position.label_text == "goalkeeper"


def test_the_opponent_joins_to_the_club_fielding_that_team(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    first_match = match_rows[0]
    assert first_match.opponent_team_id == NORTHBRIDGE_TEAM_A
    assert first_match.opponent_club_uid == NORTHBRIDGE_UID
    assert first_match.opponent_club_name == "Northbridge FC"
    assert first_match.opponent_club_short_name == "Northbridge"
    assert first_match.opponent_team_slot == 0


def test_the_unidentified_bytes_are_exported_as_they_are_stored(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    assert dict(match_rows[0].unknown) == {"tag": 0, "role_code": FIRST_MATCH_ROLE_CODE}
    assert PlayerMatchStats.UNKNOWN_KEYS == ("tag", "role_code", "rating_raw")


def test_a_match_with_no_body_carries_nothing_from_past_the_header(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    """The record stops after its header, so every field past it belongs to the next match."""
    without_body = match_rows[1]
    assert without_body.has_stats is False
    assert without_body.stats_in_range is False
    for field_name in (
        "position",
        "minutes",
        "left_at_minute",
        "goals",
        "assists",
        "rating",
        "passes_attempted",
        "passes_completed",
    ):
        assert getattr(without_body, field_name) is None, field_name
    # The tag is inside the header, so it is read; the role code is not, so it is absent and
    # flattens to an empty column rather than to a number belonging to the next match.
    assert dict(without_body.unknown) == {"tag": 0}
    assert without_body.opponent_club_uid == ATHLETIC_UID
    assert without_body.date == date(2031, 2, 13)


def test_a_match_with_no_body_does_not_swallow_the_match_stored_after_it(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    """A record with no body is 15 bytes, not 43, so the next one starts right after it."""
    after_the_short_record = match_rows[2]
    assert after_the_short_record.date == date(2031, 2, 6)
    assert after_the_short_record.competition_id == UNLISTED_MATCH_COMPETITION_ID
    assert after_the_short_record.minutes == 45
    assert after_the_short_record.rating == 6.5
    assert after_the_short_record.has_stats is True
    assert after_the_short_record.stats_in_range is True


def test_a_competition_the_stage_table_does_not_name_is_kept_and_counted(
    career_save_path: Path, match_rows: tuple[PlayerMatchStats, ...]
) -> None:
    assert match_rows[2].competition_id == UNLISTED_MATCH_COMPETITION_ID
    observed = {gate.name: gate.observed for gate in reader_validation(career_save_path).gates}
    # Three of the four records name a competition the stage table holds.
    assert observed["per_match_competition_in_stage_space"] == 0.75


def test_a_body_outside_its_ranges_is_kept_whole_and_only_flagged(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    """Storing the numbers and flagging them is the rule: a failing body is never blanked."""
    out_of_range = match_rows[3]
    assert out_of_range.minutes == OUT_OF_RANGE_MATCH_MINUTES
    assert out_of_range.rating == 12.0
    assert out_of_range.goals == OUT_OF_RANGE_MATCH_GOALS
    assert out_of_range.stats_in_range is False
    assert out_of_range.has_stats is True


def test_an_opponent_no_club_lists_leaves_its_four_fields_empty_and_is_counted(
    career_save_path: Path, match_rows: tuple[PlayerMatchStats, ...]
) -> None:
    unresolved = match_rows[3]
    assert unresolved.opponent_team_id not in EXAMPLE_CLUB_INDEX.team_to_club
    for field_name in (
        "opponent_club_uid",
        "opponent_club_name",
        "opponent_club_short_name",
        "opponent_team_slot",
    ):
        assert getattr(unresolved, field_name) is None, field_name
    assert dict(reader_validation(career_save_path).anomalies) == {
        "records_without_a_body": 1,
        "unresolved_opponents": 1,
        "competitions_outside_the_stage_table": 1,
        "bodies_outside_their_ranges": 1,
        "records_without_an_owner": 0,
    }


def test_each_row_is_named_with_the_player_whose_object_holds_it(
    career_save_path: Path, match_rows: tuple[PlayerMatchStats, ...]
) -> None:
    with fmsave.open(career_save_path) as career_save:
        player_a = career_save.players().by_uid(PLAYER_A_UID)
    assert player_a.name == "Alex Example"
    assert {row.player_name for row in match_rows} == {player_a.name}


@pytest.mark.parametrize(
    ("mask", "expected_label"),
    [
        pytest.param(FIRST_MATCH_POSITION_MASK, MatchPosition.GOALKEEPER, id="named-bit"),
        pytest.param(0, MatchPosition.UNKNOWN, id="no-bit-at-all"),
        pytest.param(1 << 5, MatchPosition.UNKNOWN, id="a-bit-no-label-names"),
        pytest.param(UNNAMED_POSITION_MASK, MatchPosition.UNKNOWN, id="another-unnamed-bit"),
        pytest.param(
            FIRST_MATCH_POSITION_MASK | (1 << 5), MatchPosition.UNKNOWN, id="two-bits-one-named"
        ),
        pytest.param((1 << 5) | (1 << 6), MatchPosition.UNKNOWN, id="two-unnamed-bits"),
    ],
)
def test_a_mask_is_named_only_when_its_one_bit_is_named(
    mask: int, expected_label: MatchPosition
) -> None:
    """Every mask keeps its raw value, whether or not a label reaches it."""
    rows, stats = located(match_bytes(position_mask=mask))
    assert stats.records == 1
    position = rows[0].position
    assert position is not None
    assert position.raw == mask
    assert position.label is expected_label


@pytest.mark.parametrize(
    ("body_flag", "expected_records"),
    [
        pytest.param(0, 1, id="no-body"),
        pytest.param(1, 1, id="a-body"),
        pytest.param(2, 0, id="neither"),
        pytest.param(255, 0, id="neither-again"),
    ],
)
def test_a_record_is_accepted_only_when_its_body_flag_says_body_or_no_body(
    body_flag: int, expected_records: int
) -> None:
    record = bytearray(match_bytes())
    record[BODY_FLAG_OFFSET] = body_flag
    _rows, stats = located(bytes(record))
    assert stats.records == expected_records


@pytest.mark.parametrize(
    ("year", "expected_records"),
    [
        pytest.param(CLOCK.year - 5, 0, id="a-year-before-the-window"),
        pytest.param(CLOCK.year - 4, 1, id="the-first-year-of-the-window"),
        pytest.param(CLOCK.year, 1, id="the-in-game-year"),
        pytest.param(CLOCK.year + 1, 1, id="the-last-year-of-the-window"),
        pytest.param(CLOCK.year + 2, 0, id="a-year-past-the-window"),
    ],
)
def test_only_matches_dated_inside_the_window_around_the_clock_are_found(
    year: int, expected_records: int
) -> None:
    _rows, stats = located(match_bytes(year=year))
    assert stats.records == expected_records


@pytest.mark.parametrize(
    ("opponent_team_id", "expected_records"),
    [
        pytest.param(0, 0, id="team-0-rejected"),
        pytest.param(1, 1, id="the-lowest-team-kept"),
        pytest.param(2_999_999, 1, id="the-highest-team-kept"),
        pytest.param(3_000_000, 0, id="past-the-highest-rejected"),
    ],
)
def test_a_record_is_accepted_only_with_an_opponent_inside_the_bounds(
    opponent_team_id: int, expected_records: int
) -> None:
    _rows, stats = located(match_bytes(opponent_team_id=opponent_team_id))
    assert stats.records == expected_records


@pytest.mark.parametrize(
    ("competition_id", "expected_records"),
    [
        pytest.param(0, 0, id="competition-0-rejected"),
        pytest.param(1, 1, id="the-lowest-competition-kept"),
        pytest.param(65_535, 1, id="the-highest-competition-kept"),
        pytest.param(65_536, 0, id="past-the-highest-rejected"),
    ],
)
def test_a_record_is_accepted_only_with_a_competition_inside_the_bounds(
    competition_id: int, expected_records: int
) -> None:
    _rows, stats = located(match_bytes(competition_id=competition_id))
    assert stats.records == expected_records


def test_a_date_that_does_not_decode_is_not_a_record() -> None:
    """Day 366 of a year that has 365 days looks like a date and is not one."""
    _rows, leap_year_stats = located(match_bytes(day_of_year=366, year=2032))
    assert leap_year_stats.records == 1
    _rows, plain_year_stats = located(match_bytes(day_of_year=366, year=2031))
    assert plain_year_stats.records == 0


def test_the_search_never_reaches_back_before_the_first_player_window() -> None:
    """A search starts where the first player's window does, so nothing before it is read."""
    window_start = PLAYER_RECORD_OFFSET - OWNER_BACK_OFFSET
    _rows, before_stats = located(match_bytes(), record_offset=window_start - 1)
    assert (before_stats.records, before_stats.unowned) == (0, 0)
    rows, at_start_stats = located(match_bytes(), record_offset=window_start)
    assert (at_start_stats.records, at_start_stats.unowned) == (1, 0)
    assert rows[0].player_uid == SYNTHETIC_FIRST_UID


def test_a_record_belonging_to_no_player_builds_no_row_and_is_counted() -> None:
    """The guard against an ownerless record matters because a position of -1 would otherwise
    read as the last player and put the match on him.
    """
    ownerless = RawMatchRecord(
        date=date(MATCH_YEAR, 2, 20),
        opponent_team_id=NORTHBRIDGE_TEAM_A,
        competition_id=FIRST_COMPETITION_ID,
        tag=0,
        has_stats=False,
        position_mask=None,
        role_code=None,
        goals=None,
        assists=None,
        left_at_minute=None,
        minutes=None,
        rating_raw=None,
        passes_attempted=None,
        passes_completed=None,
    )
    rows, stats = build_player_match_stats(
        {UNOWNED_POSITION: (ownerless,)},
        synthetic_player_records((PLAYER_RECORD_OFFSET,)),
        NO_PLAYERS,
        EXAMPLE_CLUB_INDEX,
        EXAMPLE_STAGE_INDEX,
        registered_match_layout(),
    )
    assert rows == ()
    assert stats.unowned == 1
    assert stats.records == 0
    assert stats.players_with_records == 0


def test_each_player_keeps_his_own_matches_in_stored_order() -> None:
    records = match_bytes(day_of_year=51) + match_bytes(day_of_year=44, competition_id=901)
    rows, stats = located(
        records, record_offset=MATCH_RECORD_OFFSET, player_offsets=(PLAYER_RECORD_OFFSET, 600)
    )
    assert stats.players_with_records == 1
    assert [row.competition_id for row in rows] == [FIRST_COMPETITION_ID, 901]
    assert {row.player_uid for row in rows} == {SYNTHETIC_FIRST_UID}


def test_rows_come_in_player_order() -> None:
    """Two players, the later one's match written first: rows still come player by player."""
    layout = registered_match_layout()
    player_records = synthetic_player_records((PLAYER_RECORD_OFFSET, 600))
    buffer = bytearray(1000)
    second_players_match = match_bytes(competition_id=901)
    buffer[700 : 700 + len(second_players_match)] = second_players_match
    first_players_match = match_bytes(competition_id=FIRST_COMPETITION_ID)
    buffer[400 : 400 + len(first_players_match)] = first_players_match
    rows, stats = build_player_match_stats(
        locate_match_records(bytes(buffer), player_records, layout, CLOCK),
        player_records,
        NO_PLAYERS,
        EXAMPLE_CLUB_INDEX,
        EXAMPLE_STAGE_INDEX,
        layout,
    )
    assert stats.players_with_records == 2
    assert [row.player_uid for row in rows] == [SYNTHETIC_FIRST_UID, SYNTHETIC_FIRST_UID + 1]
    assert [row.competition_id for row in rows] == [FIRST_COMPETITION_ID, 901]


def test_the_counts_the_checks_judge_come_from_the_records_themselves() -> None:
    records = (
        match_bytes(minutes=90, rating_x10=70)
        + match_bytes(played=False)
        + match_bytes(competition_id=UNLISTED_MATCH_COMPETITION_ID, minutes=200, rating_x10=120)
    )
    _rows, stats = located(records)
    assert stats == MatchStats(
        records=3,
        with_body=2,
        players_with_records=1,
        competition_in_stage_space=2,
        minutes_in_range=1,
        rating_in_range=1,
        body_valid=1,
        opponent_resolved=3,
        unowned=0,
    )


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(
    career_save_path: Path,
) -> None:
    career_save = fmsave.open(career_save_path)
    match_stats_table = career_save.player_match_stats()
    assert isinstance(match_stats_table, Table)
    assert match_stats_table.record_type is PlayerMatchStats
    assert career_save.player_match_stats() is match_stats_table
    assert PLAYER_MATCH_STATS_TABLE_CACHE_KEY == "table:player_match_stats"
    assert career_save._context._cache[PLAYER_MATCH_STATS_TABLE_CACHE_KEY] is match_stats_table
    rows_before_close = list(match_stats_table)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.player_match_stats()
    assert list(match_stats_table) == rows_before_close

    never_read_save = fmsave.open(career_save_path)
    never_read_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        never_read_save.player_match_stats()


def test_the_flat_columns_are_the_fields_with_the_coded_value_and_the_unknowns_expanded(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    assert column_names(PlayerMatchStats) == EXPECTED_COLUMNS
    assert_matches_json_normalize(list(match_rows), PlayerMatchStats)
    columns = Table(match_rows, PlayerMatchStats).to_columns()
    assert columns["position"] == ["goalkeeper", None, "unknown", "unknown"]
    assert columns["position_code"] == [FIRST_MATCH_POSITION_MASK, None, UNNAMED_POSITION_MASK, 0]
    assert columns["unknown_tag"] == [0, 0, 0, 0]
    assert columns["unknown_role_code"] == [FIRST_MATCH_ROLE_CODE, None, 0, 0]
    # Every one of these four matches carries a rating, so none of them keeps a raw copy.
    assert columns["unknown_rating_raw"] == [None, None, None, None]


def test_a_match_the_game_rated_nobody_in_carries_no_rating_and_keeps_the_stored_zero() -> None:
    """A stored zero is not a rating of 0.0, so it never sits in the column beside real ones.

    An average over the rating column is then an average of the ratings the game gave, which a
    zero standing in for "nobody was rated" would quietly drag down.
    """
    rows, _stats = located(match_bytes(rating_x10=0))
    unrated = rows[0]
    assert unrated.has_stats is True
    assert unrated.rating is None
    # Nothing is lost: the stored zero is kept where the record keeps its other raw numbers.
    assert unrated.unknown["rating_raw"] == 0
    columns = Table(rows, PlayerMatchStats).to_columns()
    assert columns["rating"] == [None]
    assert columns["unknown_rating_raw"] == [0]


def test_a_rating_the_game_gave_is_shipped_and_keeps_no_raw_copy() -> None:
    """Only the zero is kept raw, so the unknown column says exactly which matches had none."""
    rows, _stats = located(match_bytes(rating_x10=65))
    assert rows[0].rating == 6.5
    assert dict(rows[0].unknown) == {"tag": 0, "role_code": 0}


def test_a_player_on_the_pitch_at_the_end_left_at_no_minute_at_all() -> None:
    """The stored zero means he never left, so a search for early departures cannot find him."""
    records = (
        match_bytes(day_of_year=51, left_at=0)
        + match_bytes(day_of_year=44, left_at=7, minutes=7)
        + match_bytes(day_of_year=37, left_at=90)
    )
    rows, stats = located(records)
    assert stats.records == 3
    assert [row.left_at_minute for row in rows] == [None, 7, 90]
    assert all(row.has_stats for row in rows)
    early = [row for row in rows if row.left_at_minute is not None and row.left_at_minute < 10]
    assert [row.date for row in early] == [date(MATCH_YEAR, 2, 13)]
    # The minutes he played are untouched, so nothing about the match is lost with the zero.
    assert [row.minutes for row in rows] == [90, 7, 90]


def test_a_match_with_no_statistics_leaves_both_empties_meaning_something_else() -> None:
    """The two Nones are told apart by has_stats, which is false only here."""
    rows, _stats = located(match_bytes(played=False))
    without_stats = rows[0]
    assert without_stats.has_stats is False
    assert without_stats.rating is None
    assert without_stats.left_at_minute is None
    assert without_stats.stats_in_range is False
    assert dict(without_stats.unknown) == {"tag": 0}


def test_match_records_survive_pickle_and_deepcopy(
    match_rows: tuple[PlayerMatchStats, ...],
) -> None:
    match_stats_table = Table(match_rows, PlayerMatchStats)
    for example in (match_rows[0], match_rows[1], match_stats_table):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_field_statuses_follow_what_the_evidence_reaches() -> None:
    for verified_field in (
        "date",
        "competition_id",
        "opponent_team_id",
        "opponent_club_uid",
        "opponent_club_name",
        "opponent_club_short_name",
        "position",
        "goals",
    ):
        assert field_status(PlayerMatchStats, verified_field) == "verified", verified_field
    for unconfirmed_field in (
        "player_uid",
        "player_name",
        "opponent_team_slot",
        "has_stats",
        # Minutes look exactly like minutes and no displayed value pins them, which ships the
        # field but does not confirm it.
        "minutes",
        "assists",
        "left_at_minute",
        "rating",
        "passes_attempted",
        "passes_completed",
        "stats_in_range",
        "unknown",
    ):
        assert field_status(PlayerMatchStats, unconfirmed_field) == "unconfirmed", unconfirmed_field


def test_only_the_bits_a_label_reaches_are_named() -> None:
    """A bit earns a member only where a displayed label pins it, so the enum is short."""
    assert [member.name for member in MatchPosition] == ["UNKNOWN", "GOALKEEPER"]
    assert MatchPosition.UNKNOWN == -1
    # A member's value is the bit index, not the mask the record stores.
    assert MatchPosition.GOALKEEPER == 0
    assert registered_match_layout().position_bits == ((0, "GOALKEEPER"),)


def test_healthy_counts_pass_every_gate_and_a_small_section_applies_none() -> None:
    results = evaluate_player_match_stats(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == MATCH_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    small_results = evaluate_player_match_stats(healthy_stats(), BOUNDS, SMALL_GAME_DB_BYTES)
    assert all(not result.applied and result.passed for result in small_results)


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(
            dataclasses.replace(healthy_stats(), competition_in_stage_space=18_800),
            ["per_match_competition_in_stage_space"],
            id="competitions-outside-the-stage-table",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), minutes_in_range=11_760),
            ["per_match_minutes_in_range"],
            id="minutes-past-their-bound",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), rating_in_range=11_760),
            ["per_match_rating_in_range"],
            id="ratings-past-their-bound",
        ),
        pytest.param(
            MatchStats(0, 0, 0, 0, 0, 0, 0, 0, 0),
            list(MATCH_GATE_NAMES),
            id="a-search-that-found-nothing",
        ),
    ],
)
def test_the_gates_fail_one_at_a_time_when_their_counts_are_driven_past_their_bounds(
    stats: MatchStats, expected_failures: Sequence[str]
) -> None:
    """Each gate fails on its own count, and a search that found nothing fails all three rather
    than passing for want of a rate.
    """
    results = evaluate_player_match_stats(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == list(expected_failures)
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("player_match_stats", results, strict=True)
    assert str(error_info.value).startswith("player_match_stats failed checks: ")
    assert expected_failures[0] in str(error_info.value)


@pytest.mark.parametrize(
    ("observed", "bound_name", "passes"),
    [
        pytest.param(0.95, "per_match_competition_in_stage_space", True, id="at-the-floor"),
        pytest.param(0.94, "per_match_competition_in_stage_space", False, id="below-the-floor"),
        pytest.param(0.99, "per_match_minutes_in_range", True, id="minutes-at-the-floor"),
        pytest.param(0.98, "per_match_minutes_in_range", False, id="minutes-below-the-floor"),
        pytest.param(0.99, "per_match_rating_in_range", True, id="rating-at-the-floor"),
        pytest.param(0.98, "per_match_rating_in_range", False, id="rating-below-the-floor"),
    ],
)
def test_each_bound_passes_at_its_floor_and_fails_just_below_it(
    observed: float, bound_name: str, passes: bool
) -> None:
    """The bounds are where the layout says they are, from both sides."""
    records = 10_000
    with_body = 10_000
    counts = {
        "per_match_competition_in_stage_space": {
            "competition_in_stage_space": round(observed * records)
        },
        "per_match_minutes_in_range": {"minutes_in_range": round(observed * with_body)},
        "per_match_rating_in_range": {"rating_in_range": round(observed * with_body)},
    }[bound_name]
    stats = dataclasses.replace(
        MatchStats(
            records=records,
            with_body=with_body,
            players_with_records=500,
            competition_in_stage_space=records,
            minutes_in_range=with_body,
            rating_in_range=with_body,
            body_valid=with_body,
            opponent_resolved=records,
            unowned=0,
        ),
        **counts,
    )
    results = evaluate_player_match_stats(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert (bound_name not in failed_gate_names(results)) is passes


def bounds_only_this_reader_can_fail(
    **per_match_bounds: tuple[float | None, float | None],
) -> GateBounds:
    """The registered bounds with every check applied and only the per-match ones bounded.

    Every other reader's bounds are opened, so a save this small cannot fail one of theirs, and
    what the per-match reader does with its own counts is all that is left to decide the call.
    """
    opened: dict[str, tuple[float | None, float | None]] = {
        bound_field.name: (None, None)
        for bound_field in dataclasses.fields(GateBounds)
        if bound_field.type == "BoundPair"
    }
    opened.update(per_match_bounds)
    return dataclasses.replace(
        BOUNDS, minimum_applies_from_bytes=0, span_minimum_applies_from_bytes=0, **opened
    )


def test_the_reader_raises_when_its_counts_are_past_its_bounds_and_returns_its_table_when_not(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The example career's four matches fail bounds their own counts miss and pass bounds they
    meet, so every gate is shown failing and passing on one and the same save.
    """
    unmeetable_bounds = bounds_only_this_reader_can_fail(
        per_match_competition_in_stage_space=(0.95, None),
        per_match_minutes_in_range=(0.99, None),
        per_match_rating_in_range=(0.99, None),
    )
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: unmeetable_bounds)
    with fmsave.open(career_save_path, strict=True) as career_save:
        with pytest.raises(fmsave.ReaderCheckError) as error_info:
            career_save.player_match_stats()
        # Remembered as failed, and so never handed out as a table.
        assert career_save._context.cached_value(PLAYER_MATCH_STATS_TABLE_CACHE_KEY) is None
    message = str(error_info.value)
    assert message.startswith("player_match_stats failed checks: ")
    for gate_name in MATCH_GATE_NAMES:
        assert gate_name in message

    meetable_bounds = bounds_only_this_reader_can_fail(
        per_match_competition_in_stage_space=(0.70, None),
        per_match_minutes_in_range=(0.60, None),
        per_match_rating_in_range=(0.60, None),
    )
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: meetable_bounds)
    with fmsave.open(career_save_path) as career_save:
        assert len(career_save.player_match_stats()) == PLAYER_A_MATCH_COUNT


def test_the_record_count_and_anomalies_reach_the_reader_check() -> None:
    reader_check = check_player_match_stats(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert reader_check.reader == "player_match_stats"
    assert reader_check.record_count == 20_000
    assert dict(reader_check.anomalies) == {
        "records_without_a_body": 8_000,
        "unresolved_opponents": 10,
        "competitions_outside_the_stage_table": 0,
        "bodies_outside_their_ranges": 0,
        "records_without_an_owner": 0,
    }


@pytest.mark.parametrize(
    ("layout_changes", "message"),
    [
        pytest.param(
            {"lead_byte_offset": 1}, "must start a record", id="a-lead-byte-past-the-start"
        ),
        pytest.param(
            {"position_mask_offset": 14},
            "starts inside the 15-byte header",
            id="a-body-field-inside-the-header",
        ),
        pytest.param(
            {"passes_completed_offset": 43},
            "ends past the 43-byte record",
            id="a-body-field-past-the-record",
        ),
        pytest.param(
            {"header_bytes": 43}, "must be shorter than", id="a-header-as-long-as-the-record"
        ),
        pytest.param(
            {"date_offset": 12}, "ends past the 15-byte header", id="a-date-past-the-header"
        ),
        pytest.param({"date_offset": 0}, "must follow the lead byte", id="a-date-on-the-lead-byte"),
        pytest.param(
            {"competition_id_offset": 12},
            "ends past the 15-byte header",
            id="a-header-field-past-the-header",
        ),
        pytest.param(
            {"years_before_clock": 400},
            "do not share one high byte",
            id="a-window-spanning-two-high-bytes",
        ),
        pytest.param({"team_id_range": (10, 1)}, "leaves no team id", id="an-inverted-team-range"),
        pytest.param(
            {"competition_id_range": (10, 1)},
            "leaves no competition id",
            id="an-inverted-competition-range",
        ),
    ],
)
def test_locate_match_records_rejects_an_inconsistent_layout(
    layout_changes: dict[str, object], message: str
) -> None:
    broken_layout = dataclasses.replace(registered_match_layout(), **layout_changes)
    with pytest.raises(ValueError, match=message):
        locate_match_records(bytes(100), synthetic_player_records((50,)), broken_layout, CLOCK)


@pytest.mark.parametrize(
    ("position_bits", "message"),
    [
        pytest.param(((16, "GOALKEEPER"),), "outside the 16-bit", id="a-bit-past-the-mask"),
        pytest.param(((-1, "GOALKEEPER"),), "outside the 16-bit", id="a-bit-before-the-mask"),
        pytest.param(((0, "GOALKEEPER"), (0, "GOALKEEPER")), "named twice", id="a-bit-named-twice"),
        pytest.param(((1, "SWEEPER"),), "not a MatchPosition member", id="a-name-with-no-member"),
    ],
)
def test_a_position_bit_must_name_a_member_of_the_position_enum(
    position_bits: tuple[tuple[int, str], ...], message: str
) -> None:
    broken_layout = dataclasses.replace(registered_match_layout(), position_bits=position_bits)
    with pytest.raises(ValueError, match=message):
        build_player_match_stats(
            {},
            synthetic_player_records((PLAYER_RECORD_OFFSET,)),
            NO_PLAYERS,
            EXAMPLE_CLUB_INDEX,
            EXAMPLE_STAGE_INDEX,
            broken_layout,
        )
