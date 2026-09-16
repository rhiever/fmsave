from __future__ import annotations

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


@pytest.mark.parametrize(
    ("home_team_id", "away_team_id"),
    [
        pytest.param(0, AWAY_TEAM_IDS[0], id="home-team-id-zero"),
        pytest.param(HOME_TEAM_IDS[0], 3_000_000, id="away-team-id-above-the-range"),
    ],
)
def test_a_team_id_outside_the_range_is_not_accepted(home_team_id: int, away_team_id: int) -> None:
    blob = example_fixture_blob(0, home_team_id=home_team_id, away_team_id=away_team_id)

    records = scan([blob])

    assert records.fixtures == ()
    assert records.fixture_candidates > 0


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
    assert block.club_count is None
    assert block.administration_points_deduction is None


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
        pytest.param({"home_team_id": 0}, id="a-home-team-id-below-the-range"),
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
