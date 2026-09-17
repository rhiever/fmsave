"""Byte builders for the injury structures, written from observed format facts.

The injury-type name table is not in any section: every per-match directory entry of a save
carries one copy of it, a few hundred bytes into the entry's payload. `match_file_body` builds
such a payload, so a wrong offset or a wrong record shape inside fmsave has to fail the tests
built here.

The injury history is the other structure: one section of four fixed-stride arrays, three
lists and an eight-byte tail, all back to back, which `injury_manager_body` writes from its
parts so that a reader reading any count or stride wrong lands on the wrong bytes.

This module must never import fmsave. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import section_body

# A per-match entry carries a schema number of 1 where a section carries its own.
MATCH_FILE_SCHEMA = 1
# The bytes between a payload's magic and the table on almost every entry of a real save.
MATCH_FILE_LEADING_BYTES = 560
# What follows the table: repeats of a record whose length word is far past any name length,
# so the walk stops on the first of them.
TYPE_TABLE_TRAILER = bytes.fromhex("01ffff0000000001ffffffff") * 2
# Bytes between a decoy chain and the table, so neither walk reaches the other's records.
DECOY_GAP_BYTES = 16

# The example type table: five injuries, two of them far up the id space, one carrying the
# flag byte. Every name is fictional.
CAREER_INJURY_TYPES: tuple[tuple[int, str, int, int], ...] = (
    (5, "Example Strain", 0, 6),
    (7, "Example Knock", 1, 9),
    (8, "Example Sprain", 0, 12),
    (40, "Example Fracture", 0, 50),
    (41, "Example Bruise", 0, 51),
)
# A shorter chain written before the table, which a locator that takes the first run it finds
# returns instead of the table.
DECOY_INJURY_TYPES: tuple[tuple[int, str, int, int], ...] = (
    (1, "Decoy One", 0, 2),
    (2, "Decoy Two", 0, 3),
)


def injury_type_entry_bytes(*, type_id: int, name: str, flag: int, second_id: int) -> bytes:
    """One record of the injury-type name table."""
    return (
        struct.pack("<BHI", 1, type_id, len(name))
        + name.encode("ascii")
        + struct.pack("<BI", flag, second_id)
    )


def injury_type_entries(types: Sequence[tuple[int, str, int, int]]) -> bytes:
    """The records of `(id, name, flag, second id)` tuples, back to back."""
    return b"".join(
        injury_type_entry_bytes(type_id=type_id, name=name, flag=flag, second_id=second_id)
        for type_id, name, flag, second_id in types
    )


def match_file_body(
    entries: Sequence[bytes],
    *,
    extension: str = ".apm",
    leading_bytes: int = MATCH_FILE_LEADING_BYTES,
    decoy_entries: Sequence[bytes] = (),
) -> bytes:
    """One per-match entry payload: the magic, filler, any decoy chain, then the table."""
    payload = bytearray(bytes(leading_bytes))
    if decoy_entries:
        payload.extend(b"".join(decoy_entries))
        payload.extend(bytes(DECOY_GAP_BYTES))
    payload.extend(b"".join(entries))
    payload.extend(TYPE_TABLE_TRAILER)
    return section_body(extension, MATCH_FILE_SCHEMA, bytes(payload))


def match_file_magic_only(*, extension: str = ".apm") -> bytes:
    """A per-match entry payload with the magic and no table at all."""
    return section_body(extension, MATCH_FILE_SCHEMA, bytes(MATCH_FILE_LEADING_BYTES))


# The `injury_manager` section. Its four arrays and three lists run back to back from the
# arrays offset, so every builder below writes a count and then exactly that many fixed-size
# rows: a reader reading any one of those counts or strides wrong lands on the wrong bytes for
# everything after it.
INJURY_MANAGER_SCHEMA = 8
INJURY_MANAGER_TAIL = bytes.fromhex("010000000000ffff")
# The date word a typed row carries when it stores no date at all: day 1 of a year far below
# any year the game plays in.
NULL_DATE_WORD = bytes.fromhex("01006c07")


def injury_window_row_bytes(
    *, first: bytes, second: bytes, selector: int, last_byte: int = 0
) -> bytes:
    """One row of either window array: the lead byte, two dates, a selector and one byte."""
    return bytes((1,)) + first + second + struct.pack("<I", selector) + bytes((last_byte,))


def injury_typed_row_bytes(
    *, date: bytes, selector: int, type_id: int, r11: int, r12: int, lead: int = 1
) -> bytes:
    """One typed row: the lead byte, a date, a selector, an injury type and two bytes."""
    return bytes((lead,)) + date + struct.pack("<IHBB", selector, type_id, r11, r12)


def injury_log_row_bytes(
    *, date: bytes, selector: int, team_id: int, cause: int, severity: int, lead: int = 1
) -> bytes:
    """One log row: the lead byte, a date, a selector, a team id and two codes."""
    return bytes((lead,)) + date + struct.pack("<IIBB", selector, team_id, cause, severity)


def injury_manager_body(
    *,
    window_a: Sequence[bytes],
    window_b: Sequence[bytes],
    typed: Sequence[bytes],
    log: Sequence[bytes],
    lists: tuple[Sequence[int], Sequence[int], Sequence[tuple[int, int]]],
    tail: bytes = INJURY_MANAGER_TAIL,
    trailing_bytes: bytes = b"",
    log_count: int | None = None,
) -> bytes:
    """The whole section: four arrays, three lists, the tail, and any residue after it.

    `log_count` writes a count of its own in front of the log rows, so a test can hand the
    walk a count that does not match the rows written.
    """
    parts = bytearray()
    for rows in (window_a, window_b, typed):
        parts.extend(struct.pack("<I", len(rows)))
        parts.extend(b"".join(rows))
    parts.extend(struct.pack("<I", len(log) if log_count is None else log_count))
    parts.extend(b"".join(log))
    first_selectors, second_selectors, flagged_selectors = lists
    for selectors in (first_selectors, second_selectors):
        parts.extend(struct.pack("<I", len(selectors)))
        for selector in selectors:
            parts.extend(struct.pack("<I", selector))
    parts.extend(struct.pack("<I", len(flagged_selectors)))
    for selector, flag in flagged_selectors:
        parts.extend(struct.pack("<IB", selector, flag))
    # The first two zero bytes complete the u32 version whose low half the section header
    # carries, and the next two are the zero word that sits in front of the arrays.
    payload = b"\x00\x00" + b"\x00\x00" + bytes(parts) + tail + trailing_bytes
    return section_body(".dat", INJURY_MANAGER_SCHEMA, payload)
