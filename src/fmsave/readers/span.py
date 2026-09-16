"""One streamed pass over the unnamed span: fixtures, league-table blocks, rules preambles.

All three structures share one unnamed region, around 200 MB decompressed on a full save, so
they are collected together instead of one pass each. The region is never buffered whole:
frames arrive one at a time and each is scanned as `carry + frame`, where the carry is the
last `SPAN_CARRY_OVER_BYTES` of the previous window and is far longer than the longest
record. A candidate whose bytes do not all lie inside its window is left alone, because the
next window's carry holds it whole; each structure remembers the greatest region-relative
offset it has already considered, so a candidate that appears in two windows is considered
exactly once, and every search starts far enough into the carry that only candidates which
could straddle the boundary are looked at twice.

Where a structure has a variable length, leaving a candidate alone also ends the scan of
that window: a later candidate might still be judged where this one cannot, and judging it
would carry the high-water mark past the deferred candidate and hide it from the next window
for good. A fixture record is a fixed length, so no later record can fit where an earlier one
does not, and its scan runs to the end of the window.

Each search's pattern, struct, offsets and bounds are derived from its layout once per
layout, so the scan loops never read a layout. The pass keeps raw words: it decodes no
kick-off time and joins no id, which is what the fixtures, league-tables and rules readers
are for. Region-relative offsets stay on these private records and are never public.
"""

from __future__ import annotations

import datetime
import functools
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from fmsave._container import RETRY_HINT
from fmsave._errors import ISSUES_URL, CorruptSaveError, ReaderCheckError
from fmsave._layouts import (
    SPAN_CARRY_OVER_BYTES,
    FixtureCalendarLayout,
    LeagueTableLayout,
    RulesPreambleLayout,
    find_layout,
)
from fmsave._scan import decode_date
from fmsave.readers._common import MISSING_REFERENCE, SPAN_REGION, build_gap_padded_struct

SPAN_RECORDS_CACHE_KEY = "span_records"

_UINT16 = struct.Struct("<H")
_UINT32 = struct.Struct("<I")
# A year's low byte is what the fixture pattern matches, so the years it covers must share
# a high byte. Every year from 1792 to 2047 shares 0x07.
_YEAR_HIGH_BYTE_SHIFT = 8
_KICK_OFF_YEAR_AFTER_DATE = 2


@dataclass(frozen=True, slots=True)
class RawTableRow:
    """One 17-byte row of a league-table block, as stored.

    `key` is the opponent's first-team id, or the layout's unplayed key on an aggregate row
    and in a match slot that was never played.
    """

    key: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int
    flag: int


@dataclass(frozen=True, slots=True)
class RawFixture:
    """One fixture calendar record, as stored, with its region-relative offset.

    The kick-off date is kept as the two raw words the record holds, `packed_kick_off` (the
    day of the year and the time slot) and `kick_off_year`, so the pass does no date
    arithmetic. `round_index` is raw, so the layout's no-round value still reads as itself.
    """

    span_offset: int
    stage_id: int | None
    stadium_ordinal: int | None
    home_team_id: int
    away_team_id: int
    packed_kick_off: int
    kick_off_year: int
    season_start_year: int | None
    match_record_id: int | None
    round_index: int
    played: bool
    date2: int
    phase: int
    leg: int
    r39_42: int
    match_rules_template: tuple[int, int, int]
    r47_54: int


@dataclass(frozen=True, slots=True)
class RawTableBlock:
    """One league-table block, as stored, with its region-relative offset.

    `aggregates` holds the five rows in their stored order: total, home, away, first half,
    second half. `matches` holds two rows per round, whose venue alternates with the slot's
    parity. `team_id` is the first-team id of the club the block belongs to, which the block
    itself does not guarantee to be a real team.
    """

    span_offset: int
    team_id: int
    head_bytes: tuple[int, ...]
    aggregates: tuple[RawTableRow, ...]
    rounds_per_venue: int
    matches: tuple[RawTableRow, ...]


@dataclass(frozen=True, slots=True)
class RawRulesRound:
    """One round of a competition-rules preamble, as stored.

    `number` is the stored byte plus one. A round the save does not number stores the
    layout's `round_no_number_value` of 255, so it reads here as 256 rather than as a guess.
    The rules reader is what maps that value, which is why the layout registers it although
    nothing in this pass reads it: a later reader must not mistake 256 for a real round.
    """

    number: int
    date: datetime.date | None
    match_count: int
    kind: int
    b5: int


