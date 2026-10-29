from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave.readers.span import SpanLayouts, SpanRecords, find_span_layouts, scan_span
from tests.fixtures.container import SectionFrame, build_container_fragment, default_sections
from tests.fixtures.span import (
    UNPLAYED_KEY,
    fixture_record_bytes,
    moved_match_bytes,
    rules_preamble_bytes,
    span_frames,
    span_payloads,
    stage_result_bytes,
    table_block_bytes,
)

FILE_NAME = "career example.fm"
BUILD = "26.3.2+2329565"
CLOCK = date(2031, 3, 1)
SEPARATOR_BYTES = 1000

# The 0x1C locator byte sits at index 0 of a built fixture blob and the record starts at 12.
FIXTURE_MARKER_INDEX = 0
FIXTURE_RECORD_INDEX = 12
FIXTURE_BLOB_BYTES = 80
HOME_TEAM_IDS = (70001, 70003, 70005)
AWAY_TEAM_IDS = (70002, 70004, 70006)
STAGE_IDS = (4101, 4102, 4103)
STADIUM_ORDINALS = (11, 12, 13)
ROUND_INDEXES = (0, 1, 255)
PLAYED_FLAGS = (True, True, False)
KICK_OFF_DAY = 51
KICK_OFF_YEAR = 2031
KICK_OFF_SLOT = 34
SEASON_START_YEAR = 2030

NORTHBRIDGE_TEAM_ID = 70001

# A block head sits 23 bytes into a built block, its match rows 87 bytes after the head, and
# a 40-round block is 23 + 87 + 17 * 2 * 40 bytes long.
TABLE_HEAD_INDEX = 23
TABLE_MATCHES_OFFSET = 87
FULL_SEASON_ROUNDS = 40
FULL_SEASON_BLOCK_BYTES = 1470

# A stage-keyed result record: 27 bytes carrying one match's score.
RESULT_STAGE_ID = 4101
RESULT_HOME_TEAM_ID = 70001
RESULT_AWAY_TEAM_ID = 70003
RESULT_DAY = 51
RESULT_YEAR = 2031
RESULT_HOME_GOALS = 2
RESULT_AWAY_GOALS = 1
RESULT_R22 = 0x5A
RESULT_RECORD_BYTES = 27


def span_layouts() -> SpanLayouts:
    return find_span_layouts(BUILD)


def scan(frames: Sequence[bytes]) -> SpanRecords:
    return scan_span(frames, span_layouts(), CLOCK, FILE_NAME)


def example_fixture_blob(
    position: int,
    *,
    year: int = KICK_OFF_YEAR,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
) -> bytes:
    return fixture_record_bytes(
        stage_id=STAGE_IDS[position],
        stadium_ordinal=STADIUM_ORDINALS[position],
        home_team_id=HOME_TEAM_IDS[position] if home_team_id is None else home_team_id,
        away_team_id=AWAY_TEAM_IDS[position] if away_team_id is None else away_team_id,
        day_of_year=KICK_OFF_DAY,
        year=year,
        time_slot=KICK_OFF_SLOT,
        season_start_year=SEASON_START_YEAR,
        match_record_id=880000 + position,
        round_index=ROUND_INDEXES[position],
        played=PLAYED_FLAGS[position],
    )


def three_fixture_payload() -> bytes:
    return span_payloads(
        *(example_fixture_blob(position) for position in range(3)),
        separator_bytes=SEPARATOR_BYTES,
    )


def example_table_block(
    *,
    team_id: int = NORTHBRIDGE_TEAM_ID,
    rounds_per_venue: int = 2,
    total: Mapping[str, int] | None = None,
    home: Mapping[str, int] | None = None,
    away: Mapping[str, int] | None = None,
    first_half: Mapping[str, int] | None = None,
    second_half: Mapping[str, int] | None = None,
    matches: Sequence[Mapping[str, int] | None] | None = None,
) -> bytes:
    default_matches: tuple[Mapping[str, int] | None, ...] = (
        {"key": 70002, "played": 1, "won": 1, "goals_for": 3, "goals_against": 1, "points": 3},
        None,
        {"key": 70004, "played": 1, "drawn": 1, "goals_for": 2, "goals_against": 2, "points": 1},
        None,
    )
    return table_block_bytes(
        team_id=team_id,
        rounds_per_venue=rounds_per_venue,
        total={
            "played": 4,
            "won": 2,
            "drawn": 1,
            "lost": 1,
            "goals_for": 7,
            "goals_against": 5,
            "points": 7,
        }
        if total is None
        else total,
        home={"played": 2, "won": 2, "drawn": 0, "lost": 0} if home is None else home,
        away={"played": 2, "won": 0, "drawn": 1, "lost": 1} if away is None else away,
        first_half={"played": 2} if first_half is None else first_half,
        second_half={"played": 2} if second_half is None else second_half,
        matches=default_matches if matches is None else matches,
    )


def unplayed_slots_table_block() -> bytes:
    """A whole-season block whose first five match slots are unplayed.

    Five unplayed slots in a row are five unplayed keys 17 bytes apart, so the block's own
    match rows hold a second candidate head; real saves carry this shape constantly.
    """
    match_slots: list[Mapping[str, int] | None] = [None] * (2 * FULL_SEASON_ROUNDS)
    match_slots[5] = {
        "key": 70002,
        "played": 1,
        "won": 1,
        "goals_for": 3,
        "goals_against": 1,
        "points": 3,
    }
    return example_table_block(rounds_per_venue=FULL_SEASON_ROUNDS, matches=match_slots)


def example_result_record(**overrides: int) -> bytes:
    """One sound result record, with any field overridden."""
    fields: dict[str, int] = {
        "stage_id": RESULT_STAGE_ID,
        "home_team_id": RESULT_HOME_TEAM_ID,
        "away_team_id": RESULT_AWAY_TEAM_ID,
        "day_of_year": RESULT_DAY,
        "year": RESULT_YEAR,
        "home_goals": RESULT_HOME_GOALS,
        "away_goals": RESULT_AWAY_GOALS,
        "r22": RESULT_R22,
    }
    fields.update(overrides)
    return stage_result_bytes(**fields)


def example_rules_block(
    *,
    double_quad: bool = True,
    round_count: int = 3,
    moved_matches_after_first_round: int = 0,
) -> bytes:
    return rules_preamble_bytes(
        promotion=2,
        playoff=4,
        promotion_byte2=1,
        relegation=3,
        tie_breaks=(1, 5, 9),
        prize_money=(1_000_000, 500_000, 250_000),
        rounds=[
            {"day_of_year": 220 + index, "year": 2030, "match_count": 10}
            for index in range(round_count)
        ],
        double_quad=double_quad,
        moved_matches_after_first_round=moved_matches_after_first_round,
    )


# Fixtures


