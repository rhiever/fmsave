"""Bound club records by walking their counted table."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from fmsave._layouts import ClubTableLayout, RecordStep

_U32 = struct.Struct("<I")
_FOOTER = struct.Struct("<III")
_COUNTS = {1: struct.Struct("<B"), 2: struct.Struct("<H"), 4: _U32}


@dataclass(frozen=True, slots=True)
class ClubTableRecord:
    """The body, closing footer, and database identity of a walked club."""

    body_start: int
    footer_start: int
    unique_id: int
    team_counts_start: int


def _steps(data: bytes, position: int, steps: tuple[RecordStep, ...], maximum: int) -> int | None:
    for step in steps:
        count = 1
        if step.count_bytes:
            unpacker = _COUNTS[step.count_bytes]
            if position + unpacker.size > len(data):
                return None
            count = unpacker.unpack_from(data, position)[0]
            position += unpacker.size
            if count > maximum:
                return None
        position += count * (step.lead_bytes + step.tail_bytes)
        if position > len(data):
            return None
    return position


def club_record(data: bytes, body: int, layout: ClubTableLayout) -> ClubTableRecord | None:
    """Walk one club and return its bounds, or None on invalid framing."""
    if not 0 <= body < len(data):
        return None
    kind = data[body]
    if kind not in (layout.ordinary_variant, layout.extended_variant):
        return None
    cursor = body + 1 + layout.prefix_bytes
    if kind == layout.extended_variant:
        cursor += layout.extended_prefix_bytes
    for _ in range(2):
        if cursor + _U32.size > len(data):
            return None
        length = _U32.unpack_from(data, cursor)[0]
        if length > layout.max_name_bytes:
            return None
        cursor += _U32.size + length
        if cursor > len(data):
            return None
    cursor = _steps(data, cursor, layout.after_names, layout.max_entries)
    if cursor is None or cursor >= len(data):
        return None
    finance = data[cursor]
    cursor += 1
    if finance == layout.base_finance_tag:
        cursor += layout.base_finance_bytes
    elif finance == layout.full_finance_tag:
        cursor = _steps(data, cursor, layout.full_finance, layout.max_entries)
    elif finance != layout.empty_finance_tag:
        return None
    if cursor is None or cursor > len(data):
        return None
    team_counts_start = cursor
    cursor = _steps(data, cursor, layout.after_finance, layout.max_entries)
    if cursor is None or cursor + _FOOTER.size > len(data):
        return None
    uid = _FOOTER.unpack_from(data, cursor)[1]
    return ClubTableRecord(body, cursor, uid, team_counts_start)


def walk_club_table(
    data: bytes, header: int, layout: ClubTableLayout
) -> tuple[ClubTableRecord, ...] | None:
    """Walk every counted club, checking ordinal order and distinct database IDs."""
    if header < 0 or header + layout.header_bytes > len(data):
        return None
    count = _U32.unpack_from(data, header)[0]
    if not layout.count_range[0] <= count <= layout.count_range[1]:
        return None
    if data[header + _U32.size] != 0 or count > len(data) // _FOOTER.size:
        return None
    cursor = header + layout.header_bytes
    rows: list[ClubTableRecord] = []
    seen: set[int] = set()
    for ordinal in range(count):
        row = club_record(data, cursor, layout)
        if row is None:
            return None
        stored, uid, _ = _FOOTER.unpack_from(data, row.footer_start)
        if stored != ordinal or uid in (0, 0xFFFFFFFF) or uid in seen:
            return None
        seen.add(uid)
        rows.append(row)
        cursor = row.footer_start + _FOOTER.size
    return tuple(rows)
