"""In-memory `game_db` fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail
tests built here. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import length_prefixed, packed_date

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


def team_list_bytes(team_ids: Sequence[int], *, float_anchor_only: bool = False) -> bytes:
    """The block that ends in a club's team ids.

    Three dates, 5 unknown bytes, five floats, one 25-byte entry, one 12-byte entry, 9 filler
    bytes, the team count and the ids. The dates are null unless `float_anchor_only`, in which
    case only the fifth float (1.0) can locate the block.
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
    float_anchor_only: bool = False,
) -> bytes:
    """One club record: fixed header, both names, 16 zero bytes, then the team list block.

    The index and uid are stored minus 1, the league nation twice, and the anchor sits at
    record offset 17.
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
    output.extend(team_list_bytes(team_ids, float_anchor_only=float_anchor_only))
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
