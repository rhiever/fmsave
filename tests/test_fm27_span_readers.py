"""The registered FM27 span layouts, on fictional fragments built with literal offsets."""

from __future__ import annotations

import struct
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._errors import ReaderCheckError
from fmsave._layouts import GateBounds, find_layout
from fmsave.models.fixtures import Fixture
from fmsave.readers.span import SpanRecords, find_span_layouts, scan_span
from fmsave.table import Table
from tests.fixtures.container import packed_date
from tests.fixtures.span import table_block_bytes
from tests.test_fm27_experimental import BUILD, fm27_fragment

CLOCK = date(2032, 7, 1)
YEAR = 2032


def calendar_record(
    *,
    home: int,
    away: int,
    stage: int = 4101,
    stadium_ordinal: int = 11,
    day_of_year: int = 200,
    season: int = 2032,
    match_record: int = 880_001,
    phase: int = 1,
    leg: int = 2,
    round_index: int = 3,
    template: tuple[int, int, int] = (7, 8, 9),
) -> bytes:
    """One 12-byte lead-in and the 53 bytes from the home id up to the result prefix."""
    lead_in = bytearray(12)
    lead_in[0] = 0x1F
    struct.pack_into("<II", lead_in, 1, stage, stadium_ordinal + 1)
    core = bytearray(53)
    struct.pack_into("<I", core, 0, home)
    core[4] = 0xFF
    struct.pack_into("<I", core, 7, away)
    core[11] = 0xFF
    core[13:17] = packed_date(day_of_year, YEAR, 60)
    core[17:21] = packed_date(day_of_year, YEAR)
    core[21] = 0xFF
    struct.pack_into("<H", core, 22, season)
    struct.pack_into("<I", core, 28, match_record)
    core[32], core[33], core[34] = phase, leg, round_index
    core[39:42] = bytes(template)
    core[51:53] = b"\x5a\x5a"  # Undecoded, and never read as the result prefix.
    return bytes(lead_in) + bytes(core)


def result_packet(home_goals: int, away_goals: int, events: int = 1) -> bytes:
    packet = bytearray(29 + 16 * events)
    packet[0] = 0x1F
    packet[5], packet[9] = home_goals, away_goals
    packet[6] = packet[10] = 0xFF
    struct.pack_into("<I", packet, 25, events)
    return bytes(packet)


def calendar() -> bytes:
    """Three records: the second one played 3-1, the third one not yet played."""
    return (
        bytes(64)
        + calendar_record(home=70001, away=70002)
        + b"\x01"
        + result_packet(3, 1)
        + calendar_record(home=70003, away=70004, round_index=4)
        + b"\x00"
        + calendar_record(home=70005, away=70006, round_index=5)
        + b"\x00"
        + bytes(64)
    )


def scan(payload: bytes) -> SpanRecords:
    return scan_span([payload], find_span_layouts(BUILD), CLOCK, "example.fm")


def test_fm27_calendar_fields_come_from_their_own_offsets() -> None:
    records = scan(calendar())

    first, second, third = records.fixtures
    assert (first.home_team_id, first.away_team_id) == (70001, 70002)
    assert (first.stage_id, first.stadium_ordinal) == (4101, 11)
    assert (first.kick_off_year, first.season_start_year) == (YEAR, 2032)
    assert first.match_record_id == 880_001
    assert (first.phase, first.leg, first.round_index) == (1, 2, 3)
    assert first.match_rules_template == (7, 8, 9)
    assert (second.round_index, third.round_index) == (4, 5)
    fm26 = find_span_layouts("26.3.2+2329565")
    assert scan_span([calendar()], fm26, CLOCK, "example.fm").fixtures == ()


def test_fm27_result_prefix_belongs_to_the_following_record() -> None:
    records = scan(calendar())

    _, second, third = records.fixtures
    presence = {row.span_offset: row.played for row in records.fixture_presence}
    assert presence == {second.span_offset: True, third.span_offset: False}
    (score,) = records.fixture_scores
    assert (score.span_offset, score.home_goals, score.away_goals) == (second.span_offset, 3, 1)


