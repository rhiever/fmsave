"""Values and error-context helpers shared by the readers."""

from __future__ import annotations

import struct
from collections.abc import Sequence

from fmsave._errors import ISSUES_URL, ReaderCheckError

# The value the save stores in a u32 id or index field that refers to nothing.
MISSING_REFERENCE = 0xFFFFFFFF

# The one section every game_db reader (names, clubs, players) works from.
GAME_DB_SECTION = "game_db"


def section_label(file_name: str, section_name: str = GAME_DB_SECTION) -> str:
    """ "<file name>: section '<section name>'", the common prefix of a reader's error text."""
    return f"{file_name}: section {section_name!r}"


def layout_mismatch(
    file_name: str, detail: str, section_name: str = GAME_DB_SECTION
) -> ReaderCheckError:
    """A ReaderCheckError saying the save layout differs from what fmsave expects."""
    return ReaderCheckError(
        f"{section_label(file_name, section_name)}: {detail}, so the save layout differs from "
        f"what fmsave expects. Please report it at {ISSUES_URL}"
    )


def build_gap_padded_struct(
    fields: Sequence[tuple[int, str, str]], *, start_offset: int | None = None
) -> tuple[struct.Struct, int, dict[str, int]]:
    """One little-endian struct spanning the given (offset, format_code, name) fields.

    Fields are sorted by offset; any gap between them (or before the first one) is padded
    with `x`. Returns (struct_object, start_offset, index_by_name): start_offset is the
    offset the struct must be unpacked from, and index_by_name maps each field name to its
    position in the tuple `unpack_from` returns.

    When `start_offset` is not given, it defaults to the lowest field offset, so the struct
    carries no unnecessary leading padding. Pass an explicit `start_offset` (for example 0,
    to always unpack from a fixed anchor position such as a record start) when the caller
    needs the struct to start somewhere at or before the lowest field.

    Raises:
        ValueError: `fields` is empty, two fields overlap, or an explicit `start_offset` is
            past the lowest field offset.
    """
    if not fields:
        raise ValueError("fields must not be empty")
    sorted_fields = sorted(fields, key=lambda described_field: described_field[0])
    lowest_offset = sorted_fields[0][0]
    if start_offset is None:
        start_offset = lowest_offset
    elif start_offset > lowest_offset:
        raise ValueError(
            f"start_offset {start_offset} is past the lowest field offset {lowest_offset}"
        )
    cursor = start_offset
    format_codes: list[str] = []
    index_by_name: dict[str, int] = {}
    for position, (offset, code, name) in enumerate(sorted_fields):
        gap = offset - cursor
        if gap < 0:
            raise ValueError(f"field {name!r} at offset {offset} overlaps an earlier field")
        if gap:
            format_codes.append(f"{gap}x")
        format_codes.append(code)
        cursor = offset + struct.calcsize(code)
        index_by_name[name] = position
    return struct.Struct("<" + "".join(format_codes)), start_offset, index_by_name
