"""In-memory unnamed-span fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests
built here. Every id, date and value below is fictional.

Four structures share the span and are built here: the fixture calendar record, the
league-table block, the competition-rules preamble block, and the stage-keyed result record,
which also occurs in several named sections and is built here for those too.
"""

from __future__ import annotations

import struct
import sys
from collections.abc import Mapping, Sequence

from tests.fixtures.container import packed_date

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

# Fixture calendar: 12 lead-in bytes (the 0x1C marker, the stage id and the stadium
# ordinal) then the 68-byte record, addressed from the home team id.
FIXTURE_LEAD_IN_BYTES = 12
FIXTURE_RECORD_BYTES = 68
FIXTURE_MARKER_BYTE = 0x1C
FIXTURE_SENTINEL_BYTE = 0xFF
FIXTURE_STAGE_ID_AT = 1
FIXTURE_STADIUM_AT = 5

# League table: a 17-byte row, five aggregate rows, then the match slots.
TABLE_ROW_BYTES = 17
TABLE_HEAD_BYTES = 19
TABLE_TEAM_ID_BACK = 23
TABLE_ROUNDS_PER_VENUE_AT = 85
TABLE_MATCHES_AT = 87
UNPLAYED_KEY = 0xFFFFFFFF
DEFAULT_HEAD_BYTES = bytes(range(TABLE_HEAD_BYTES))

# Competition rules: the promotion quad twice, the 15-byte marker, then the body.
RULES_MARKER = bytes.fromhex("03000001000000ffff000001ffffff")
RULES_BODY_OFFSET = 16
ROUND_RECORD_BYTES = 15
ROUND_NO_NUMBER = 0xFF
ROUND_SENTINEL_BYTE = 0xFF
# Legacy's anchor for the club count; fmsave does not read it, because no fixed offset from
# the marker carries that value on either corpus save measured.
CLUB_COUNT_MARKER = bytes.fromhex("000202")

# Stage-keyed result: a 27-byte record carrying one match's score.
STAGE_RESULT_BYTES = 27
STAGE_RESULT_LEAD_BYTE = 0x01
STAGE_RESULT_SENTINEL = 1
STAGE_RESULT_R22 = 0x5A

SPAN_SEPARATOR_BYTES = 64


def packed_kick_off(day_of_year: int, year: int, time_slot: int) -> bytes:
    """The 4-byte kick-off date: the day-and-slot word, then the year."""
    return packed_date(day_of_year, year, time_slot)


def fixture_record_bytes(
    *,
    stage_id: int,
    stadium_ordinal: int,
    home_team_id: int,
    away_team_id: int,
    day_of_year: int,
    year: int,
    time_slot: int,
    season_start_year: int,
    match_record_id: int,
    round_index: int,
    played: bool,
    date2: int = 0x1234,
    phase: int = 2,
    leg: int = 1,
    r39_42: int = 0x11223344,
    match_rules_template: tuple[int, int, int] = (7, 8, 9),
    r47_54: int = 0x0102030405060708,
) -> bytes:
    """One fixture calendar record with its lead-in: 80 bytes.

    The 0x1C marker sits at index 0, the u32 stage id at index 1 and the u32 stadium
    ordinal (the value plus 1, as the save stores it) at index 5, so the record itself
    starts at index 12 and the marker is 12 bytes before it. Inside the record: the home
    team id at +0, a 0xFF at +4, the away team id at +7, a 0xFF at +11, the kick-off
    date4 at +13, a second date at +17, the season start year at +26, the match record id
    at +32, the phase, leg and round index at +36 to +38, unidentified values at +39 and
    +47, the three match-rules template bytes at +43, and the played byte at +55.
    """
    lead_in = bytearray(FIXTURE_LEAD_IN_BYTES)
    lead_in[0] = FIXTURE_MARKER_BYTE
    struct.pack_into("<I", lead_in, FIXTURE_STAGE_ID_AT, stage_id)
    struct.pack_into("<I", lead_in, FIXTURE_STADIUM_AT, stadium_ordinal + 1)

    record = bytearray(FIXTURE_RECORD_BYTES)
    struct.pack_into("<I", record, 0, home_team_id)
    record[4] = FIXTURE_SENTINEL_BYTE
    struct.pack_into("<I", record, 7, away_team_id)
    record[11] = FIXTURE_SENTINEL_BYTE
    record[13:17] = packed_kick_off(day_of_year, year, time_slot)
    struct.pack_into("<I", record, 17, date2)
    struct.pack_into("<H", record, 26, season_start_year)
    struct.pack_into("<I", record, 32, match_record_id)
    record[36] = phase
    record[37] = leg
    record[38] = round_index
    struct.pack_into("<I", record, 39, r39_42)
    record[43:46] = bytes(match_rules_template)
    struct.pack_into("<Q", record, 47, r47_54)
    record[55] = 1 if played else 0
    return bytes(lead_in) + bytes(record)