def test_one_frame_of_three_fixture_records_decodes_in_region_order() -> None:
    records = scan([three_fixture_payload()])

    assert len(records.fixtures) == 3
    first_fixture, second_fixture, third_fixture = records.fixtures
    assert [fixture.span_offset for fixture in records.fixtures] == [
        FIXTURE_RECORD_INDEX,
        FIXTURE_BLOB_BYTES + SEPARATOR_BYTES + FIXTURE_RECORD_INDEX,
        2 * (FIXTURE_BLOB_BYTES + SEPARATOR_BYTES) + FIXTURE_RECORD_INDEX,
    ]
    assert first_fixture.stage_id == STAGE_IDS[0]
    assert first_fixture.home_team_id == HOME_TEAM_IDS[0]
    assert first_fixture.away_team_id == AWAY_TEAM_IDS[0]
    # The save stores the ordinal plus one, so the record reads one less than it holds.
    assert first_fixture.stadium_ordinal == STADIUM_ORDINALS[0]
    assert first_fixture.kick_off_year == KICK_OFF_YEAR
    assert first_fixture.packed_kick_off == KICK_OFF_DAY | KICK_OFF_SLOT << 9
    assert first_fixture.season_start_year == SEASON_START_YEAR
    assert first_fixture.match_record_id == 880000
    assert first_fixture.round_index == 0
    assert first_fixture.played is True
    assert first_fixture.phase == 2
    assert first_fixture.leg == 1
    assert first_fixture.match_rules_template == (7, 8, 9)
    assert second_fixture.stage_id == STAGE_IDS[1]
    assert third_fixture.round_index == 255
    assert third_fixture.played is False


def test_a_kick_off_year_outside_the_clock_window_is_not_found() -> None:
    records = scan([example_fixture_blob(0, year=CLOCK.year + 9)])

    assert records.fixtures == ()


def test_a_clock_window_that_crosses_a_high_byte_finds_kick_off_years_on_both_sides() -> None:
    """2047 is 0x07FF and 2048 is 0x0800, so the window around 2040 spans two high bytes."""
    payload = span_payloads(
        example_fixture_blob(0, year=2047),
        example_fixture_blob(1, year=2048),
        example_fixture_blob(2, year=2049),
        separator_bytes=SEPARATOR_BYTES,
    )

    records = scan_span([payload], span_layouts(), date(2040, 12, 1), FILE_NAME)

    assert [fixture.kick_off_year for fixture in records.fixtures] == [2047, 2048]


@pytest.mark.parametrize(
    ("home_team_id", "away_team_id"),
    [
        pytest.param(3_000_000, AWAY_TEAM_IDS[0], id="home-team-id-above-the-range"),
        pytest.param(HOME_TEAM_IDS[0], 3_000_000, id="away-team-id-above-the-range"),
    ],
)
def test_a_team_id_outside_the_range_is_not_accepted(home_team_id: int, away_team_id: int) -> None:
    blob = example_fixture_blob(0, home_team_id=home_team_id, away_team_id=away_team_id)

    records = scan([blob])

    assert records.fixtures == ()
    assert records.fixture_candidates > 0


@pytest.mark.parametrize(
    ("home_team_id", "away_team_id"),
    [
        pytest.param(0, AWAY_TEAM_IDS[0], id="home-team-0"),
        pytest.param(HOME_TEAM_IDS[0], 0, id="away-team-0"),
    ],
)
def test_team_0_is_a_fixture_team_like_any_other(home_team_id: int, away_team_id: int) -> None:
    blob = example_fixture_blob(0, home_team_id=home_team_id, away_team_id=away_team_id)

    records = scan([blob])

    assert [(f.home_team_id, f.away_team_id) for f in records.fixtures] == [
        (home_team_id, away_team_id)
    ]


def test_a_result_for_team_0_is_kept() -> None:
    records = scan([example_result_record(home_team_id=0)])

    assert [result.home_team_id for result in records.results] == [0]


def test_a_wrong_locator_byte_is_not_accepted() -> None:
    blob = bytearray(example_fixture_blob(0))
    blob[FIXTURE_MARKER_INDEX] = 0x1D

    records = scan([bytes(blob)])

    assert records.fixtures == ()
    assert records.fixture_candidates > 0


# Frame straddling


def test_a_record_straddling_a_frame_boundary_is_found_exactly_once() -> None:
    payload = three_fixture_payload()
    second_record_start = FIXTURE_BLOB_BYTES + SEPARATOR_BYTES + FIXTURE_RECORD_INDEX
    split_at = second_record_start + 30

    records = scan([payload[:split_at], payload[split_at:]])

    assert len(records.fixtures) == 3
    span_offsets = [fixture.span_offset for fixture in records.fixtures]
    assert span_offsets == sorted(span_offsets)
    assert len(set(span_offsets)) == 3


def test_a_record_lying_inside_the_carry_is_emitted_once() -> None:
    payload = three_fixture_payload()
    split_at = 2 * (FIXTURE_BLOB_BYTES + SEPARATOR_BYTES)

    records = scan([payload[:split_at], payload[split_at:]])

    assert len(records.fixtures) == 3
    span_offsets = [fixture.span_offset for fixture in records.fixtures]
    assert len(set(span_offsets)) == 3


# League-table blocks


def test_one_league_table_block_decodes_with_its_aggregates_and_match_rows() -> None:
    records = scan([example_table_block()])

    assert len(records.table_blocks) == 1
    block = records.table_blocks[0]
    assert block.team_id == NORTHBRIDGE_TEAM_ID
    assert block.head_bytes == tuple(range(19))
    assert block.rounds_per_venue == 2
    assert len(block.aggregates) == 5
    total_row, home_row, away_row, first_half_row, second_half_row = block.aggregates
    assert (total_row.played, total_row.won, total_row.drawn, total_row.lost) == (4, 2, 1, 1)
    assert (total_row.goals_for, total_row.goals_against, total_row.points) == (7, 5, 7)
    assert home_row.played == 2
    assert away_row.played == 2
    assert first_half_row.played == 2
    assert second_half_row.played == 2
    assert len(block.matches) == 4
    assert block.matches[0].key == 70002
    assert block.matches[1].key == UNPLAYED_KEY
    assert block.matches[2].key == 70004
    assert block.matches[3].key == UNPLAYED_KEY


def test_a_block_whose_home_and_away_do_not_add_up_is_rejected() -> None:
    block = example_table_block(
        home={"played": 1, "won": 1, "drawn": 0, "lost": 0},
        away={"played": 2, "won": 0, "drawn": 1, "lost": 1},
    )

    records = scan([block])

    assert records.table_blocks == ()
    assert records.table_block_candidates > 0