@dataclass(frozen=True, slots=True)
class RawRulesBlock:
    """One competition-rules preamble block, as stored, with its region-relative offset.

    The four promotion-quad values are None together when the save's two copies of the quad
    differ. `club_count` and `administration_points_deduction` are always None: no fixed
    offset from the marker carries them on the corpus, so the span pass does not guess them.
    `fully_parsed` is true when the quad was doubled and the tie-break list, the prize list
    and every round record decoded. It therefore holds on a smaller share of blocks than the
    figure the format research recorded, which counts the lists and the rounds and ignores
    the quad: a gate on this field must say which of the two definitions it means.
    """

    span_offset: int
    promotion_places: int | None
    playoff_places: int | None
    promotion_byte2: int | None
    relegation_places: int | None
    tie_breaks: tuple[int, ...]
    prize_money: tuple[int, ...]
    rounds: tuple[RawRulesRound, ...]
    club_count: int | None
    administration_points_deduction: int | None
    fully_parsed: bool


@dataclass(frozen=True, slots=True, repr=False)
class SpanRecords:
    """What one pass over the unnamed span found. The repr gives counts only.

    The three counters count the candidates each search judged, accepted or not, so a reader
    that gates on an accept rate divides by them instead of walking the span a second time.
    They are not counts of raw pattern matches: a candidate whose bytes run past the end of
    the last window is never judged, so it is never counted either.

    `rules_markers` is the exception to that reading. Every marker judged yields a block, so
    it always equals `len(rules_blocks)` and an accept rate built from it is 1 by
    construction; it is the denominator for the share of blocks that fully parsed, not for a
    rejection rate.
    """

    fixtures: tuple[RawFixture, ...]
    table_blocks: tuple[RawTableBlock, ...]
    rules_blocks: tuple[RawRulesBlock, ...]
    fixture_candidates: int
    table_block_candidates: int
    rules_markers: int
    span_bytes: int
    frame_count: int

    def __repr__(self) -> str:
        return (
            f"<fmsave SpanRecords {len(self.fixtures)} fixtures, "
            f"{len(self.table_blocks)} table blocks, {len(self.rules_blocks)} rules blocks>"
        )


@dataclass(frozen=True, slots=True)
class SpanLayouts:
    """The layouts and the carry-over size one span pass uses."""

    fixtures: FixtureCalendarLayout
    tables: LeagueTableLayout
    rules: RulesPreambleLayout
    carry_over_bytes: int


def find_span_layouts(build: str) -> SpanLayouts:
    """Look up the three span layouts for a build. The span carries no schema number."""
    return SpanLayouts(
        fixtures=find_layout(FixtureCalendarLayout, SPAN_REGION, None, build).layout,
        tables=find_layout(LeagueTableLayout, SPAN_REGION, None, build).layout,
        rules=find_layout(RulesPreambleLayout, SPAN_REGION, None, build).layout,
        carry_over_bytes=SPAN_CARRY_OVER_BYTES,
    )


def _span_decode_error(file_name: str, error: Exception) -> CorruptSaveError:
    """A read ran past its window, which the acceptance checks should have caught."""
    return CorruptSaveError(
        f"{file_name}: region {SPAN_REGION!r} is damaged or was being written ({error}). "
        f"{RETRY_HINT}"
    )


def missing_clock_error(file_name: str) -> ReaderCheckError:
    """The span pass needs the in-game date to build its kick-off year window."""
    return ReaderCheckError(
        f"{file_name}: region {SPAN_REGION!r}: the save's in-game date could not be read, so "
        f"the kick-off year window cannot be built. Please report it at {ISSUES_URL}"
    )


@dataclass(frozen=True, slots=True)
class _FixtureSearch:
    """Everything the fixture scan needs from a `FixtureCalendarLayout` and the clock."""

    pattern: re.Pattern[bytes]
    match_offset: int
    record_bytes: int
    marker_byte_offset: int
    marker_byte_value: int
    sentinel_offsets: tuple[tuple[int, int], ...]
    fields_struct: struct.Struct
    struct_start: int
    stage_id_index: int
    stadium_ordinal_index: int
    home_team_id_index: int
    away_team_id_index: int
    packed_kick_off_index: int
    kick_off_year_index: int
    date2_index: int
    season_start_year_index: int
    match_record_id_index: int
    phase_index: int
    leg_index: int
    round_index_index: int
    r39_42_index: int
    match_rules_template_index: int
    r47_54_index: int
    played_index: int
    lowest_team_id: int
    highest_team_id: int
    search_back_bytes: int


@dataclass(frozen=True, slots=True)
class _TableSearch:
    """Everything the league-table scan needs from a `LeagueTableLayout`."""

    pattern: re.Pattern[bytes]
    row_bytes: int
    aggregate_count: int
    team_id_offset: int
    head_bytes_offset: int
    head_bytes_count: int
    rounds_per_venue_offset: int
    matches_offset: int
    lowest_rounds_per_venue: int
    highest_rounds_per_venue: int
    row_struct: struct.Struct
    key_index: int
    played_index: int
    played_copy_index: int
    won_index: int
    drawn_index: int
    lost_index: int
    goals_for_index: int
    goals_against_index: int
    points_index: int
    flag_index: int
    lowest_offset: int
    search_back_bytes: int