def stage_result_bytes(
    *,
    stage_id: int,
    home_team_id: int,
    away_team_id: int,
    day_of_year: int,
    year: int,
    home_goals: int,
    away_goals: int,
    r22: int = STAGE_RESULT_R22,
    lead_byte: int = STAGE_RESULT_LEAD_BYTE,
    sentinel: int = STAGE_RESULT_SENTINEL,
    zero_byte: int = 0,
) -> bytes:
    """One 27-byte stage-keyed result record, carrying one match's score.

    The lead byte sits at +0, the match date4 at +1, the u32 stage id at +5, the u16 sentinel
    at +9, the u32 home team id at +11, the byte the locator requires to be zero at +15, the
    u32 away team id at +16, the home and away goal bytes at +20 and +21, and five
    unidentified bytes from +22, of which only the first is read.

    `lead_byte`, `sentinel` and `zero_byte` are settable so a test can write a record the
    locator must turn away.
    """
    record = bytearray(STAGE_RESULT_BYTES)
    record[0] = lead_byte
    record[1:5] = packed_date(day_of_year, year)
    struct.pack_into("<I", record, 5, stage_id)
    struct.pack_into("<H", record, 9, sentinel)
    struct.pack_into("<I", record, 11, home_team_id)
    record[15] = zero_byte
    struct.pack_into("<I", record, 16, away_team_id)
    record[20] = home_goals
    record[21] = away_goals
    record[22] = r22
    return bytes(record)


def table_row_bytes(
    *,
    key: int,
    played: int,
    won: int,
    drawn: int,
    lost: int,
    goals_for: int,
    goals_against: int,
    points: int,
    flag: int = 0,
) -> bytes:
    """One 17-byte table row: the key, the counters written as the save stores them.

    `played` is written twice, at +4 and +5, and the byte at +9 is zero.
    """
    row = bytearray(TABLE_ROW_BYTES)
    struct.pack_into("<I", row, 0, key)
    row[4] = played
    row[5] = played
    row[6] = won
    row[7] = drawn
    row[8] = lost
    row[9] = 0
    struct.pack_into("<HHH", row, 10, goals_for, goals_against, points)
    row[16] = flag
    return bytes(row)


def _row_from_counters(counters: Mapping[str, int], *, key: int) -> bytes:
    """One row from a counter mapping; an absent `won` becomes `played - drawn - lost`.

    That default keeps a block's aggregates internally consistent when a test only cares
    about one of them; a test that wants to break the `played == won + drawn + lost` rule
    passes all three counters explicitly.
    """
    played = counters.get("played", 0)
    drawn = counters.get("drawn", 0)
    lost = counters.get("lost", 0)
    return table_row_bytes(
        key=counters.get("key", key),
        played=played,
        won=counters.get("won", played - drawn - lost),
        drawn=drawn,
        lost=lost,
        goals_for=counters.get("goals_for", 0),
        goals_against=counters.get("goals_against", 0),
        points=counters.get("points", 0),
        flag=counters.get("flag", 0),
    )


def table_block_bytes(
    *,
    team_id: int,
    rounds_per_venue: int,
    total: Mapping[str, int],
    home: Mapping[str, int],
    away: Mapping[str, int],
    first_half: Mapping[str, int],
    second_half: Mapping[str, int],
    matches: Sequence[Mapping[str, int] | None],
    head_bytes: bytes = DEFAULT_HEAD_BYTES,
) -> bytes:
    """One league-table block, 23 + 87 + 17 * 2 * `rounds_per_venue` bytes.

    The u32 first-team id sits 23 bytes before the block head and the 19 undecoded head
    bytes 19 bytes before it. From the head come the five aggregate rows in the order
    TOTAL, HOME, AWAY, FIRST HALF, SECOND HALF (each keyed 0xFFFFFFFF), the u16 rounds per
    venue at +85, and `2 * rounds_per_venue` match rows at +87. A `None` match slot is
    written with the unplayed key and all-zero counters.

    Raises:
        ValueError: `head_bytes` is not 19 bytes, or `matches` does not hold exactly
            `2 * rounds_per_venue` slots.
    """
    if len(head_bytes) != TABLE_HEAD_BYTES:
        raise ValueError(f"head_bytes must be {TABLE_HEAD_BYTES} bytes")
    match_slots = list(matches)
    if len(match_slots) != 2 * rounds_per_venue:
        raise ValueError(f"matches must hold {2 * rounds_per_venue} slots, not {len(match_slots)}")
    block = bytearray()
    block.extend(struct.pack("<I", team_id))
    block.extend(head_bytes)
    for aggregate in (total, home, away, first_half, second_half):
        block.extend(_row_from_counters(aggregate, key=UNPLAYED_KEY))
    block.extend(struct.pack("<H", rounds_per_venue))
    for slot in match_slots:
        if slot is None:
            block.extend(
                table_row_bytes(
                    key=UNPLAYED_KEY,
                    played=0,
                    won=0,
                    drawn=0,
                    lost=0,
                    goals_for=0,
                    goals_against=0,
                    points=0,
                )
            )
        else:
            block.extend(_row_from_counters(slot, key=UNPLAYED_KEY))
    return bytes(block)