def test_a_block_with_too_many_rounds_per_venue_is_rejected() -> None:
    block = example_table_block(
        rounds_per_venue=41,
        total={"played": 0, "won": 0, "drawn": 0, "lost": 0},
        home={"played": 0},
        away={"played": 0},
        first_half={"played": 0},
        second_half={"played": 0},
        matches=[None] * 82,
    )

    records = scan([block])

    assert records.table_blocks == ()
    assert records.table_block_candidates > 0


def test_a_block_whose_total_row_played_nothing_is_rejected() -> None:
    block = example_table_block(
        total={"played": 0, "won": 0, "drawn": 0, "lost": 0},
        home={"played": 0},
        away={"played": 0},
        first_half={"played": 0},
        second_half={"played": 0},
        matches=[None, None, None, None],
    )

    records = scan([block])

    assert records.table_blocks == ()
    assert records.table_block_candidates > 0


def test_a_deferred_block_is_not_hidden_by_a_later_candidate_in_the_same_window() -> None:
    """A block whose first five match slots are unplayed carries a second candidate head
    inside its own match rows, because five unplayed slots are five unplayed keys 17 bytes
    apart. When the block itself does not fit in a window, that inner candidate must not be
    judged ahead of it, or the block is skipped in the next window and lost for good.
    """
    block = unplayed_slots_table_block()
    assert len(block) == FULL_SEASON_BLOCK_BYTES
    # The inner candidate head really is there: the first match row holds the unplayed key.
    inner_head = TABLE_HEAD_INDEX + TABLE_MATCHES_OFFSET
    assert block[inner_head : inner_head + 4] == b"\xff\xff\xff\xff"

    for split_at in (120, 200, 400, 800, 1200):
        records = scan([block[:split_at], block[split_at:]])

        assert len(records.table_blocks) == 1, split_at
        assert records.table_blocks[0].rounds_per_venue == FULL_SEASON_ROUNDS, split_at
        assert records.table_blocks[0].span_offset == TABLE_HEAD_INDEX, split_at


def test_a_block_whose_first_half_counters_do_not_add_up_is_rejected() -> None:
    block = example_table_block(first_half={"played": 2, "won": 0, "drawn": 0, "lost": 0})

    records = scan([block])

    assert records.table_blocks == ()
    assert records.table_block_candidates > 0


# Competition-rules preambles


def test_one_rules_preamble_decodes_its_quad_lists_and_rounds() -> None:
    records = scan([example_rules_block()])

    assert len(records.rules_blocks) == 1
    block = records.rules_blocks[0]
    assert block.promotion_places == 2
    assert block.playoff_places == 4
    assert block.promotion_byte2 == 1
    assert block.relegation_places == 3
    assert block.tie_breaks == (1, 5, 9)
    assert block.prize_money == (1_000_000, 500_000, 250_000)
    assert len(block.rounds) == 3
    assert block.rounds[0].number == 1
    assert block.rounds[0].date == date(2030, 8, 8)
    assert block.rounds[0].match_count == 10
    assert [round_record.number for round_record in block.rounds] == [1, 2, 3]
    assert block.fully_parsed is True


def test_a_rules_preamble_whose_quad_is_not_doubled_keeps_its_lists() -> None:
    records = scan([example_rules_block(double_quad=False)])

    assert len(records.rules_blocks) == 1
    block = records.rules_blocks[0]
    assert block.promotion_places is None
    assert block.playoff_places is None
    assert block.promotion_byte2 is None
    assert block.relegation_places is None
    assert block.tie_breaks == (1, 5, 9)
    assert block.prize_money == (1_000_000, 500_000, 250_000)
    assert block.fully_parsed is False


def test_a_rules_preamble_with_too_many_rounds_keeps_no_rounds() -> None:
    records = scan([example_rules_block(round_count=81)])

    assert len(records.rules_blocks) == 1
    block = records.rules_blocks[0]
    assert block.rounds == ()
    assert block.fully_parsed is False
    assert records.rules_markers == 1


def test_round_records_are_read_across_the_moved_match_blocks_between_them() -> None:
    records = scan([example_rules_block(moved_matches_after_first_round=2)])

    assert len(records.rules_blocks) == 1
    block = records.rules_blocks[0]
    assert [round_record.number for round_record in block.rounds] == [1, 2, 3]
    assert [round_record.date for round_record in block.rounds] == [
        date(2030, 8, 8),
        date(2030, 8, 9),
        date(2030, 8, 10),
    ]
    assert block.fully_parsed is True


def tagged_interstitial_block(*, interstitial: bytes, count: int = 2) -> bytes:
    return example_rules_block(moved_matches_after_first_round=count).replace(
        moved_match_bytes(), interstitial
    )


def test_tagged_interstitials_preserve_rounds_without_interpreting_the_payload() -> None:
    interstitial = b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4
    records = scan([tagged_interstitial_block(interstitial=interstitial)])
    block = records.rules_blocks[0]
    assert [row.number for row in block.rounds] == [1, 2, 3]
    assert [row.match_count for row in block.rounds] == [10, 10, 10]
    assert block.fully_parsed


@pytest.mark.parametrize("changed_offset", [0, 6, 7, 8, 9])
def test_tagged_interstitials_require_the_tag_and_every_tail_byte(changed_offset: int) -> None:
    interstitial = bytearray(b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4)
    interstitial[changed_offset] = 2
    block = scan([tagged_interstitial_block(interstitial=bytes(interstitial))]).rules_blocks[0]
    assert len(block.rounds) == 1
    assert not block.fully_parsed


@pytest.mark.parametrize(("offset", "value"), [(9, 256), (1, 0)])
def test_tagged_interstitials_require_a_complete_calendar_without_raising_count_limits(
    offset: int, value: int
) -> None:
    data = bytearray(
        tagged_interstitial_block(interstitial=b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4)
    )
    # The indexed retry also needs every ordinal. An invalid date or an oversized raw word
    # accompanied by a corrupt ordinal must preserve the original one-round prefix.
    struct.pack_into("<I", data, len(data) - 15 + offset, value)
    if offset == 9:
        data[-2] = 0xFF
    block = scan([bytes(data)]).rules_blocks[0]
    assert len(block.rounds) == 1
    assert not block.fully_parsed


def test_tagged_interstitials_keep_the_per_round_bound() -> None:
    data = tagged_interstitial_block(
        interstitial=b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4, count=65
    )
    block = scan([data]).rules_blocks[0]
    assert len(block.rounds) == 1
    assert not block.fully_parsed


def indexed_rules_block(*, word: int = 256, tagged_interstitial: bool = False) -> bytes:
    data = bytearray(example_rules_block())
    struct.pack_into("<I", data, len(data) - 30 + 9, word)
    if tagged_interstitial:
        start = len(data) - 30
        data[start:start] = b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4
    return bytes(data)