@dataclass(frozen=True, slots=True)
class _RulesSearch:
    """Everything the rules-preamble scan needs from a `RulesPreambleLayout`."""

    marker: bytes
    promotion_quad_offset: int
    promotion_quad_bytes: int
    body_offset: int
    tie_break_count_max: int
    prize_count_max: int
    round_count_max: int
    round_record_bytes: int
    round_anchor_search_bytes: int
    round_kind_offset: int
    round_date_offset: int
    round_b5_offset: int
    round_number_offset: int
    round_match_count_offset: int
    round_match_count_max: int
    moved_match_bytes: int
    moved_match_sentinel_offset: int
    moved_match_sentinel_value: int
    moved_match_tail_offset: int
    moved_match_tail: bytes
    moved_match_max_per_round: int
    search_back_bytes: int


def _byte_run(count: int) -> bytes:
    return b".{%d}" % count


@functools.cache
def _fixture_search(layout: FixtureCalendarLayout, clock_year: int) -> _FixtureSearch:
    """The fixture pattern and struct for one layout and in-game year, built on first use.

    Raises:
        ValueError: The layout does not describe two ascending sentinel bytes before the
            kick-off year, the years around the clock do not share one high byte, or two
            record fields overlap.
    """
    sentinels = tuple(sorted(layout.sentinel_offsets))
    if len(sentinels) != 2:
        raise ValueError("a fixture record is located by exactly two sentinel bytes")
    (first_offset, first_value), (second_offset, second_value) = sentinels
    year_low_offset = layout.kick_off_date_offset + _KICK_OFF_YEAR_AFTER_DATE
    if not 0 <= first_offset < second_offset < year_low_offset:
        raise ValueError(
            f"the sentinel offsets {sentinels} must be at or after the record start and "
            f"before the kick-off year at offset {year_low_offset}"
        )
    years = range(clock_year - layout.years_before_clock, clock_year + layout.years_after_clock + 1)
    high_bytes = {year >> _YEAR_HIGH_BYTE_SHIFT for year in years}
    if len(high_bytes) != 1:
        raise ValueError(
            f"the kick-off years {years.start} to {years.stop - 1} do not share one high "
            "byte, so no single byte class covers them"
        )
    high_byte = high_bytes.pop()
    low_bytes = sorted(year & 0xFF for year in years)
    if low_bytes[-1] - low_bytes[0] != len(low_bytes) - 1:
        raise ValueError("the kick-off years' low bytes are not a single run")
    pattern = re.compile(
        re.escape(bytes((first_value,)))
        + _byte_run(second_offset - first_offset - 1)
        + re.escape(bytes((second_value,)))
        + _byte_run(year_low_offset - second_offset - 1)
        + b"["
        + re.escape(bytes((low_bytes[0],)))
        + b"-"
        + re.escape(bytes((low_bytes[-1],)))
        + b"]"
        + re.escape(bytes((high_byte,))),
        re.DOTALL,
    )
    template_code = f"{layout.match_rules_template_bytes}s"
    fields_struct, struct_start, index_by_name = build_gap_padded_struct(
        [
            (layout.stage_id_offset, "I", "stage_id"),
            (layout.stadium_ordinal_offset, "I", "stadium_ordinal"),
            (layout.home_team_id_offset, "I", "home_team_id"),
            (layout.away_team_id_offset, "I", "away_team_id"),
            (layout.kick_off_date_offset, "H", "packed_kick_off"),
            (year_low_offset, "H", "kick_off_year"),
            (layout.date2_offset, "I", "date2"),
            (layout.season_start_year_offset, "H", "season_start_year"),
            (layout.match_record_id_offset, "I", "match_record_id"),
            (layout.phase_offset, "B", "phase"),
            (layout.leg_offset, "B", "leg"),
            (layout.round_index_offset, "B", "round_index"),
            (layout.r39_42_offset, "I", "r39_42"),
            (layout.match_rules_template_offset, template_code, "match_rules_template"),
            (layout.r47_54_offset, "Q", "r47_54"),
            (layout.played_offset, "B", "played"),
        ]
    )
    lowest_team_id, highest_team_id = layout.team_id_range
    return _FixtureSearch(
        pattern=pattern,
        match_offset=first_offset,
        record_bytes=layout.record_bytes,
        marker_byte_offset=layout.marker_byte_offset,
        marker_byte_value=layout.marker_byte_value,
        sentinel_offsets=sentinels,
        fields_struct=fields_struct,
        struct_start=struct_start,
        stage_id_index=index_by_name["stage_id"],
        stadium_ordinal_index=index_by_name["stadium_ordinal"],
        home_team_id_index=index_by_name["home_team_id"],
        away_team_id_index=index_by_name["away_team_id"],
        packed_kick_off_index=index_by_name["packed_kick_off"],
        kick_off_year_index=index_by_name["kick_off_year"],
        date2_index=index_by_name["date2"],
        season_start_year_index=index_by_name["season_start_year"],
        match_record_id_index=index_by_name["match_record_id"],
        phase_index=index_by_name["phase"],
        leg_index=index_by_name["leg"],
        round_index_index=index_by_name["round_index"],
        r39_42_index=index_by_name["r39_42"],
        match_rules_template_index=index_by_name["match_rules_template"],
        r47_54_index=index_by_name["r47_54"],
        played_index=index_by_name["played"],
        lowest_team_id=lowest_team_id,
        highest_team_id=highest_team_id,
        search_back_bytes=layout.record_bytes - layout.marker_byte_offset,
    )


