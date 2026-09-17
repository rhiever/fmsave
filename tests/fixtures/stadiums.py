"""In-memory stadium table fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All names are fictional.

A row is 181 bytes when it carries no inline name. A named row sets bit 0x10 of the flags
byte, writes a u32 name length where the unnamed row's last 23 bytes begin, then the name, and
then those 23 bytes, so it is 185 bytes plus the name.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import packed_date

# The date every stadium row that carries no date holds: day 1 of 1900, which is before the
# earliest year a game date decodes, so it reads as no date at all.
NULL_DATE = packed_date(1, 1900)

# The row length of a stadium that carries no inline name, and the bytes a named row adds on
# top of that plus its name: the u32 length in front of the text.
STADIUM_ROW_BYTES = 181
STADIUM_NAME_LENGTH_BYTES = 4
# Bit 0x10 of the flags byte at +156 says the row carries its name inline.
STADIUM_INLINE_NAME_FLAG = 0x10
# The u32 an owner field holds when the ground belongs to no club.
STADIUM_NO_OWNER = 0xFFFFFFFF
# The word the bytes after the last row of the table begin with.
STADIUM_TABLE_TERMINATOR = 3
STADIUM_TABLE_LEADING_BYTES = 64
STADIUM_TABLE_TRAILING_BYTES = 32

# Where each field sits inside a row, counted from the row start.
_ORDINAL_AT = 0
_UID_AT = 4
_UID_COPY_AT = 8
_ZERO_BYTE_AT = 12
_ALL_SEATER_AT = 13
_U17_AT = 17
_EXPANSION_AT = 21
_U25_AT = 25
_OWNER_AT = 29
_B33_AT = 33
_CAPACITY_AT = 34
_PITCH_AT = 38
_BUILT_AT = 50
_REBUILT_AT = 54
_DATE_58_AT = 58
_PITCH_MINIMUM_AT = 67
_PITCH_MAXIMUM_AT = 71
_FLAGS_AT = 156
_NAME_LENGTH_AT = 158


def stadium_row_bytes(
    *,
    ordinal: int,
    uid: int,
    all_seater: int,
    expansion: int,
    owner_club_index: int | None,
    capacity: int,
    pitch: tuple[int, int] = (1050, 680),
    pitch_minimum: tuple[int, int] = (900, 550),
    pitch_maximum: tuple[int, int] = (1200, 900),
    built: bytes = NULL_DATE,
    rebuilt: bytes = NULL_DATE,
    date_58: bytes = NULL_DATE,
    u17: int = 0,
    u25: int = 0,
    b33: int = 0,
    flags: int = 0,
    name: str | None = None,
) -> bytes:
    """One stadium row, with the uid stored twice as the uid minus one.

    `owner_club_index=None` writes the no-owner word. With a `name`, bit 0x10 of the flags
    byte is set, the name's byte length is written at +158 and the name at +162, and the row
    is 185 bytes plus the name; without one the row is 181 bytes.
    """
    name_bytes = b"" if name is None else name.encode("utf-8")
    written_flags = flags | (STADIUM_INLINE_NAME_FLAG if name is not None else 0)
    row = bytearray(STADIUM_ROW_BYTES)
    struct.pack_into("<III", row, _ORDINAL_AT, ordinal, uid - 1, uid - 1)
    row[_ZERO_BYTE_AT] = 0
    struct.pack_into("<IIII", row, _ALL_SEATER_AT, all_seater, u17, expansion, u25)
    struct.pack_into(
        "<I", row, _OWNER_AT, STADIUM_NO_OWNER if owner_club_index is None else owner_club_index
    )
    row[_B33_AT] = b33
    struct.pack_into("<I", row, _CAPACITY_AT, capacity)
    struct.pack_into("<HH", row, _PITCH_AT, *pitch)
    row[_BUILT_AT : _BUILT_AT + len(built)] = built
    row[_REBUILT_AT : _REBUILT_AT + len(rebuilt)] = rebuilt
    row[_DATE_58_AT : _DATE_58_AT + len(date_58)] = date_58
    struct.pack_into("<HH", row, _PITCH_MINIMUM_AT, *pitch_minimum)
    struct.pack_into("<HH", row, _PITCH_MAXIMUM_AT, *pitch_maximum)
    row[_FLAGS_AT] = written_flags
    if name is None:
        return bytes(row)
    # The 23 bytes an unnamed row holds from +158 move to after the name, behind its length.
    tail = bytes(row[_NAME_LENGTH_AT:])
    return bytes(row[:_NAME_LENGTH_AT]) + struct.pack("<I", len(name_bytes)) + name_bytes + tail


def stadium_table_bytes(
    rows: Sequence[bytes],
    *,
    leading_bytes: int = STADIUM_TABLE_LEADING_BYTES,
    trailing_bytes: int = STADIUM_TABLE_TRAILING_BYTES,
) -> bytes:
    """Zero padding, the rows back to back, then the terminator word and zero padding."""
    return (
        bytes(leading_bytes)
        + b"".join(rows)
        + struct.pack("<I", STADIUM_TABLE_TERMINATOR)
        + bytes(trailing_bytes)
    )


# The example table: 101 rows whose uids run from the base plus one. Row 10 is a fully filled
# ground owned by the first club, row 20 belongs to the second and stores no capacity, row 30
# names a club index no club record holds, row 99 has no owner at all, row 100 carries an
# inline name, and row 101 is the template every save's table ends with.
CAREER_STADIUM_UID_BASE = 610_000
CAREER_STADIUM_ROW_COUNT = 101
CAREER_NAMED_STADIUM_ORDINAL = 100
CAREER_TEMPLATE_STADIUM_ORDINAL = 101
CAREER_NAMED_STADIUM = "Example Park"
CAREER_STADIUM_BUILT_DAY = 100
CAREER_STADIUM_BUILT_YEAR = 1950
CAREER_STADIUM_REBUILT_DAY = 50
CAREER_STADIUM_REBUILT_YEAR = 1990
CAREER_STADIUM_U17 = 5_000
CAREER_STADIUM_U25 = 4_000
CAREER_STADIUM_B33 = 10
# The all-seater capacity and the pitch limits the last row of a real table holds.
CAREER_TEMPLATE_ALL_SEATER = 16_777_216
CAREER_TEMPLATE_PITCH_MINIMUM = (0, 0)
CAREER_TEMPLATE_PITCH_MAXIMUM = (15_000, 65_535)
# Club indexes the example club records hold, and one no club record holds at all.
FIRST_OWNER_CLUB_INDEX = 1
SECOND_OWNER_CLUB_INDEX = 2
UNLISTED_OWNER_CLUB_INDEX = 3


def career_stadium_rows() -> list[bytes]:
    """The example table's 101 rows, in ordinal order."""
    rows: list[bytes] = []
    for ordinal in range(1, CAREER_STADIUM_ROW_COUNT + 1):
        uid = CAREER_STADIUM_UID_BASE + ordinal
        if ordinal == CAREER_TEMPLATE_STADIUM_ORDINAL:
            rows.append(
                stadium_row_bytes(
                    ordinal=ordinal,
                    uid=uid,
                    all_seater=CAREER_TEMPLATE_ALL_SEATER,
                    expansion=0,
                    owner_club_index=None,
                    capacity=0,
                    pitch_minimum=CAREER_TEMPLATE_PITCH_MINIMUM,
                    pitch_maximum=CAREER_TEMPLATE_PITCH_MAXIMUM,
                )
            )
            continue
        if ordinal == 10:
            rows.append(
                stadium_row_bytes(
                    ordinal=ordinal,
                    uid=uid,
                    all_seater=5_010,
                    expansion=6_010,
                    owner_club_index=FIRST_OWNER_CLUB_INDEX,
                    capacity=5_010,
                    built=packed_date(CAREER_STADIUM_BUILT_DAY, CAREER_STADIUM_BUILT_YEAR),
                    rebuilt=packed_date(CAREER_STADIUM_REBUILT_DAY, CAREER_STADIUM_REBUILT_YEAR),
                    u17=CAREER_STADIUM_U17,
                    u25=CAREER_STADIUM_U25,
                    b33=CAREER_STADIUM_B33,
                )
            )
            continue
        owner_club_index = None
        if ordinal == 20:
            owner_club_index = SECOND_OWNER_CLUB_INDEX
        elif ordinal == 30:
            owner_club_index = UNLISTED_OWNER_CLUB_INDEX
        rows.append(
            stadium_row_bytes(
                ordinal=ordinal,
                uid=uid,
                all_seater=5_000 + ordinal,
                expansion=6_000 + ordinal,
                owner_club_index=owner_club_index,
                capacity=0,
                name=(CAREER_NAMED_STADIUM if ordinal == CAREER_NAMED_STADIUM_ORDINAL else None),
            )
        )
    return rows