@pytest.mark.parametrize("word", [72, 128, 136, 256, 264, 8192, 65536, 0xFFFFFFFF])
@pytest.mark.parametrize("tagged_interstitial", [False, True])
def test_complete_indexed_calendars_preserve_large_raw_words(
    word: int, tagged_interstitial: bool
) -> None:
    block = scan(
        [indexed_rules_block(word=word, tagged_interstitial=tagged_interstitial)]
    ).rules_blocks[0]
    assert block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10, word, 10]
    assert [row.date for row in block.rounds] == [
        date(2030, 8, 8),
        date(2030, 8, 9),
        date(2030, 8, 10),
    ]


@pytest.mark.parametrize(
    ("row_index", "offset", "value"),
    [(0, 13, 1), (1, 13, 0xFF), (2, 13, 1), (1, 0, 1), (2, 0, 1)],
)
def test_indexed_calendar_requires_every_parent_ordinal_and_kind(
    row_index: int, offset: int, value: int
) -> None:
    data = bytearray(indexed_rules_block())
    data[len(data) - 45 + 15 * row_index + offset] = value
    block = scan([bytes(data)]).rules_blocks[0]
    assert not block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10]
    assert block.rounds[0].date == date(2030, 8, 8)


def test_indexed_calendar_invalid_later_date_keeps_the_original_prefix() -> None:
    data = bytearray(indexed_rules_block())
    data[-14:-10] = bytes(4)
    block = scan([bytes(data)]).rules_blocks[0]
    assert not block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10]


@pytest.mark.parametrize("missing_bytes", [1, 2, 6, 14, 15])
def test_incomplete_indexed_calendar_keeps_the_original_prefix(missing_bytes: int) -> None:
    block = scan([indexed_rules_block()[:-missing_bytes]]).rules_blocks[0]
    assert not block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10]


def test_legacy_calendar_keeps_rows_without_parent_ordinals() -> None:
    data = bytearray(example_rules_block())
    data[-2] = 0xFF
    block = scan([bytes(data)]).rules_blocks[0]
    assert block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10, 10, 10]


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("missing_from_first_frame", [1, 7, 14, 20, 31])
def test_complete_calendar_retries_wait_for_the_following_frame(
    indexed: bool, missing_from_first_frame: int
) -> None:
    data = (
        indexed_rules_block(tagged_interstitial=True)
        if indexed
        else tagged_interstitial_block(interstitial=b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4)
    )
    unsplit = scan([data])
    split = scan([data[:-missing_from_first_frame], data[-missing_from_first_frame:]])
    assert split.rules_blocks == unsplit.rules_blocks
    assert split.rules_markers == unsplit.rules_markers == 1
    assert split.rules_blocks[0].fully_parsed


def test_truncated_tagged_retry_at_eof_keeps_the_original_prefix() -> None:
    data = tagged_interstitial_block(interstitial=b"\x01\x55\x66\x77\x88\x99" + b"\xff" * 4)
    block = scan([data[:-1]]).rules_blocks[0]
    assert not block.fully_parsed
    assert [row.match_count for row in block.rounds] == [10]


# Stage-keyed results


def test_one_result_record_decodes_its_date_score_and_stage() -> None:
    records = scan([example_result_record()])

    assert len(records.results) == 1
    result = records.results[0]
    assert result.date == date(RESULT_YEAR, 2, 20)
    assert result.stage_id == RESULT_STAGE_ID
    assert result.home_team_id == RESULT_HOME_TEAM_ID
    assert result.away_team_id == RESULT_AWAY_TEAM_ID
    assert result.home_goals == RESULT_HOME_GOALS
    assert result.away_goals == RESULT_AWAY_GOALS
    assert result.r22 == RESULT_R22


def test_the_span_pass_keeps_a_result_it_cannot_yet_place() -> None:
    """Scope is not this pass's job, and a record it cannot judge must not be dropped here.

    The calendar and the stage table decide whether a record is in scope, and neither has been
    read while the span is being scanned. A pass that turned records away on a stage id or a
    date of its own would be a second acceptance rule, out of step with the one the sections
    are judged by, and whichever of the two was narrower would silently lose scores.
    """
    records = scan([example_result_record(stage_id=999_999, year=1999)])

    assert len(records.results) == 1
    assert records.results[0].stage_id == 999_999
    assert records.results[0].date == date(1999, 2, 20)


def test_a_result_record_keeps_no_span_offset() -> None:
    """Nothing downstream separates these records by position, so none is carried."""
    records = scan([example_result_record()])

    assert not hasattr(records.results[0], "span_offset")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"lead_byte": 0x02}, id="a-decoy-lead-byte"),
        pytest.param({"home_goals": 41}, id="more-goals-than-the-maximum"),
        pytest.param({"away_goals": 41}, id="more-away-goals-than-the-maximum"),
        pytest.param({"home_team_id": 3_000_000}, id="a-home-team-id-above-the-range"),
        pytest.param({"away_team_id": 3_000_000}, id="an-away-team-id-above-the-range"),
    ],
)
def test_a_result_the_record_itself_rules_out_is_judged_and_turned_away(
    overrides: dict[str, int],
) -> None:
    """These are the tests a record answers alone, so the span pass applies them itself."""
    records = scan([example_result_record(**overrides)])

    assert records.results == ()
    assert records.result_candidates > 0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"sentinel": 2}, id="a-sentinel-that-is-not-one"),
        pytest.param({"zero_byte": 1}, id="a-byte-the-locator-needs-zero"),
    ],
)
def test_a_record_the_locator_does_not_match_is_never_even_a_candidate(
    overrides: dict[str, int],
) -> None:
    """The sentinel and the zero byte are in the pattern, so these never reach a judgement."""
    records = scan([example_result_record(**overrides)])

    assert records.results == ()
    assert records.result_candidates == 0


def test_a_result_record_straddling_a_frame_boundary_is_found_exactly_once() -> None:
    record = example_result_record()
    payload = span_payloads(record, record, separator_bytes=SEPARATOR_BYTES)

    for split_at in (5, 12, 20, RESULT_RECORD_BYTES + 10):
        records = scan([payload[:split_at], payload[split_at:]])

        assert len(records.results) == 2, split_at


# All four together


def test_all_four_structures_are_collected_in_one_pass() -> None:
    table_block = example_table_block()
    payload = span_payloads(
        example_fixture_blob(0),
        table_block,
        example_rules_block(),
        example_result_record(),
        separator_bytes=SEPARATOR_BYTES,
    )
    table_block_start = FIXTURE_BLOB_BYTES + SEPARATOR_BYTES
    split_at = table_block_start + len(table_block) // 2

    records = scan([payload[:split_at], payload[split_at:]])

    assert len(records.fixtures) == 1
    assert len(records.table_blocks) == 1
    assert len(records.rules_blocks) == 1
    assert len(records.results) == 1


# Counters