def round_record_bytes(
    *,
    stored_number: int,
    day_of_year: int,
    year: int,
    match_count: int,
    kind: int = 0,
    b5: int = 0,
    b7: int = 1,
) -> bytes:
    """One 15-byte round record of a rules preamble.

    The unidentified `kind` byte sits at +0, the date4 at +1, the unidentified `b5` byte
    at +5, the stored round number (the number minus 1, or 255 for no round number) at
    +6, an unidentified byte that is almost always 1 at +7, a 0xFF at +8, the u32 match
    count at +9, a second copy of the stored round number at +13, and a 0xFF at +14.
    """
    record = bytearray(ROUND_RECORD_BYTES)
    record[0] = kind
    record[1:5] = packed_date(day_of_year, year)
    record[5] = b5
    record[6] = stored_number
    record[7] = b7
    record[8] = ROUND_SENTINEL_BYTE
    struct.pack_into("<I", record, 9, match_count)
    record[13] = stored_number
    record[14] = ROUND_SENTINEL_BYTE
    return bytes(record)


def moved_match_bytes(*, day_of_year: int = 11, year: int = 1900, tail_byte: int = 0xFF) -> bytes:
    """One 10-byte interstitial block between round records: a date-shaped pair of words,
    then 0xFF, then `tail_byte` (0xFF or 3 in the saves), then four 0xFF.
    """
    return packed_date(day_of_year, year) + bytes([ROUND_SENTINEL_BYTE, tail_byte]) + b"\xff" * 4


def rules_preamble_bytes(
    *,
    promotion: int,
    playoff: int,
    promotion_byte2: int,
    relegation: int,
    tie_breaks: Sequence[int],
    prize_money: Sequence[int],
    rounds: Sequence[Mapping[str, int]],
    double_quad: bool = True,
    club_count: int = 20,
    administration_deduction: int = 12,
    moved_matches_after_first_round: int = 0,
) -> bytes:
    """One competition-rules preamble block.

    Written in the order the save lays it out: the bytes legacy read a club count and an
    administration deduction from (which no fixed offset from the marker carries on the
    corpus, so fmsave does not read them); the promotion quad twice, `promotion, playoff,
    an unidentified byte, relegation`, ending right before the marker; the 15-byte marker;
    one filler byte, so the body starts 16 bytes after the marker; the u32 tie-break count
    and that many bytes; the u32 prize count and that many u32 prizes; the u32 round count;
    and the 15-byte round records, whose first byte is the round count's own (always zero)
    high byte.

    Each mapping in `rounds` may carry `day_of_year`, `year`, `match_count`, `kind`, `b5`
    and `stored_number`, which defaults to the round's index, so the first round numbers 1.
    With `double_quad=False` the second copy of the quad differs in its first byte.
    `moved_matches_after_first_round` writes that many 10-byte interstitial blocks after the
    first round record, which a reader must step over.

    Raises:
        ValueError: The first round record's `kind` byte is not zero, which is where the
            round count's high byte sits.
    """
    output = bytearray()
    output.extend(CLUB_COUNT_MARKER)
    output.append(club_count)
    output.extend(bytes([len(rounds) & 0xFF, 0xFF, administration_deduction]))

    quad = bytes([promotion, playoff, promotion_byte2, relegation])
    second_quad = quad if double_quad else bytes([(promotion + 1) & 0xFF, *quad[1:]])
    output.extend(quad)
    output.extend(second_quad)
    output.extend(RULES_MARKER)
    output.extend(bytes(RULES_BODY_OFFSET - len(RULES_MARKER)))

    output.extend(struct.pack("<I", len(tie_breaks)))
    output.extend(bytes(tie_breaks))
    output.extend(struct.pack("<I", len(prize_money)))
    for prize in prize_money:
        output.extend(struct.pack("<I", prize))

    packed_rounds = bytearray()
    for index, round_fields in enumerate(rounds):
        packed_rounds.extend(
            round_record_bytes(
                stored_number=round_fields.get("stored_number", index),
                day_of_year=round_fields.get("day_of_year", 1),
                year=round_fields.get("year", 2031),
                match_count=round_fields.get("match_count", 0),
                kind=round_fields.get("kind", 0),
                b5=round_fields.get("b5", 0),
            )
        )
        if index == 0:
            for _ in range(moved_matches_after_first_round):
                packed_rounds.extend(moved_match_bytes())
    output.extend(struct.pack("<I", len(rounds)))
    if packed_rounds:
        if packed_rounds[0] != 0:
            raise ValueError(
                "the first round record's kind byte doubles as the round count's high byte, "
                "so it must be zero"
            )
        output.extend(packed_rounds[1:])
    return bytes(output)


def span_payloads(*blocks: bytes, separator_bytes: int = SPAN_SEPARATOR_BYTES) -> bytes:
    """The blocks back to back, separated by `separator_bytes` zero bytes."""
    return bytes(separator_bytes).join(blocks)


def span_frames(payloads: Sequence[bytes]) -> tuple[bytes, ...]:
    """Each payload as its own zstd frame, ready for `SectionFrame.unlisted_frames_after`."""
    return tuple(zstd.compress(payload) for payload in payloads)
