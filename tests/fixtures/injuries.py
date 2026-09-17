"""Byte builders for the injury structures, written from observed format facts.

The injury-type name table is not in any section: every per-match directory entry of a save
carries one copy of it, a few hundred bytes into the entry's payload. `match_file_body` builds
such a payload, so a wrong offset or a wrong record shape inside fmsave has to fail the tests
built here.

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