def test_counters_report_the_span_size_the_frames_and_every_candidate() -> None:
    frames = [
        three_fixture_payload(),
        example_table_block(),
        example_rules_block(),
        example_result_record(),
    ]

    records = scan(frames)

    assert records.span_bytes == sum(len(frame) for frame in frames)
    assert records.frame_count == 4
    assert records.fixture_candidates >= len(records.fixtures)
    assert records.table_block_candidates >= len(records.table_blocks)
    assert records.rules_markers >= len(records.rules_blocks)
    assert records.result_candidates >= len(records.results)


def test_repr_shows_the_counts_and_no_offsets() -> None:
    records = scan(
        [
            three_fixture_payload(),
            example_table_block(),
            example_rules_block(),
            example_result_record(),
        ]
    )

    description = repr(records)
    assert "3" in description
    assert "fixtures" in description
    assert "table blocks" in description
    assert "rules blocks" in description
    assert "results" in description
    for fixture in records.fixtures:
        assert str(fixture.span_offset) not in description


# Integration through an opened save


def span_fragment_path(tmp_path: Path, payloads: Sequence[bytes]) -> Path:
    sections = [
        SectionFrame(
            section.name,
            section.body,
            section.extension,
            span_frames(payloads) if section.name == "non_pl_hist_ls" else (),
        )
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def test_span_records_are_read_once_through_the_save_context(tmp_path: Path) -> None:
    payloads = [
        three_fixture_payload(),
        example_table_block(),
        example_rules_block(),
        example_result_record(),
    ]
    fragment_path = span_fragment_path(tmp_path, payloads)

    career_save = fmsave.open(fragment_path)
    assert career_save.info.game_date == CLOCK
    records = career_save._context.span_records()
    assert len(records.fixtures) == 3
    assert len(records.table_blocks) == 1
    assert len(records.rules_blocks) == 1
    assert len(records.results) == 1
    assert records.frame_count == 4
    assert career_save._context.span_records() is records

    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save._context.span_records()


def test_a_span_cut_in_the_middle_of_a_block_reads_what_is_whole(tmp_path: Path) -> None:
    table_block = example_table_block()
    fragment_path = span_fragment_path(tmp_path, [table_block[: len(table_block) // 2]])

    with fmsave.open(fragment_path) as career_save:
        records = career_save._context.span_records()

    assert records.table_blocks == ()
    assert records.fixtures == ()


def continuation_fixture(*, year: int = KICK_OFF_YEAR, home: int | None = None) -> bytes:
    blob = bytearray(example_fixture_blob(1, year=year, home_team_id=home))
    # These bytes are deliberately not interpreted as inline goals.
    blob[16], blob[23] = 7, 9
    return bytes(blob)


def continuation_payload(*, event_count: int = 0, middles: Sequence[bytes] | None = None) -> bytes:
    from tests.fixtures.span import counted_fixture_bytes

    if middles is None:
        middles = [continuation_fixture()]
    return (
        counted_fixture_bytes(example_fixture_blob(0), event_count=event_count)
        + b"".join(counted_fixture_bytes(row, event_count=event_count) for row in middles)
        + example_fixture_blob(2)
    )


def test_counted_fixture_continuations_preserve_the_strict_anchor_records() -> None:
    payload = continuation_payload(event_count=3)
    records = scan([payload])
    assert len(records.fixtures) == 2
    assert len(records.fixture_continuations) == 1
    continuation = records.fixture_continuations[0]
    assert (continuation.left_offset, continuation.right_offset) == (
        records.fixtures[0].span_offset,
        records.fixtures[1].span_offset,
    )
    assert len(continuation.fixtures) == 1
    middle = continuation.fixtures[0]
    assert middle.home_team_id == HOME_TEAM_IDS[1]
    assert middle.away_team_id == AWAY_TEAM_IDS[1]
    assert (middle.r39_42, middle.r47_54) == (0x11223344, 0x0102030405060708)


def test_a_short_continuation_is_invariant_at_every_frame_split() -> None:
    payload = continuation_payload(event_count=2)
    expected = scan([payload])
    for split in range(1, len(payload)):
        actual = scan([payload[:split], payload[split:]])
        assert actual.fixtures == expected.fixtures
        assert actual.fixture_continuations == expected.fixture_continuations
        assert actual.fixture_scores == expected.fixture_scores
        assert actual.fixture_presence == expected.fixture_presence
    one_byte = scan([payload[i : i + 1] for i in range(len(payload))])
    assert one_byte.fixtures == expected.fixtures
    assert one_byte.fixture_continuations == expected.fixture_continuations
    assert one_byte.fixture_scores == expected.fixture_scores
    assert one_byte.fixture_presence == expected.fixture_presence


def test_a_path_longer_than_the_carry_is_invariant_with_one_byte_frames() -> None:
    payload = continuation_payload(middles=[continuation_fixture()] * 676)
    assert len(payload) > span_layouts().carry_over_bytes
    expected = scan([payload])
    actual = scan([payload[i : i + 1] for i in range(len(payload))])
    assert actual.fixtures == expected.fixtures
    assert actual.fixture_continuations == expected.fixture_continuations
    assert len(actual.fixture_continuations[0].fixtures) == 676
    assert actual.fixture_scores == expected.fixture_scores
    assert len(actual.fixture_scores) == 677
    assert actual.fixture_presence == expected.fixture_presence


def test_event_arrays_are_skipped_across_frames_without_an_observed_count_cap() -> None:
    payload = continuation_payload(event_count=4097)
    expected = scan([payload])
    actual = scan([payload[i : i + 113] for i in range(0, len(payload), 113)])
    assert len(actual.fixture_continuations) == 1
    assert actual.fixture_continuations == expected.fixture_continuations
    assert actual.fixture_scores == expected.fixture_scores
    assert actual.fixture_presence == expected.fixture_presence


@pytest.mark.parametrize(
    "damage",
    ["secondary-marker", "inflated-count", "middle-marker", "date", "played", "tail-count"],
)
def test_a_broken_counted_path_cannot_emit_any_middle(damage: str) -> None:
    payload = bytearray(continuation_payload())
    if damage == "secondary-marker":
        payload[68] = 0
    elif damage == "inflated-count":
        payload[93:97] = (0xFFFFFFFF).to_bytes(4, "little")
    elif damage == "middle-marker":
        payload[97] = 0
    elif damage == "date":
        payload[122:126] = bytes(4)
    elif damage == "played":
        payload[164] = 2
    else:
        payload[190:194] = (1).to_bytes(4, "little")
    records = scan([bytes(payload)])
    assert len(records.fixtures) == 2
    assert records.fixture_continuations == ()
    assert records.fixture_scores == ()
    assert records.fixture_presence == ()


def test_an_unclosed_continuation_at_eof_is_not_emitted() -> None:
    payload = continuation_payload()[:-80]
    assert scan([payload]).fixture_continuations == ()


def test_a_bad_large_count_does_not_mask_a_later_independent_good_path() -> None:
    bad = bytearray(continuation_payload())
    bad[93:97] = (0xFFFFFFFF).to_bytes(4, "little")
    payload = bytes(bad) + bytes(20) + continuation_payload()
    records = scan([payload])
    assert len(records.fixtures) == 4
    assert len(records.fixture_continuations) == 1
    assert records.fixture_continuations[0].left_offset > len(bad)


def test_filtered_middle_references_and_years_still_frame_the_known_later_row() -> None:
    payload = continuation_payload(
        middles=[
            continuation_fixture(year=1905),
            continuation_fixture(home=3_000_000),
            continuation_fixture(),
        ]
    )
    records = scan([payload])
    assert len(records.fixture_continuations) == 1
    assert [r.home_team_id for r in records.fixture_continuations[0].fixtures] == [HOME_TEAM_IDS[1]]


def test_consecutive_anchors_in_different_clusters_cannot_own_a_continuation() -> None:
    import dataclasses

    payload = continuation_payload()
    layouts = span_layouts()
    small_clusters = dataclasses.replace(
        layouts, fixtures=dataclasses.replace(layouts.fixtures, cluster_gap_bytes=100)
    )
    records = scan_span([payload], small_clusters, CLOCK, FILE_NAME)
    assert len(records.fixtures) == 2
    assert records.fixture_continuations == ()


def test_an_exact_closing_anchor_beyond_the_cluster_gap_is_never_committed() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    gap = span_layouts().fixtures.cluster_gap_bytes
    payload = counted_fixture_bytes(
        example_fixture_blob(0), event_count=gap // 16
    ) + example_fixture_blob(2)
    whole = scan([payload])
    fragmented = scan([payload[i : i + 4096] for i in range(0, len(payload), 4096)])
    assert len(whole.fixtures) == 2
    assert whole.fixtures == fragmented.fixtures
    assert whole.fixture_continuations == fragmented.fixture_continuations == ()
    assert whole.fixture_scores == fragmented.fixture_scores == ()
    assert whole.fixture_presence == fragmented.fixture_presence == ()


def test_owned_unplayed_middle_stays_unplayed_without_invented_inline_goals() -> None:
    payload = (
        example_fixture_blob(0)[:67]
        + b"\x00"
        + continuation_fixture()[:67]
        + b"\x00"
        + example_fixture_blob(2)
    )
    records = scan([payload])
    assert len(records.fixture_continuations) == 1
    assert records.fixture_continuations[0].fixtures[0].played is False
    assert records.fixture_scores == ()
    assert [r.played for r in records.fixture_presence] == [False, False]


def test_counted_scores_belong_to_the_following_physical_core_including_strict_anchors() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = (
        counted_fixture_bytes(example_fixture_blob(0), goals=(2, 1), event_count=3)
        + counted_fixture_bytes(continuation_fixture(), goals=(0, 0), optional_goals=(1, 2))
        + example_fixture_blob(2)
    )
    records = scan([payload])
    assert [(s.span_offset, s.home_goals, s.away_goals) for s in records.fixture_scores] == [
        (12 + 97 + 3 * 16, 2, 1),
        (12 + 2 * 97 + 3 * 16, 1, 2),
    ]
    assert records.fixture_scores[0].span_offset not in {r.span_offset for r in records.fixtures}
    assert records.fixture_scores[1].span_offset == records.fixtures[1].span_offset


def test_an_owned_packet_between_two_strict_anchors_needs_no_recovered_middle() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = counted_fixture_bytes(example_fixture_blob(0), goals=(3, 2)) + example_fixture_blob(2)
    records = scan([payload])
    assert records.fixture_continuations == ()
    assert [(s.span_offset, s.home_goals, s.away_goals) for s in records.fixture_scores] == [
        (109, 3, 2)
    ]
    assert (
        scan([payload[i : i + 1] for i in range(len(payload))]).fixture_scores
        == records.fixture_scores
    )


@pytest.mark.parametrize(
    ("basic", "optional", "expected"),
    [
        ((2, 1), (255, 255), (2, 1)),
        ((1, 1), (2, 3), (2, 3)),
        ((1, 1), (1, 1), (1, 1)),
        ((255, 1), (2, 3), (None, None)),
        ((41, 1), (42, 3), (None, None)),
        ((1, 1), (255, 2), (None, None)),
        ((1, 1), (2, 255), (None, None)),
        ((2, 1), (1, 3), (None, None)),
        ((1, 2), (3, 1), (None, None)),
        ((1, 1), (41, 3), (None, None)),
    ],
)
def test_score_safety_rejects_only_its_own_evidence(
    basic: tuple[int, int], optional: tuple[int, int], expected: tuple[int | None, int | None]
) -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = (
        counted_fixture_bytes(example_fixture_blob(0), goals=basic, optional_goals=optional)
        + counted_fixture_bytes(continuation_fixture(), goals=(4, 0))
        + example_fixture_blob(2)
    )
    records = scan([payload])
    assert len(records.fixture_continuations) == 1
    assert [(s.home_goals, s.away_goals) for s in records.fixture_scores] == [expected, (4, 0)]
    assert [r.played for r in records.fixture_presence] == [True, True]


def test_shootout_and_partial_aggregate_values_cannot_change_match_goals() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = counted_fixture_bytes(
        example_fixture_blob(0), goals=(1, 1), optional_goals=(2, 2), other_goals=(5, 6, 255, 4)
    ) + example_fixture_blob(2)
    score = scan([payload]).fixture_scores[0]
    assert (score.home_goals, score.away_goals) == (2, 2)


def test_incomplete_counted_ownership_cannot_publish_even_a_safe_packet_score() -> None:
    payload = continuation_payload()[:-80]
    assert scan([payload]).fixture_scores == ()
    bad = bytearray(continuation_payload())
    bad[190:194] = (1).to_bytes(4, "little")
    assert scan([bytes(bad)]).fixture_scores == ()


def test_score_fields_follow_registered_offsets_and_validate_their_extent() -> None:
    import dataclasses

    from tests.fixtures.span import counted_fixture_bytes

    layout = span_layouts()
    changed = dataclasses.replace(
        layout,
        fixtures=dataclasses.replace(
            layout.fixtures, secondary_home_goals_offset=9, secondary_away_goals_offset=5
        ),
    )
    payload = counted_fixture_bytes(example_fixture_blob(0), goals=(2, 1)) + example_fixture_blob(2)
    scores = scan_span([payload], changed, CLOCK, FILE_NAME).fixture_scores
    assert (scores[0].home_goals, scores[0].away_goals) == (1, 2)
    broken = dataclasses.replace(
        layout, fixtures=dataclasses.replace(layout.fixtures, secondary_home_goals_offset=25)
    )
    with pytest.raises(ValueError, match="score fields"):
        scan_span([payload], broken, CLOCK, FILE_NAME)


@pytest.mark.parametrize("damage", ["played", "date"])
def test_owned_status_ignores_next_collection_but_rejects_invalid_closing_date(damage: str) -> None:
    from tests.fixtures.span import counted_fixture_bytes

    right = bytearray(example_fixture_blob(2))
    if damage == "played":
        right[67] = 2
    else:
        right[25:27] = bytes(2)
    payload = counted_fixture_bytes(example_fixture_blob(0), goals=(3, 2)) + bytes(right)
    records = scan([payload])
    assert len(records.fixtures) == 2
    assert [(s.home_goals, s.away_goals) for s in records.fixture_scores] == (
        [(3, 2)] if damage == "played" else []
    )
    assert [r.played for r in records.fixture_presence] == ([True] if damage == "played" else [])
    assert (
        scan([payload[i : i + 1] for i in range(len(payload))]).fixture_scores
        == records.fixture_scores
    )


def test_mixed_present_and_absent_rows_use_their_own_prefix_at_every_split() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = (
        counted_fixture_bytes(example_fixture_blob(0), goals=(2, 1), event_count=2)
        + continuation_fixture()[:67]
        + b"\x00"
        + counted_fixture_bytes(continuation_fixture(), goals=(3, 2), event_count=1)
        + example_fixture_blob(2)
    )
    expected = scan([payload])
    assert [r.played for r in expected.fixture_presence] == [True, False, True]
    assert [r.played for r in expected.fixture_continuations[0].fixtures] == [True, False]
    assert [(r.home_goals, r.away_goals) for r in expected.fixture_scores] == [(2, 1), (3, 2)]
    assert expected.fixtures[0].span_offset not in {
        r.span_offset for r in expected.fixture_presence
    }
    for split in range(1, len(payload)):
        actual = scan([payload[:split], payload[split:]])
        assert actual.fixture_continuations == expected.fixture_continuations
        assert actual.fixture_presence == expected.fixture_presence
        assert actual.fixture_scores == expected.fixture_scores
    one_byte = scan([payload[i : i + 1] for i in range(len(payload))])
    assert one_byte.fixture_presence == expected.fixture_presence
    assert one_byte.fixture_scores == expected.fixture_scores


def test_terminal_collection_count_is_not_a_current_record_played_field() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    tail = (143).to_bytes(4, "little") + b"\x01" + (132).to_bytes(4, "little") + bytes(4)
    payload = (
        counted_fixture_bytes(example_fixture_blob(0), goals=(2, 2))
        + example_fixture_blob(2)[:67]
        + tail
    )
    records = scan([payload])
    assert len(records.fixtures) == 2
    assert [(s.home_goals, s.away_goals) for s in records.fixture_scores] == [(2, 2)]
    assert [r.played for r in records.fixture_presence] == [True]
    assert (
        scan([payload[i : i + 1] for i in range(len(payload))]).fixture_presence
        == records.fixture_presence
    )


def test_a_complete_67_byte_core_at_eof_has_no_guessed_closing_boundary() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    payload = (
        counted_fixture_bytes(example_fixture_blob(0), goals=(2, 2)) + example_fixture_blob(2)[:67]
    )
    records = scan([payload])
    assert len(records.fixtures) == 1
    assert records.fixture_continuations == ()
    assert records.fixture_presence == ()
    assert records.fixture_scores == ()


def test_invalid_prefix_drops_owned_evidence_but_not_a_later_independent_path() -> None:
    from tests.fixtures.span import counted_fixture_bytes

    bad = bytearray(counted_fixture_bytes(example_fixture_blob(0)))
    bad[67] = 2
    failed = bytes(bad) + example_fixture_blob(2)
    good = counted_fixture_bytes(example_fixture_blob(0), goals=(1, 0)) + example_fixture_blob(2)
    records = scan([failed + bytes(20) + good])
    assert len(records.fixtures) == 4
    assert len(records.fixture_presence) == 1
    assert records.fixture_presence[0].span_offset > len(failed)
    assert [(s.home_goals, s.away_goals) for s in records.fixture_scores] == [(1, 0)]


def cache_payload(
    *,
    first_count: int = 2,
    second_count: int = 1,
    event_count: int = 0,
    vector: bytes = b"\x07\x00\xff\x2a",
    calendar_cores: bool = False,
    cache_dates: list[tuple[int, int]] | None = None,
) -> bytes:
    from tests.fixtures.span import fixture_cache_bytes

    return fixture_cache_bytes(
        example_table_block(),
        [example_fixture_blob(0)] * first_count,
        [example_fixture_blob(1)] * second_count,
        event_count=event_count,
        vector=vector,
        calendar_cores=calendar_cores,
        cache_dates=cache_dates,
    )


def test_separate_counted_cache_rows_keep_all_original_span_anchors() -> None:
    payload = cache_payload()
    records = scan([payload])
    assert len(records.table_blocks) == 1
    assert len(records.fixture_cache_offsets) == 3
    assert records.fixture_cache_offsets == tuple(r.span_offset for r in records.fixtures)
    # The unsafe packet scores and opaque suffix word do not control ownership.
    assert {r.r47_54 & 0xFFFFFFFF for r in records.fixtures} == {0x0309FFFE}


@pytest.mark.parametrize("dates", [None, [], [(1, 2024), (366, 2024), (230, 2025)]])
def test_cache_nullable_dates_close_before_both_counted_lists(
    dates: list[tuple[int, int]] | None,
) -> None:
    payload = cache_payload(cache_dates=dates)
    expected = scan([payload])
    assert len(expected.fixture_cache_offsets) == 3
    for split in range(1, len(payload)):
        actual = scan([payload[:split], payload[split:]])
        assert actual.fixture_cache_offsets == expected.fixture_cache_offsets, split
    assert (
        scan([payload[i : i + 1] for i in range(len(payload))]).fixture_cache_offsets
        == expected.fixture_cache_offsets
    )


@pytest.mark.parametrize(
    "damage", ["prefix", "presence", "count_over", "count_under", "huge_count", "date"]
)
def test_malformed_nullable_dates_reject_the_whole_cache_parent(damage: str) -> None:
    payload = bytearray(cache_payload(cache_dates=[(12, 2025), (13, 2025)]))
    dates_at = len(example_table_block()) + 13 + 4
    if damage == "prefix":
        payload[dates_at] = 1
    elif damage == "presence":
        payload[dates_at + 1] = 2
    elif damage == "date":
        struct.pack_into("<H", payload, dates_at + 6 + 2, 0)
    else:
        count = {"count_over": 3, "count_under": 1, "huge_count": 0xFFFFFFFF}[damage]
        struct.pack_into("<I", payload, dates_at + 2, count)
    assert scan([bytes(payload)]).fixture_cache_offsets == ()


def test_truncated_nullable_date_array_and_raw_tail_never_commit_cache_rows() -> None:
    payload = cache_payload(cache_dates=[(12, 2025), (13, 2025)])
    dates_at = len(example_table_block()) + 13 + 4
    for cut in range(dates_at, dates_at + 2 + 4 + 8 + 11):
        assert scan([payload[:cut]]).fixture_cache_offsets == (), cut


@pytest.mark.parametrize(("first", "second"), [(0, 2), (2, 0), (0, 0)])
def test_cache_lists_can_be_explicitly_empty(first: int, second: int) -> None:
    payload = cache_payload(first_count=first, second_count=second)
    records = scan([payload])
    assert len(records.fixture_cache_offsets) == first + second
    assert records.fixture_cache_offsets == tuple(r.span_offset for r in records.fixtures)


def test_cache_ownership_is_identical_at_every_frame_split_and_one_byte_frames() -> None:
    payload = cache_payload()
    expected = scan([payload])
    for split in range(1, len(payload)):
        actual = scan([payload[:split], payload[split:]])
        assert actual.fixture_cache_offsets == expected.fixture_cache_offsets, split
        assert actual.fixtures == expected.fixtures, split
    actual = scan([payload[i : i + 1] for i in range(len(payload))])
    assert actual.fixture_cache_offsets == expected.fixture_cache_offsets
    assert actual.fixtures == expected.fixtures


@pytest.mark.parametrize("count", [0, 255])
def test_raw_cache_vector_entries_have_their_own_repeated_count(count: int) -> None:
    payload = cache_payload(vector=bytes(i % 256 for i in range(count)))
    assert len(scan([payload]).fixture_cache_offsets) == 3
    broken = bytearray(payload)
    vector_start = len(example_table_block())
    struct.pack_into("<H", broken, vector_start + 11, count + 1)
    assert scan([bytes(broken)]).fixture_cache_offsets == ()


@pytest.mark.parametrize(
    "damage",
    [
        "first_count",
        "first_under",
        "second_count",
        "second_under",
        "huge_count",
        "events",
        "core",
        "date",
        "suffix",
        "prefix",
        "header",
    ],
)
def test_malformed_cache_parent_never_excludes_a_complete_prefix(damage: str) -> None:
    payload = bytearray(cache_payload())
    table_end = len(example_table_block())
    first = table_end + 13 + 4 + 13
    second = first + 4 + 2 * 92
    if damage == "first_count":
        struct.pack_into("<I", payload, first, 3)
    elif damage == "first_under":
        struct.pack_into("<I", payload, first, 1)
    elif damage == "huge_count":
        struct.pack_into("<I", payload, first, 0xFFFFFFFF)
    elif damage == "second_count":
        struct.pack_into("<I", payload, second, 2)
    elif damage == "second_under":
        struct.pack_into("<I", payload, second, 0)
    elif damage == "events":
        struct.pack_into("<I", payload, second + 4 + 25, 0xFFFFFFFF)
    elif damage == "core":
        payload[second + 4 + 29] = 0
    elif damage == "date":
        struct.pack_into("<H", payload, second + 4 + 29 + 27, 0)
    elif damage == "suffix":
        payload[second + 4 + 29 + 59] = 0
    elif damage == "prefix":
        payload[-34] = 1
    else:
        payload[-12] = 1
    assert scan([bytes(payload)]).fixture_cache_offsets == ()


def test_missing_cache_tail_or_next_object_prefix_never_commits_rows() -> None:
    payload = cache_payload()
    for cut in range(len(payload) - 34, len(payload)):
        assert scan([payload[:cut]]).fixture_cache_offsets == (), cut


def test_a_real_calendar_core_cannot_be_reinterpreted_as_a_short_cache_core() -> None:
    payload = cache_payload(calendar_cores=True)
    assert scan([payload]).fixture_cache_offsets == ()


@pytest.mark.parametrize("bad_table", ["empty", "arithmetic"])
def test_unaccepted_table_lookalikes_do_not_own_cache_arrays(bad_table: str) -> None:
    from tests.fixtures.span import fixture_cache_bytes

    table = (
        example_table_block(total={})
        if bad_table == "empty"
        else example_table_block(total={"played": 4, "won": 0})
    )
    payload = fixture_cache_bytes(table, [example_fixture_blob(0)], [example_fixture_blob(1)])
    assert scan([payload]).fixture_cache_offsets == ()


def test_long_cache_packets_progress_without_another_table_or_strict_anchor() -> None:
    payload = cache_payload(first_count=1, second_count=1, event_count=5000)
    assert len(payload) > span_layouts().carry_over_bytes
    expected = scan([payload])
    assert len(expected.fixture_cache_offsets) == 2
    actual = scan([payload[i : i + 31] for i in range(0, len(payload), 31)])
    assert actual.fixture_cache_offsets == expected.fixture_cache_offsets
    assert actual.fixtures == expected.fixtures


def test_cache_event_skip_cannot_cross_the_existing_calendar_cluster_bound() -> None:
    event_count = span_layouts().fixtures.cluster_gap_bytes // 16
    payload = cache_payload(first_count=1, second_count=0, event_count=event_count)
    expected = scan([payload])
    assert expected.fixture_cache_offsets == ()
    actual = scan([payload[:600], payload[600:-100], payload[-100:]])
    assert actual.fixture_cache_offsets == ()


def test_a_failed_parent_does_not_hide_a_later_separately_owned_cache() -> None:
    bad = cache_payload()[:-19]
    good = cache_payload(first_count=1, second_count=0)
    expected = scan([good]).fixture_cache_offsets
    records = scan([bad + bytes(30) + good])
    assert records.fixture_cache_offsets == tuple(len(bad) + 30 + o for o in expected)


def test_cache_framing_keeps_raw_references_and_dates_outside_calendar_output_scope() -> None:
    from tests.fixtures.span import fixture_cache_bytes

    raw = example_fixture_blob(0, year=1905, home_team_id=0xFFFFFFFF, away_team_id=0)
    payload = fixture_cache_bytes(example_table_block(), [raw], [])
    records = scan([payload])
    assert records.fixtures == ()
    assert len(records.fixture_cache_offsets) == 1


def test_long_cache_is_also_invariant_with_one_byte_frames() -> None:
    payload = cache_payload(first_count=1, second_count=0, event_count=4200)
    assert len(payload) > span_layouts().carry_over_bytes
    expected = scan([payload])
    actual = scan([payload[i : i + 1] for i in range(len(payload))])
    assert actual.fixture_cache_offsets == expected.fixture_cache_offsets
    assert len(actual.fixture_cache_offsets) == 1