@functools.cache
def _table_search(layout: LeagueTableLayout) -> _TableSearch:
    """The league-table pattern and row struct for one layout, built on first use.

    Raises:
        ValueError: The row key does not start a row, the layout has fewer than two
            aggregate rows, or two row fields overlap.
    """
    if layout.key_offset != 0:
        raise ValueError("the row key must start a row, since the aggregate rows locate a block")
    if layout.aggregate_count < 2:
        raise ValueError("a block is located by at least two aggregate rows")
    key_bytes = _UINT32.pack(layout.unplayed_key)
    keyed_row = re.escape(key_bytes) + _byte_run(layout.row_bytes - _UINT32.size)
    pattern = re.compile(keyed_row * (layout.aggregate_count - 1) + re.escape(key_bytes), re.DOTALL)
    row_struct, _row_start, index_by_name = build_gap_padded_struct(
        [
            (layout.key_offset, "I", "key"),
            (layout.played_offset, "B", "played"),
            (layout.played_copy_offset, "B", "played_copy"),
            (layout.won_offset, "B", "won"),
            (layout.drawn_offset, "B", "drawn"),
            (layout.lost_offset, "B", "lost"),
            (layout.zero_offset, "B", "zero"),
            (layout.goals_for_offset, "H", "goals_for"),
            (layout.goals_against_offset, "H", "goals_against"),
            (layout.points_offset, "H", "points"),
            (layout.flag_offset, "B", "flag"),
        ],
        start_offset=0,
    )
    lowest_rounds, highest_rounds = layout.rounds_per_venue_range
    lowest_offset = min(layout.team_id_offset, layout.head_bytes_offset)
    longest_block = layout.matches_offset + layout.row_bytes * 2 * highest_rounds - lowest_offset
    return _TableSearch(
        pattern=pattern,
        row_bytes=layout.row_bytes,
        aggregate_count=layout.aggregate_count,
        team_id_offset=layout.team_id_offset,
        head_bytes_offset=layout.head_bytes_offset,
        head_bytes_count=layout.head_bytes_count,
        rounds_per_venue_offset=layout.rounds_per_venue_offset,
        matches_offset=layout.matches_offset,
        lowest_rounds_per_venue=lowest_rounds,
        highest_rounds_per_venue=highest_rounds,
        row_struct=row_struct,
        key_index=index_by_name["key"],
        played_index=index_by_name["played"],
        played_copy_index=index_by_name["played_copy"],
        won_index=index_by_name["won"],
        drawn_index=index_by_name["drawn"],
        lost_index=index_by_name["lost"],
        goals_for_index=index_by_name["goals_for"],
        goals_against_index=index_by_name["goals_against"],
        points_index=index_by_name["points"],
        flag_index=index_by_name["flag"],
        lowest_offset=lowest_offset,
        search_back_bytes=longest_block,
    )


@functools.cache
def _rules_search(layout: RulesPreambleLayout) -> _RulesSearch:
    """The rules-preamble marker and bounds for one layout, built on first use.

    Raises:
        ValueError: The marker is empty, or the body does not start after it.
    """
    if not layout.marker:
        raise ValueError("the rules marker must not be empty")
    if layout.body_offset < len(layout.marker):
        raise ValueError("the rules body must start at or after the end of the marker")
    longest_round = layout.round_record_bytes + (
        layout.moved_match_max_per_round * layout.moved_match_bytes
    )
    longest_block = (
        layout.body_offset
        + 2 * _UINT32.size
        + layout.tie_break_count_max
        + _UINT32.size * layout.prize_count_max
        + _UINT32.size
        + layout.round_count_max * longest_round
        - layout.promotion_quad_offset
    )
    return _RulesSearch(
        marker=layout.marker,
        promotion_quad_offset=layout.promotion_quad_offset,
        promotion_quad_bytes=layout.promotion_quad_bytes,
        body_offset=layout.body_offset,
        tie_break_count_max=layout.tie_break_count_max,
        prize_count_max=layout.prize_count_max,
        round_count_max=layout.round_count_max,
        round_record_bytes=layout.round_record_bytes,
        round_anchor_search_bytes=layout.round_anchor_search_bytes,
        round_kind_offset=layout.round_kind_offset,
        round_date_offset=layout.round_date_offset,
        round_b5_offset=layout.round_b5_offset,
        round_number_offset=layout.round_number_offset,
        round_match_count_offset=layout.round_match_count_offset,
        round_match_count_max=layout.round_match_count_max,
        moved_match_bytes=layout.moved_match_bytes,
        moved_match_sentinel_offset=layout.moved_match_sentinel_offset,
        moved_match_sentinel_value=layout.moved_match_sentinel_value,
        moved_match_tail_offset=layout.moved_match_tail_offset,
        moved_match_tail=layout.moved_match_tail,
        moved_match_max_per_round=layout.moved_match_max_per_round,
        search_back_bytes=longest_block,
    )


