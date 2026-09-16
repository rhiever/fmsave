"""In-memory `game_db` fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail
tests built here. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import cast

from tests.fixtures.container import length_prefixed, packed_date, section_body

NAME_POOL_SIGNATURE = struct.pack("<6I", 46421, 0, 1024, 256, 2048, 0)
CLUB_RECORD_ANCHOR = b"\xff\xff\xff\xff"
NULL_DATE = packed_date(1, 1900)
TEAM_LIST_FLOATS = (0.0, 0.0, 0.0, 0.0, 1.0)
TEAM_LIST_FILLER = b"\x11" * 9
STATUS_RECORD_BYTES = 86
STATUS_UID_AT = 18
NORMAL_STATUS_KIND = 0x0A
STUB_STATUS_KIND = 0x0B


def name_pools_bytes(
    first_names: Sequence[str],
    surnames: Sequence[str],
    common_names: Sequence[str],
    *,
    signature: bytes = NAME_POOL_SIGNATURE,
    id_override: dict[tuple[int, int], int] | None = None,
) -> bytes:
    """The signature, then the three pools back to back.

    Each pool is a u32 entry count followed by entries of u32 id, u32 byte length and
    the UTF-8 name. `id_override` maps (pool number, index) to a stored id that differs
    from the index.
    """
    wrong_ids = id_override or {}
    output = bytearray(signature)
    for pool_number, pool_names in enumerate((first_names, surnames, common_names)):
        output.extend(struct.pack("<I", len(pool_names)))
        for entry_index, pool_name in enumerate(pool_names):
            encoded_name = pool_name.encode("utf-8")
            stored_id = wrong_ids.get((pool_number, entry_index), entry_index)
            output.extend(struct.pack("<II", stored_id, len(encoded_name)))
            output.extend(encoded_name)
    return bytes(output)


def team_list_bytes(
    team_ids: Sequence[int],
    *,
    affiliate_team_ids: Sequence[int] = (),
    float_anchor_only: bool = False,
) -> bytes:
    """The block that ends in a club's team ids and its affiliated-team ids.

    Three dates, 5 unknown bytes, five floats, one 25-byte entry, one 12-byte entry, 9 filler
    bytes, the team count and the ids, then the affiliated-team count and those ids. The dates
    are null unless `float_anchor_only`, in which case only the fifth float (1.0) can locate
    the block.
    """
    output = bytearray()
    if float_anchor_only:
        output.extend(packed_date(10, 2030) * 3)
    else:
        output.extend(NULL_DATE * 3)
    output.extend(bytes(5))
    output.extend(struct.pack("<5f", *TEAM_LIST_FLOATS))
    output.extend(b"\x01" + b"\x02" + bytes(24))
    output.extend(b"\x01" + b"\x01" + bytes(11))
    output.extend(TEAM_LIST_FILLER)
    output.append(len(team_ids))
    output.extend(struct.pack(f"<{len(team_ids)}I", *team_ids))
    output.append(len(affiliate_team_ids))
    output.extend(struct.pack(f"<{len(affiliate_team_ids)}I", *affiliate_team_ids))
    return bytes(output)


def club_record_names_end(name: str, short_name: str) -> int:
    """The record offset just after the short name."""
    return 39 + len(length_prefixed(name)) + len(length_prefixed(short_name))


def club_record_bytes(
    *,
    club_index: int,
    uid: int,
    nation_id: int,
    fa_nation_id: int,
    city_id: int,
    name: str,
    short_name: str,
    team_ids: Sequence[int],
    affiliate_team_ids: Sequence[int] = (),
    float_anchor_only: bool = False,
) -> bytes:
    """One club record: fixed header, both names, 16 zero bytes, then the team list block.

    The index and uid are stored minus 1, the league nation twice, and the anchor sits at
    record offset 17. `affiliate_team_ids` are the teams of other clubs this club controls.
    """
    output = bytearray()
    output.extend(struct.pack("<III", club_index - 1, uid - 1, uid - 1))
    output.append(0)
    output.extend(struct.pack("<I", nation_id))
    output.extend(CLUB_RECORD_ANCHOR)
    output.extend(struct.pack("<III", fa_nation_id, nation_id, city_id))
    output.extend(bytes(6))
    output.extend(length_prefixed(name))
    output.extend(length_prefixed(short_name))
    output.extend(bytes(16))
    output.extend(
        team_list_bytes(
            team_ids,
            affiliate_team_ids=affiliate_team_ids,
            float_anchor_only=float_anchor_only,
        )
    )
    return bytes(output)


def status_record_bytes(
    *,
    ordinal: int,
    club_index: int,
    uid: int,
    kind: int,
    last_league_position: int,
    reputation: int,
) -> bytes:
    """One 86-byte club-status record whose doubled uid starts at offset 18.

    Offset 0 holds the club index minus 1 followed by 10 zero bytes, and offset 14 the ordinal.
    """
    output = bytearray(STATUS_RECORD_BYTES)
    struct.pack_into("<I", output, 0, club_index - 1)
    struct.pack_into("<I", output, STATUS_UID_AT - 4, ordinal)
    struct.pack_into("<II", output, STATUS_UID_AT, uid - 1, uid - 1)
    output[STATUS_UID_AT + 8] = kind
    output[STATUS_UID_AT + 10] = last_league_position
    struct.pack_into("<H", output, STATUS_UID_AT + 11, reputation)
    return bytes(output)


def game_db_body(
    club_records: Sequence[bytes], status_records: Sequence[bytes], *, gap_bytes: int = 70_000
) -> bytes:
    """64 zero bytes, the club records, `gap_bytes` zero bytes, then the status records."""
    return bytes(64) + b"".join(club_records) + bytes(gap_bytes) + b"".join(status_records)


PLAYER_RECORD_MARKER = bytes.fromhex("01006c07")
PLAYER_RECORD_BODY_BYTES = 300


PERSON_BLOCK_UNIDENTIFIED_DATE = packed_date(1, 1900)
PERSON_BLOCK_FILLER_BYTE = 0x21
DEFAULT_PERSON_BLOCK_CLUTTER = b"\x00" * 120

# Bytes between the block start and the birth date4: the unidentified date (4) plus its zero
# byte (1), the u64 trait bits (8), three name ids each followed by a zero byte (5 * 3 = 15),
# and the legal-name length word (4). The legal name text itself (its byte length) follows.
_PERSON_BLOCK_HEADER_BYTES = 5 + 8 + 15 + 4


def relation_entry_bytes(referenced: int, kind: int, role: int, qualifier: int = 100) -> bytes:
    """One 16-byte relation entry: referenced value, kind, role, qualifier, then 0xFF."""
    output = bytearray(16)
    struct.pack_into("<I", output, 0, referenced)
    output[10] = kind
    output[11] = role
    output[12] = qualifier
    output[15] = 0xFF
    return bytes(output)


def person_block_birth_offset(
    legal_name: str | None, clutter: bytes = DEFAULT_PERSON_BLOCK_CLUTTER
) -> int:
    """The birth date4's offset inside a `person_block_bytes` result, for a given legal name
    and clutter length; callers must derive this rather than hard-coding it.
    """
    legal_name_length = 0 if legal_name is None else len(legal_name.encode("utf-8"))
    return len(clutter) + _PERSON_BLOCK_HEADER_BYTES + legal_name_length


def person_block_bytes(
    *,
    first_name_id: int,
    surname_id: int,
    common_name_id: int,
    legal_name: str | None,
    birth: bytes,
    nation_id: int,
    personality: Sequence[int],
    trait_bits: int,
    relations: Sequence[bytes],
    clutter: bytes = DEFAULT_PERSON_BLOCK_CLUTTER,
) -> bytes:
    """A person block, in the order fmsave's reader expects: clutter, then trait bits, name
    ids, legal name, birth date, filler, nation id, personality, city filler, and the
    relation list. The 120 zero bytes of clutter keep the block after rec+100.
    """
    encoded_legal_name = b"" if legal_name is None else legal_name.encode("utf-8")
    legal_name_length = len(encoded_legal_name)

    output = bytearray(clutter)
    output.extend(PERSON_BLOCK_UNIDENTIFIED_DATE)
    output.append(0)
    output.extend(struct.pack("<Q", trait_bits))
    for name_id in (first_name_id, surname_id, common_name_id):
        output.extend(struct.pack("<I", name_id))
        output.append(0)
    output.extend(struct.pack("<I", legal_name_length))
    output.extend(encoded_legal_name)
    output.extend(birth)
    output.extend(bytes([PERSON_BLOCK_FILLER_BYTE]) * 9)
    output.extend(struct.pack("<H", nation_id))
    output.extend(bytes(6))
    output.extend(bytes(personality))
    output.extend(struct.pack("<H", 0))
    output.extend(bytes(6))
    output.append(1 if relations else 0)
    output.append(len(relations))
    for relation in relations:
        output.extend(relation)
    return bytes(output)


def player_record_bytes(
    *,
    pindex: int,
    uid: int,
    current_ability: int,
    potential_ability: int,
    bucket: int,
    home_reputation: int,
    current_reputation: int,
    world_reputation: int,
    team_id: int,
    ratings: Sequence[int],
    raw_attributes: Sequence[int],
    transfer_value_raw: int,
    join_date: bytes,
    sharpness: int,
    condition: int,
    height_cm: int,
    marker: bytes = PLAYER_RECORD_MARKER,
    doubled_uid: bool = True,
    trailing: bytes = b"",
) -> bytes:
    """One player record fragment: a header, the doubled uid, reputations, the record body.

    The record itself starts 26 bytes into the returned bytes. Every offset inside the body
    counts from that start; unlisted bytes are 0. `marker` is written at offset 102 (the scan
    marker for accepted records, or a real date for a marker-less record).
    """
    header = bytearray(b"\x00\x40\x00\x00\x00\x00\x00")
    header.extend(struct.pack("<I", pindex))
    second_uid = uid if doubled_uid else uid + 1
    header.extend(struct.pack("<II", uid, second_uid))
    header.append(0)
    header.extend(struct.pack("<HHH", home_reputation, current_reputation, world_reputation))

    body = bytearray(PLAYER_RECORD_BODY_BYTES)
    struct.pack_into("<H", body, 0, current_ability)
    struct.pack_into("<h", body, 2, potential_ability)
    body[8] = bucket
    struct.pack_into("<I", body, 16, team_id)
    body[24 : 24 + len(ratings)] = bytes(ratings)
    body[39 : 39 + len(raw_attributes)] = bytes(raw_attributes)
    struct.pack_into("<I", body, 93, transfer_value_raw)
    body[98 : 98 + len(join_date)] = join_date
    body[102 : 102 + len(marker)] = marker
    struct.pack_into("<H", body, 106, sharpness)
    struct.pack_into("<H", body, 110, condition)
    body[121] = height_cm

    return bytes(header) + bytes(body) + trailing


# Contract chain records: fixed byte layout, written directly here (never imported from
# fmsave) so a wrong offset inside fmsave has to fail a test built from this module.
CONTRACT_TAG = bytes.fromhex("01006c07")
CONTRACT_NULL_DATE = packed_date(1, 1900)
CONTRACT_PADDING_BYTE = 0x22
_CONTRACT_LEADING_PADDING_BYTES = 48
_CONTRACT_HEAD_SPAN_BYTES = 19  # u16 gate + u8 type + 3 u32 money words + a 4-byte null date
_CONTRACT_HEAD_GATE_VALUE = 5
CONTRACT_CLAUSE_MARKER = b"\xff" * 8
_COMPETITION_BONUS_FILLER_BYTE = 0x33


def clause_bonus_lists_bytes(
    *,
    competition_bonuses: Sequence[tuple[int, int]] = (),
    award_bonuses: Sequence[tuple[int, int]] | None = None,
) -> bytes:
    """The bytes a clause table stores after its last entry, up to the tail start.

    Written forward: a count byte, then one 31-byte item per `(competition_id, value)` in
    `competition_bonuses` (`01 00`, a null-date tag, the u32 competition id, the u32 value and 17
    bytes of `_COMPETITION_BONUS_FILLER_BYTE`); then an award flag byte, 0 when `award_bonuses` is
    None, else 1 followed by a u32 count and one 15-byte item per `(award_id, value)` (`01 00`,
    the u32 award id, a zero u32, the u32 value and a zero byte); then two zero bytes. With no
    bonuses at all these are the four zero bytes a plain clause table ends with.
    """
    output = bytearray([len(competition_bonuses)])
    for competition_id, value in competition_bonuses:
        output.extend(b"\x01\x00" + CONTRACT_TAG)
        output.extend(struct.pack("<II", competition_id, value))
        output.extend([_COMPETITION_BONUS_FILLER_BYTE] * 17)
    if award_bonuses is None:
        output.append(0)
    else:
        output.append(1)
        output.extend(struct.pack("<I", len(award_bonuses)))
        for award_id, value in award_bonuses:
            output.extend(b"\x01\x00")
            output.extend(struct.pack("<III", award_id, 0, value))
            output.append(0)
    output.extend(bytes(2))
    return bytes(output)


def contract_bytes(
    *,
    selector: int,
    team_id: int,
    wage: int,
    start: bytes,
    tail: dict[str, object] | None,
    clauses: Sequence[tuple[int, int, int]] = (),
    head: dict[str, int] | None = None,
    events: int = 0,
    clause_table: bool = True,
    clause_marker: bytes = CONTRACT_CLAUSE_MARKER,
    clause_suffix: bytes | None = None,
    marker: bytes = CONTRACT_TAG,
) -> tuple[bytes, int]:
    """One contract chain record: the blob, and the offset of its tag (`M`) inside it.

    Built forward, in the order the format lays it out: `_CONTRACT_LEADING_PADDING_BYTES`
    of `CONTRACT_PADDING_BYTE`; then, only when `tail` is given, the head span (real head
    fields when `head` is given, `CONTRACT_PADDING_BYTE` otherwise, so the head gate never
    reads 5 by accident), the clause table (the 8-byte `clause_marker`, `00` x 3, the count
    byte, the clause entries, and `clause_suffix`, which defaults to
    `clause_bonus_lists_bytes()`: empty bonus lists) when `clause_table` is true, the 46-byte
    tail block, and `events` 29-byte event records (their content is never read); then,
    always, one padding byte, the start `date4`, 12 padding bytes and 3 zero bytes (`M-3`);
    then the 40-byte tag record itself. The head's own 4-byte null date is written as
    `CONTRACT_TAG`, since that is what a null `date4` reads as, so it looks like a second
    chain-record tag inside the record; its selector (the 4 bytes right after it) is
    whatever clause-table byte follows, never the player's own selector.

    `tail` keys: `end` (bytes, default the null date), `status`, `e2`, `e8`, `e12`, `e16`,
    `e20`, `e24`, `e37`, `e38`, `e39` (defaulting to 0 except `e2`, which defaults to
    0x0300), and `break_tail` (bool; when true, the u32 that the tail locator requires to
    be 4 is written 5 instead, so no candidate offset parses). `head` keys: `type`,
    `money_a`, `money_b`, `money_c`. Pass `tail=None` for a record with no tail at all;
    pass `clause_table=False` to omit the clause table even with a tail. `clause_marker`
    is written as given (`FF` x 8 by default, or a u32 team id and a zero u32), and so is
    `clause_suffix`, so a test can write a malformed marker or bonus list. `marker` is the
    4 bytes written at `M` itself, the chain tag by default, or a `date4` for a record the
    save marks with a date instead.
    """
    if len(clause_marker) != 8:
        raise ValueError("clause_marker must be 8 bytes")
    buffer = bytearray([CONTRACT_PADDING_BYTE]) * _CONTRACT_LEADING_PADDING_BYTES

    if tail is not None:
        if head is not None:
            buffer.extend(struct.pack("<HB", _CONTRACT_HEAD_GATE_VALUE, head.get("type", 0)))
            buffer.extend(
                struct.pack(
                    "<III", head.get("money_a", 0), head.get("money_b", 0), head.get("money_c", 0)
                )
            )
            buffer.extend(CONTRACT_TAG)  # the base-20 field is itself a null-date tag
        else:
            buffer.extend([CONTRACT_PADDING_BYTE] * _CONTRACT_HEAD_SPAN_BYTES)

        if clause_table:
            clause_count = len(clauses)
            buffer.extend(clause_marker)
            buffer.extend(bytes(3))
            buffer.append(clause_count)
            for value, parameter, kind in clauses:
                buffer.extend(
                    struct.pack("<IHH", value & 0xFFFFFFFF, parameter & 0xFFFF, kind & 0xFFFF)
                )
            buffer.extend(clause_bonus_lists_bytes() if clause_suffix is None else clause_suffix)

        tail_offset = len(buffer)
        buffer.extend(bytes(46))
        e2_value = tail.get("e2", 0x0300)
        struct.pack_into("<H", buffer, tail_offset + 2, cast(int, e2_value))
        buffer[tail_offset + 3] = 3  # the tail locator always finds this byte equal to 3
        struct.pack_into("<I", buffer, tail_offset + 4, 5 if tail.get("break_tail") else 4)
        struct.pack_into("<I", buffer, tail_offset + 8, cast(int, tail.get("e8", 0)))
        struct.pack_into("<I", buffer, tail_offset + 12, cast(int, tail.get("e12", 0)))
        struct.pack_into("<I", buffer, tail_offset + 16, cast(int, tail.get("e16", 0)))
        struct.pack_into("<I", buffer, tail_offset + 20, cast(int, tail.get("e20", 0)))
        struct.pack_into("<I", buffer, tail_offset + 24, cast(int, tail.get("e24", 0)))
        end_bytes = cast("bytes | None", tail.get("end")) or CONTRACT_NULL_DATE
        buffer[tail_offset + 28 : tail_offset + 32] = end_bytes
        buffer[tail_offset + 36] = cast(int, tail.get("status", 0))
        buffer[tail_offset + 37] = cast(int, tail.get("e37", 0))
        buffer[tail_offset + 38] = cast(int, tail.get("e38", 0))
        buffer[tail_offset + 39] = cast(int, tail.get("e39", 0))
        struct.pack_into("<I", buffer, tail_offset + 42, events)

        buffer.extend(bytes(29 * events))

    buffer.append(CONTRACT_PADDING_BYTE)
    buffer.extend(start)
    buffer.extend([CONTRACT_PADDING_BYTE] * 12)
    buffer.extend(bytes(3))  # the flags byte at M-3, and two more zero bytes

    tag_offset = len(buffer)
    if len(marker) != 4:
        raise ValueError("marker must be 4 bytes")
    buffer.extend(marker)
    buffer.append(0)
    buffer.extend(struct.pack("<II", selector, team_id))
    buffer.extend(bytes(4))
    buffer.extend(struct.pack("<I", wage))
    buffer.extend(bytes(19))  # pad the tag record out to 40 bytes from tag_offset

    return bytes(buffer), tag_offset


def fallback_contract_bytes(*, end: bytes, start: bytes) -> bytes:
    """FF FF FF FF, 4 zero bytes, an end date4, a start date4, then 8 bytes of 0x33."""
    return b"\xff\xff\xff\xff" + bytes(4) + end + start + bytes([0x33]) * 8


SUSPENSION_ENTRY_BYTES = 20


def suspension_entry_bytes(*, competition_id: int, issued: bytes, e7: int, e14: int) -> bytes:
    """One 20-byte suspension entry, written forward in the order the format lays it out.

    u16 1, u16 1, `FF FF`, a zero byte, u16 `e7`, the 4-byte `issued` date, `05`, u8 `e14`,
    `FF`, u16 `competition_id`, `FF`, then a zero byte.
    """
    output = bytearray(struct.pack("<HH", 1, 1))
    output.extend(b"\xff\xff")
    output.append(0)
    output.extend(struct.pack("<H", e7))
    output.extend(issued)
    output.append(0x05)
    output.append(e14)
    output.append(0xFF)
    output.extend(struct.pack("<H", competition_id))
    output.append(0xFF)
    output.append(0)
    return bytes(output)


HUMANS_SCHEMA = 21


def humans_body(*, count: int, selector: int) -> bytes:
    """A `humans` section: u16 human count, u32 selector, then 32 zero bytes.

    The selector is the first human manager's person id plus 1.
    """
    return section_body(".dat", HUMANS_SCHEMA, struct.pack("<HI", count, selector) + bytes(32))