def summary_block(*, flag: int, played: int = 4) -> bytes:
    """A block whose last aggregate byte is the match-row flag; a summary follows a 0."""
    blob = bytearray(
        table_block_bytes(
            team_id=70001,
            rounds_per_venue=1,
            total={"played": played, "won": played, "points": 3 * played},
            home={"played": played // 2},
            away={"played": played - played // 2},
            first_half={"played": played // 2},
            second_half={"played": played - played // 2, "flag": flag},
            matches=[None, None],
        )
    )
    struct.pack_into("<H", blob, 23 + 85, 0x0203)
    return bytes(blob)


def test_fm27_table_block_without_match_rows_keeps_its_aggregates() -> None:
    (block,) = scan(bytes(64) + summary_block(flag=0) + bytes(64)).table_blocks

    assert block.team_id == 70001
    assert block.rounds_per_venue is None
    assert block.matches == ()
    assert (block.aggregates[0].played, block.aggregates[0].points) == (4, 12)


def test_fm27_table_aggregates_may_count_results_short_of_played() -> None:
    shortfall = table_block_bytes(
        team_id=70001,
        rounds_per_venue=2,
        total={"played": 2, "won": 1, "drawn": 0, "lost": 0, "points": 4},
        home={"played": 1, "won": 1, "drawn": 0, "lost": 0},
        away={"played": 1, "won": 0, "drawn": 0, "lost": 0},
        first_half={"played": 2, "won": 1, "drawn": 0, "lost": 0},
        second_half={"played": 0, "flag": 1},
        matches=[None] * 4,
    )

    (block,) = scan(bytes(64) + shortfall + bytes(64)).table_blocks
    assert (block.aggregates[0].played, block.aggregates[0].won) == (2, 1)
    assert block.rounds_per_venue == 2


def rules_block() -> bytes:
    """A doubled quad, twenty bytes, the marker, then lists and three 21-byte rounds."""
    quad = bytes((2, 1, 0, 3))
    output = bytearray(quad + quad + bytes(20) + bytes.fromhex("ffff000001ffffff00"))
    output += struct.pack("<I", 3) + bytes((0, 1, 3))
    output += struct.pack("<I", 2) + struct.pack("<II", 5_000_000, 2_500_000)
    output += struct.pack("<I", 3)
    for ordinal in range(3):
        if ordinal == 2:
            output += b"\xff" * 4 + bytes(6)
        row = bytearray(21)
        row[1:5] = packed_date(220 + 7 * ordinal, YEAR)
        row[6] = ordinal
        row[7], row[8] = 1, 0xFF
        struct.pack_into("<I", row, 9, 10)
        row[13], row[14] = ordinal, 0xFF
        row[16:20] = packed_date(1, 1900)
        output += row[1:] if ordinal == 0 else row
    return bytes(output)


def test_fm27_rules_block_reads_its_quad_lists_and_rounds() -> None:
    (block,) = scan(bytes(64) + rules_block() + bytes(64)).rules_blocks

    assert (block.promotion_places, block.playoff_places, block.relegation_places) == (2, 1, 3)
    assert block.tie_breaks == (0, 1, 3)
    assert block.prize_money == (5_000_000, 2_500_000)
    assert [round_row.number for round_row in block.rounds] == [1, 2, 3]
    assert [round_row.match_count for round_row in block.rounds] == [10, 10, 10]
    assert block.fully_parsed


def test_fm27_needs_fewer_table_blocks_than_fm26() -> None:
    fm27 = find_layout(GateBounds, "game_db", 4000, BUILD).layout
    fm26 = find_layout(GateBounds, "game_db", 4000, "26.3.2+2329565").layout

    assert fm27.table_blocks_minimum == (120, None)
    assert fm26.table_blocks_minimum == (200, None)


def test_fm27_stadiums_take_no_home_grounds_from_a_calendar_that_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(_save: fmsave.Save) -> Table[Fixture]:
        raise ReaderCheckError("fictional calendar failure")

    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(fm27_fragment(tmp_path))
    with save:
        monkeypatch.setattr(fmsave.Save, "fixtures", failing)
        assert save._fm27_home_ground_calendar() is None
        empty = Table((), Fixture)
        monkeypatch.setattr(fmsave.Save, "fixtures", lambda _save: empty)
        assert save._fm27_home_ground_calendar() is empty
