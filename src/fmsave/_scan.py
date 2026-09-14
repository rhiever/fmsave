"""Bounds-checked primitive reads, dates and bounded marker searches.

These are the only low-level loops over decompressed save bytes. Every read checks
its bounds first and reports problems as CorruptSaveError, so malformed input never
surfaces as struct.error or IndexError.
"""

from __future__ import annotations

import calendar
import struct
from collections.abc import Iterator
from datetime import date, timedelta

from fmsave._errors import CorruptSaveError

type Buffer = bytes | bytearray | memoryview
type SearchableBuffer = bytes | bytearray

_U8 = struct.Struct("<B")
_U16 = struct.Struct("<H")
_I16 = struct.Struct("<h")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_U64 = struct.Struct("<Q")

DAY_OF_YEAR_MASK = 0x1FF
TIME_SLOT_SHIFT = 9
EARLIEST_GAME_YEAR = 1901
LATEST_GAME_YEAR = 2200


def _check_bounds(buffer: Buffer, offset: int, size: int) -> None:
    if offset < 0 or offset + size > len(buffer):
        raise CorruptSaveError(
            f"read of {size} bytes at offset {offset} is outside a {len(buffer)}-byte buffer"
        )


def _unpack(layout: struct.Struct, buffer: Buffer, offset: int) -> int:
    _check_bounds(buffer, offset, layout.size)
    value: int = layout.unpack_from(buffer, offset)[0]
    return value


def read_u8(buffer: Buffer, offset: int) -> int:
    return _unpack(_U8, buffer, offset)


def read_u16(buffer: Buffer, offset: int) -> int:
    return _unpack(_U16, buffer, offset)


def read_i16(buffer: Buffer, offset: int) -> int:
    return _unpack(_I16, buffer, offset)


def read_u32(buffer: Buffer, offset: int) -> int:
    return _unpack(_U32, buffer, offset)


def read_i32(buffer: Buffer, offset: int) -> int:
    return _unpack(_I32, buffer, offset)


def read_u64(buffer: Buffer, offset: int) -> int:
    return _unpack(_U64, buffer, offset)


def read_length_prefixed_string(buffer: Buffer, offset: int, max_length: int) -> tuple[str, int]:
    """Read a u32 length followed by that many UTF-8 bytes; return (text, offset after it)."""
    length = read_u32(buffer, offset)
    if length > max_length:
        raise CorruptSaveError(
            f"string at offset {offset} claims {length} bytes, more than the {max_length} allowed"
        )
    text_start = offset + 4
    _check_bounds(buffer, text_start, length)
    try:
        text = bytes(buffer[text_start : text_start + length]).decode("utf-8")
    except UnicodeDecodeError as error:
        raise CorruptSaveError(f"string at offset {offset} is not valid UTF-8") from error
    return text, text_start + length


def decode_date(buffer: Buffer, offset: int) -> date | None:
    """Decode a 4-byte game date, or None for the null date and malformed values."""
    packed = read_u16(buffer, offset)
    year = read_u16(buffer, offset + 2)
    day_of_year = packed & DAY_OF_YEAR_MASK
    if not EARLIEST_GAME_YEAR <= year <= LATEST_GAME_YEAR:
        return None
    days_in_year = 366 if calendar.isleap(year) else 365
    if not 1 <= day_of_year <= days_in_year:
        return None
    return date(year, 1, 1) + timedelta(days=day_of_year - 1)


def decode_time_slot(buffer: Buffer, offset: int) -> int:
    """The intra-day slot stored in the high bits of a game date."""
    return read_u16(buffer, offset) >> TIME_SLOT_SHIFT


def _check_search(buffer: SearchableBuffer, marker: bytes, start: int, end: int) -> None:
    if not marker:
        raise ValueError("marker must not be empty")
    if start < 0 or end > len(buffer) or start > end:
        raise CorruptSaveError(
            f"search range {start}..{end} is outside a {len(buffer)}-byte buffer"
        )


def find_marker(buffer: SearchableBuffer, marker: bytes, start: int, end: int) -> int:
    """Index of the first marker lying wholly inside [start, end), or -1."""
    _check_search(buffer, marker, start, end)
    return buffer.find(marker, start, end)


def iter_markers(buffer: SearchableBuffer, marker: bytes, start: int, end: int) -> Iterator[int]:
    """Every index where the marker lies wholly inside [start, end), overlapping, in order."""
    _check_search(buffer, marker, start, end)
    position = buffer.find(marker, start, end)
    while position >= 0:
        yield position
        position = buffer.find(marker, position + 1, end)
