"""Fictional nation records built independently of the reader layouts."""

from __future__ import annotations

import struct


def nation_record_bytes(nation_id: int, database_id: int, *, copy_id: int | None = None) -> bytes:
    """A record with empty lists and one entry containing four fictional strings."""
    strings = b"".join(
        struct.pack("<I", len(value)) + value for value in (b"Example", b"", b"A", b"B")
    )
    return b"".join(
        (
            bytes(5),
            struct.pack("<H", 0),
            struct.pack("<I", 0),
            struct.pack("<H", 1),
            bytes(1),
            strings,
            bytes(20),
            bytes(48),
            struct.pack("<III", 0, 0, 0),
            bytes(24),
            bytes(1),
            struct.pack("<III", 0, 0, 0),
            bytes(54),
            struct.pack(
                "<III", nation_id, database_id, database_id if copy_id is None else copy_id
            ),
        )
    )


def nation_table_bytes(count: int = 251) -> bytes:
    """A complete counted table whose database ids are fictional."""
    return struct.pack("<IB", count, 0) + b"".join(
        nation_record_bytes(nation_id, 900_000 + nation_id) for nation_id in range(count)
    )