def _optional_id(value: int) -> int | None:
    return None if value == 0 or value == MISSING_REFERENCE else value


def _collect_fixtures(
    window: bytes,
    window_origin: int,
    search_from: int,
    search: _FixtureSearch,
    considered_to: int,
    fixtures: list[RawFixture],
) -> tuple[int, int]:
    """Append every accepted fixture record in the window; return (considered to, candidates)."""
    find_match = search.pattern.search
    window_length = len(window)
    match_offset = search.match_offset
    record_bytes = search.record_bytes
    marker_byte_offset = search.marker_byte_offset
    marker_byte_value = search.marker_byte_value
    sentinel_offsets = search.sentinel_offsets
    unpack_fields = search.fields_struct.unpack_from
    struct_start = search.struct_start
    stage_id_index = search.stage_id_index
    stadium_ordinal_index = search.stadium_ordinal_index
    home_team_id_index = search.home_team_id_index
    away_team_id_index = search.away_team_id_index
    packed_kick_off_index = search.packed_kick_off_index
    kick_off_year_index = search.kick_off_year_index
    date2_index = search.date2_index
    season_start_year_index = search.season_start_year_index
    match_record_id_index = search.match_record_id_index
    phase_index = search.phase_index
    leg_index = search.leg_index
    round_index_index = search.round_index_index
    r39_42_index = search.r39_42_index
    match_rules_template_index = search.match_rules_template_index
    r47_54_index = search.r47_54_index
    played_index = search.played_index
    lowest_team_id = search.lowest_team_id
    highest_team_id = search.highest_team_id
    add_fixture = fixtures.append
    candidates = 0

    match = find_match(window, search_from)
    while match is not None:
        match_start = match.start()
        match = find_match(window, match_start + 1)
        record_start = match_start - match_offset
        if record_start + marker_byte_offset < 0 or record_start + record_bytes > window_length:
            continue
        absolute = window_origin + record_start
        if absolute <= considered_to:
            continue
        considered_to = absolute
        candidates += 1
        if window[record_start + marker_byte_offset] != marker_byte_value:
            continue
        if any(window[record_start + offset] != value for offset, value in sentinel_offsets):
            continue
        values = unpack_fields(window, record_start + struct_start)
        home_team_id: int = values[home_team_id_index]
        away_team_id: int = values[away_team_id_index]
        if not (
            lowest_team_id <= home_team_id <= highest_team_id
            and lowest_team_id <= away_team_id <= highest_team_id
        ):
            continue
        stored_stadium: int = values[stadium_ordinal_index]
        stadium_ordinal = None if _optional_id(stored_stadium) is None else stored_stadium - 1
        stage_id: int = values[stage_id_index]
        season_start_year: int = values[season_start_year_index]
        template: bytes = values[match_rules_template_index]
        add_fixture(
            RawFixture(
                span_offset=absolute,
                stage_id=None if stage_id == MISSING_REFERENCE else stage_id,
                stadium_ordinal=stadium_ordinal,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                packed_kick_off=values[packed_kick_off_index],
                kick_off_year=values[kick_off_year_index],
                season_start_year=season_start_year or None,
                match_record_id=_optional_id(values[match_record_id_index]),
                round_index=values[round_index_index],
                played=values[played_index] != 0,
                date2=values[date2_index],
                phase=values[phase_index],
                leg=values[leg_index],
                r39_42=values[r39_42_index],
                match_rules_template=(template[0], template[1], template[2]),
                r47_54=values[r47_54_index],
            )
        )
    return considered_to, candidates


