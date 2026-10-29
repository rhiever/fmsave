"""Fictional counted club tables, independent of production layouts."""

from __future__ import annotations

import struct
from collections.abc import Sequence


def club_body(name: str, short_name: str, teams: Sequence[int], *, finance: int = 0) -> bytes:
    prefix = struct.pack("<4I", 3, 0xFFFFFFFF, 3, 3) + struct.pack("<I", 77) + bytes(6)
    names = b"".join(struct.pack("<I", len(v.encode())) + v.encode() for v in (name, short_name))
    if finance == 0:
        money = bytes(45)
    elif finance == 1:
        money = bytes(70) + (bytes(235) + bytes(2)) * 4 + bytes(67)
        money += bytes(1) + struct.pack("<I", 0) + bytes(71) + bytes(1) + bytes(67)
    else:
        money = b""
    refs = bytes((len(teams),)) + struct.pack(f"<{len(teams)}I", *teams)
    return (
        bytes(1)
        + prefix
        + names
        + bytes(8)
        + bytes(1)
        + bytes((finance,))
        + money
        + bytes(2)
        + bytes(9)
        + refs
        + bytes(4)
        + bytes(1)
        + bytes(2)
    )


def club_table(*, finance: int = 0) -> bytes:
    bodies = [
        club_body("Example Initial", "Initial", (71001,), finance=finance),
        club_body("Example Following", "Following", (71002,)),
    ]
    return struct.pack("<IB", 2, 0) + b"".join(
        body + struct.pack("<III", ordinal, uid, uid)
        for ordinal, (body, uid) in enumerate(zip(bodies, (6100, 6200), strict=True))
    )
