"""Byte builders for the `training_man` section: team blocks, weeks, groups and the library.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All ids, labels and schedule names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import length_prefixed, section_body

TRAINING_SCHEMA = 31
HEADER_ENTRY_BYTES = 13
BLOCK_ENTRY_BYTES = 14
BLOCK_ENTRY_LEAD_BYTE = 5
# Measured on every save: a weekly record carries fourteen bytes after its schedule name.
WEEK_TRAILER_BYTES = 14
BLOCK_TAIL_BYTES = 36
# Measured on every save: three bytes sit between the header list and the first team block,
# the first of them the number of blocks that follow.
HEADER_GAP_BYTES = 3
# Measured on every save: the six bytes that sit immediately before a library group's count.
LIBRARY_GROUP_PREFIX = bytes([1, 1, 0, 0, 0, 1])

_WORD = struct.Struct("<I")
_DAY_SESSIONS = struct.Struct("<3H")


def day_block_bytes(sessions: tuple[int, int, int] = (11, 10, 6)) -> bytes:
    """One day of a training week: the lead byte, then its three session codes."""
    return b"\x03" + _DAY_SESSIONS.pack(*sessions)


def _seven_day_blocks() -> bytes:
    return day_block_bytes() * 7


def training_header_entry_bytes(*, selector: int, first_date: bytes, second_date: bytes) -> bytes:
    """One 13-byte entry of the per-person list the section header holds."""
    entry = b"\x01" + _WORD.pack(selector) + first_date[:4] + second_date[:4]
    if len(entry) != HEADER_ENTRY_BYTES:
        raise ValueError(f"a header entry is {HEADER_ENTRY_BYTES} bytes, not {len(entry)}")
    return entry


def training_week_bytes(
    *,
    week_start: bytes,
    schedule_name: str,
    after_name: bytes = bytes(WEEK_TRAILER_BYTES),
) -> bytes:
    """One weekly record: the lead byte, the week's start date, then its schedule name."""
    record = bytearray(b"\x0b")
    record.extend(week_start[:4])
    record.append(1)
    record.extend(_seven_day_blocks())
    record.extend(length_prefixed(schedule_name))
    record.extend(after_name)
    return bytes(record)


def mentoring_group_bytes(*, number: int, label: str, member_selectors: Sequence[int]) -> bytes:
    """One mentoring group: its number, its stored label, then its member selectors."""
    group = bytearray(b"\x01")
    group.extend(_WORD.pack(number))
    group.append(4)
    group.extend(length_prefixed(label))
    group.extend(_WORD.pack(len(member_selectors)))
    for selector in member_selectors:
        group.extend(_WORD.pack(selector))
    return bytes(group)


def training_block_bytes(
    *,
    team_id: int,
    entries: int,
    weeks: Sequence[bytes],
    groups: Sequence[bytes],
    last: bool,
    entry_lead: int = BLOCK_ENTRY_LEAD_BYTE,
) -> bytes:
    """One team's block: its unidentified entries, its calendar, its tail and its groups.

    `last` leaves out the zero byte that separates one block from the next, which is what the
    section's own last block does. `entry_lead` replaces the byte every entry starts with, so a
    test can hand the walk entries it must turn away.
    """
    block = bytearray(_WORD.pack(team_id))
    block.append(1)
    block.extend(_WORD.pack(entries))
    block.extend((bytes((entry_lead,)) + b"\x11" * (BLOCK_ENTRY_BYTES - 1)) * entries)
    block.extend(_WORD.pack(len(weeks)))
    for week in weeks:
        block.extend(week)
    block.extend(bytes(BLOCK_TAIL_BYTES))
    block.extend(_WORD.pack(len(groups)))
    for group in groups:
        block.extend(group)
    if not last:
        block.append(0)
    return bytes(block)


def schedule_library_bytes(entries: Sequence[tuple[str, int, str]]) -> bytes:
    """One count-prefixed group of saved schedules, each `(folder, id, name)`."""
    group = bytearray(LIBRARY_GROUP_PREFIX)
    group.extend(_WORD.pack(len(entries)))
    for folder, schedule_id, name in entries:
        group.append(5)
        group.extend(_WORD.pack(1))
        group.append(1)
        group.extend(_seven_day_blocks())
        group.extend(length_prefixed(folder))
        group.extend(_WORD.pack(schedule_id))
        group.extend(length_prefixed(name))
    return bytes(group)


def training_man_body(
    *,
    header_entries: Sequence[bytes],
    blocks: Sequence[bytes],
    after_blocks: bytes = b"",
    header_gap: bytes | None = None,
    schema: int = TRAINING_SCHEMA,
) -> bytes:
    """The whole `training_man` section: the header list, the blocks, then anything after them.

    `header_gap` replaces the three bytes the section holds between the header list and the
    first block, so a test can shift where the blocks begin.
    """
    payload = bytearray(_WORD.pack(581))
    payload.extend(_WORD.pack(1))
    payload.extend(b"\x5a" * 10)
    payload.extend(_WORD.pack(len(header_entries)))
    for entry in header_entries:
        payload.extend(entry)
    if header_gap is None:
        header_gap = bytes((len(blocks) & 0xFF, 0, 0))
    payload.extend(header_gap)
    for block in blocks:
        payload.extend(block)
    payload.extend(after_blocks)
    return section_body(".dat", schema, bytes(payload))