def _collect_table_blocks(
    window: bytes,
    window_origin: int,
    search_from: int,
    search: _TableSearch,
    considered_to: int,
    table_blocks: list[RawTableBlock],
) -> tuple[int, int]:
    """Append every accepted league-table block; return (considered to, candidates)."""
    find_match = search.pattern.search
    window_length = len(window)
    row_bytes = search.row_bytes
    aggregate_count = search.aggregate_count
    team_id_offset = search.team_id_offset
    head_bytes_offset = search.head_bytes_offset
    head_bytes_count = search.head_bytes_count
    rounds_per_venue_offset = search.rounds_per_venue_offset
    matches_offset = search.matches_offset
    lowest_rounds_per_venue = search.lowest_rounds_per_venue
    highest_rounds_per_venue = search.highest_rounds_per_venue
    unpack_row = search.row_struct.unpack_from
    key_index = search.key_index
    played_index = search.played_index
    played_copy_index = search.played_copy_index
    won_index = search.won_index
    drawn_index = search.drawn_index
    lost_index = search.lost_index
    goals_for_index = search.goals_for_index
    goals_against_index = search.goals_against_index
    points_index = search.points_index
    flag_index = search.flag_index
    lowest_offset = search.lowest_offset
    unpack_rounds = _UINT16.unpack_from
    unpack_team_id = _UINT32.unpack_from
    add_block = table_blocks.append
    candidates = 0

    match = find_match(window, search_from)
    while match is not None:
        head = match.start()
        match = find_match(window, head + 1)
        if head + lowest_offset < 0:
            # The bytes in front of this head lie before the region, so it can never be read.
            continue
        if head + matches_offset > window_length:
            break
        rounds_per_venue: int = unpack_rounds(window, head + rounds_per_venue_offset)[0]
        in_range = lowest_rounds_per_venue <= rounds_per_venue <= highest_rounds_per_venue
        match_count = 2 * rounds_per_venue
        block_end = head + matches_offset + row_bytes * match_count
        if in_range and block_end > window_length:
            # Deferred, so the scan of this window stops here rather than moving on. A block
            # is variable length, so a later candidate can still be judged where this one
            # cannot, and judging it would advance the high-water mark past this head and
            # hide it from the next window for good. Everything before here has been judged,
            # and the next window's carry holds this block whole.
            break
        absolute = window_origin + head
        if absolute <= considered_to:
            continue
        considered_to = absolute
        candidates += 1
        if not in_range:
            continue
        # The aggregate rows reject almost every candidate the pattern finds, so they are
        # read and checked before the match rows, which outnumber them many times over.
        aggregate_rows = [
            unpack_row(window, head + row_bytes * row_number)
            for row_number in range(aggregate_count)
        ]
        total_played: int = aggregate_rows[0][played_index]
        if total_played == 0:
            continue
        if any(
            row[played_index] != row[played_copy_index]
            or row[played_index] != row[won_index] + row[drawn_index] + row[lost_index]
            for row in aggregate_rows
        ):
            continue
        if aggregate_rows[1][played_index] + aggregate_rows[2][played_index] != total_played:
            continue
        if aggregate_rows[3][played_index] + aggregate_rows[4][played_index] != total_played:
            continue
        # The match rows start at matches_offset, which the aggregates do not reach.
        match_rows = [
            unpack_row(window, head + matches_offset + row_bytes * slot)
            for slot in range(match_count)
        ]
        head_start = head + head_bytes_offset
        add_block(
            RawTableBlock(
                span_offset=absolute,
                team_id=unpack_team_id(window, head + team_id_offset)[0],
                head_bytes=tuple(window[head_start : head_start + head_bytes_count]),
                aggregates=tuple(
                    RawTableRow(
                        key=row[key_index],
                        played=row[played_index],
                        won=row[won_index],
                        drawn=row[drawn_index],
                        lost=row[lost_index],
                        goals_for=row[goals_for_index],
                        goals_against=row[goals_against_index],
                        points=row[points_index],
                        flag=row[flag_index],
                    )
                    for row in aggregate_rows
                ),
                rounds_per_venue=rounds_per_venue,
                matches=tuple(
                    RawTableRow(
                        key=row[key_index],
                        played=row[played_index],
                        won=row[won_index],
                        drawn=row[drawn_index],
                        lost=row[lost_index],
                        goals_for=row[goals_for_index],
                        goals_against=row[goals_against_index],
                        points=row[points_index],
                        flag=row[flag_index],
                    )
                    for row in match_rows
                ),
            )
        )
    return considered_to, candidates


def _rules_block(
    span_offset: int,
    quad: bytes | None,
    tie_breaks: tuple[int, ...],
    prize_money: tuple[int, ...],
    rounds: tuple[RawRulesRound, ...],
    *,
    fully_parsed: bool,
) -> RawRulesBlock:
    """One rules block; the four quad values are None together when the copies differed."""
    promotion_places = playoff_places = promotion_byte2 = relegation_places = None
    if quad is not None:
        promotion_places, playoff_places, promotion_byte2, relegation_places = quad
    return RawRulesBlock(
        span_offset=span_offset,
        promotion_places=promotion_places,
        playoff_places=playoff_places,
        promotion_byte2=promotion_byte2,
        relegation_places=relegation_places,
        tie_breaks=tie_breaks,
        prize_money=prize_money,
        rounds=rounds,
        club_count=None,
        administration_points_deduction=None,
        fully_parsed=fully_parsed,
    )


def _parse_rules_block(
    window: bytes, span_offset: int, mark: int, search: _RulesSearch
) -> RawRulesBlock | None:
    """The block at `mark`, or None when this window does not hold enough of it to judge.

    A list whose count is outside its bound, or a round record that does not decode, ends
    the parse and leaves the block not fully parsed; only bytes missing from the window
    return None, so that the next window, whose carry holds the block whole, judges it.
    The caller has already checked that the promotion quad lies inside the window, so None
    always means the block runs past the window's end and the scan of it must stop there.
    """
    window_length = len(window)
    quad_start = mark + search.promotion_quad_offset
    quad_bytes = search.promotion_quad_bytes
    first_copy = window[quad_start : quad_start + quad_bytes]
    second_copy = window[quad_start + quad_bytes : quad_start + 2 * quad_bytes]
    quad = first_copy if first_copy == second_copy else None
    no_rounds: tuple[RawRulesRound, ...] = ()

    cursor = mark + search.body_offset
    if cursor + _UINT32.size > window_length:
        return None
    tie_break_count: int = _UINT32.unpack_from(window, cursor)[0]
    if tie_break_count > search.tie_break_count_max:
        return _rules_block(span_offset, quad, (), (), no_rounds, fully_parsed=False)
    cursor += _UINT32.size
    if cursor + tie_break_count > window_length:
        return None
    tie_breaks = tuple(window[cursor : cursor + tie_break_count])
    cursor += tie_break_count

    if cursor + _UINT32.size > window_length:
        return None
    prize_count: int = _UINT32.unpack_from(window, cursor)[0]
    if prize_count > search.prize_count_max:
        return _rules_block(span_offset, quad, tie_breaks, (), no_rounds, fully_parsed=False)
    cursor += _UINT32.size
    if cursor + _UINT32.size * prize_count > window_length:
        return None
    prize_money = tuple(
        _UINT32.unpack_from(window, cursor + _UINT32.size * prize)[0]
        for prize in range(prize_count)
    )
    cursor += _UINT32.size * prize_count

    if cursor + _UINT32.size > window_length:
        return None
    round_count: int = _UINT32.unpack_from(window, cursor)[0]
    if not 0 < round_count <= search.round_count_max:
        return _rules_block(
            span_offset, quad, tie_breaks, prize_money, no_rounds, fully_parsed=False
        )
    rounds = _parse_rules_rounds(window, cursor + _UINT32.size, round_count, search)
    if rounds is None:
        return None
    return _rules_block(
        span_offset,
        quad,
        tie_breaks,
        prize_money,
        rounds,
        fully_parsed=quad is not None and len(rounds) == round_count,
    )


def _parse_rules_rounds(
    window: bytes, body_cursor: int, round_count: int, search: _RulesSearch
) -> tuple[RawRulesRound, ...] | None:
    """The block's round records, or None when the window does not hold them all.

    The list is anchored on the first offset after the round count whose date decodes, and
    the record starts one byte before it, because a round record opens with an unidentified
    byte which for the first record is the round count's own high byte. Between records the
    save writes moved matches, which are stepped over.
    """
    window_length = len(window)
    record_bytes = search.round_record_bytes
    date_offset = search.round_date_offset
    match_count_offset = search.round_match_count_offset
    match_count_max = search.round_match_count_max
    number_offset = search.round_number_offset
    kind_offset = search.round_kind_offset
    b5_offset = search.round_b5_offset
    moved_match_bytes = search.moved_match_bytes
    moved_match_sentinel_offset = search.moved_match_sentinel_offset
    moved_match_sentinel_value = search.moved_match_sentinel_value
    moved_match_tail_offset = search.moved_match_tail_offset
    moved_match_tail = search.moved_match_tail
    moved_match_tail_end = moved_match_tail_offset + len(moved_match_tail)
    moved_match_max_per_round = search.moved_match_max_per_round

    position = -1
    for anchor in range(search.round_anchor_search_bytes):
        date_at = body_cursor + anchor
        if date_at + 4 > window_length:
            return None
        if decode_date(window, date_at) is not None:
            position = date_at - date_offset
            break
    if position < 0:
        return ()

    rounds: list[RawRulesRound] = []
    for round_number in range(round_count):
        if round_number:
            for _ in range(moved_match_max_per_round):
                if position + moved_match_bytes > window_length:
                    return None
                if (
                    window[position + moved_match_sentinel_offset] != moved_match_sentinel_value
                    or window[position + moved_match_tail_offset : position + moved_match_tail_end]
                    != moved_match_tail
                ):
                    break
                position += moved_match_bytes
        if position + record_bytes > window_length:
            return None
        round_date = decode_date(window, position + date_offset)
        match_count: int = _UINT32.unpack_from(window, position + match_count_offset)[0]
        if round_date is None or match_count > match_count_max:
            break
        rounds.append(
            RawRulesRound(
                number=window[position + number_offset] + 1,
                date=round_date,
                match_count=match_count,
                kind=window[position + kind_offset],
                b5=window[position + b5_offset],
            )
        )
        position += record_bytes
    return tuple(rounds)


def _collect_rules_blocks(
    window: bytes,
    window_origin: int,
    search_from: int,
    search: _RulesSearch,
    considered_to: int,
    rules_blocks: list[RawRulesBlock],
) -> tuple[int, int]:
    """Append one block per rules marker judged here; return (considered to, markers)."""
    find_marker = window.find
    marker = search.marker
    promotion_quad_offset = search.promotion_quad_offset
    add_block = rules_blocks.append
    markers = 0

    position = find_marker(marker, search_from)
    while position >= 0:
        absolute = window_origin + position
        next_position = find_marker(marker, position + 1)
        # A marker whose quad lies before the region starts can never be read, so it is
        # passed over rather than deferred, which would stop the scan here for good.
        if absolute > considered_to and position + promotion_quad_offset >= 0:
            block = _parse_rules_block(window, absolute, position, search)
            if block is None:
                # Deferred, so the scan of this window stops here rather than moving on, for
                # the reason the league-table scan stops: a block is variable length, and a
                # later marker that can be judged would hide this one from the next window.
                break
            considered_to = absolute
            markers += 1
            add_block(block)
        position = next_position
    return considered_to, markers


def scan_span(
    frames: Iterable[bytes], layouts: SpanLayouts, clock: datetime.date, file_name: str
) -> SpanRecords:
    """Collect fixtures, league-table blocks and rules preambles from one pass over the span.

    `frames` are the region's decompressed frames in file order. Only one frame plus the
    carry-over is held at a time. A candidate that fails an acceptance check is not emitted
    and is never an error.

    Raises:
        CorruptSaveError: A decode ran past its window, which the acceptance checks should
            have caught, so the span is damaged or was being written.
        ValueError: A layout is inconsistent (see the `_*_search` builders).
    """
    fixture_search = _fixture_search(layouts.fixtures, clock.year)
    table_search = _table_search(layouts.tables)
    rules_search = _rules_search(layouts.rules)
    carry_over_bytes = layouts.carry_over_bytes

    fixtures: list[RawFixture] = []
    table_blocks: list[RawTableBlock] = []
    rules_blocks: list[RawRulesBlock] = []
    fixture_candidates = 0
    table_block_candidates = 0
    rules_markers = 0
    fixtures_considered_to = -1
    tables_considered_to = -1
    rules_considered_to = -1

    carry = b""
    window_origin = 0
    span_bytes = 0
    frame_count = 0
    for frame_bytes in frames:
        window = carry + frame_bytes if carry else frame_bytes
        carry_length = len(window) - len(frame_bytes)
        frame_count += 1
        span_bytes += len(frame_bytes)
        try:
            fixtures_considered_to, found_fixtures = _collect_fixtures(
                window,
                window_origin,
                max(0, carry_length - fixture_search.search_back_bytes),
                fixture_search,
                fixtures_considered_to,
                fixtures,
            )
            tables_considered_to, found_blocks = _collect_table_blocks(
                window,
                window_origin,
                max(0, carry_length - table_search.search_back_bytes),
                table_search,
                tables_considered_to,
                table_blocks,
            )
            rules_considered_to, found_markers = _collect_rules_blocks(
                window,
                window_origin,
                max(0, carry_length - rules_search.search_back_bytes),
                rules_search,
                rules_considered_to,
                rules_blocks,
            )
        except (struct.error, IndexError, CorruptSaveError) as error:
            raise _span_decode_error(file_name, error) from error
        fixture_candidates += found_fixtures
        table_block_candidates += found_blocks
        rules_markers += found_markers

        window_end = window_origin + len(window)
        carry = window[-carry_over_bytes:] if len(window) > carry_over_bytes else window
        window_origin = window_end - len(carry)
    return SpanRecords(
        fixtures=tuple(fixtures),
        table_blocks=tuple(table_blocks),
        rules_blocks=tuple(rules_blocks),
        fixture_candidates=fixture_candidates,
        table_block_candidates=table_block_candidates,
        rules_markers=rules_markers,
        span_bytes=span_bytes,
        frame_count=frame_count,
    )
