"""Fictional archived statistics and index builders, independent of production layouts."""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import section_body
from tests.fixtures.season_stats import stat_line


def history_unit(
    *,
    team: int = 70001,
    year: int = 2030,
    kind: int = 1,
    competition: int = 43,
    metadata_word: int = 0x12345678,
    metadata_flag: int = 2,
    **stats: float,
) -> bytes:
    line = stat_line(**stats)
    unit = bytearray(152)
    struct.pack_into("<IHIH", unit, 1, team, competition, metadata_word, year)
    unit[13:17] = line[2:6]
    unit[17:20] = line[11:14]
    unit[20:24] = line[15:19]
    unit[24:29] = line[6:11]
    unit[29] = line[14]
    unit[30:32] = bytes((metadata_flag, kind))
    unit[32:152] = line[19:139]
    return bytes(unit)


def history_archive(units: Sequence[bytes] = ()) -> bytes:
    return section_body(".cmt", 6, b"".join(units))


def history_index(
    lists: Sequence[Sequence[int]] = (),
    *,
    singles: Sequence[int] = (),
    free: Sequence[int] = (),
    encoded: bool = False,
) -> bytes:
    payload = bytearray(struct.pack("<I", len(singles)))
    for offset in singles:
        payload += struct.pack("<I", offset)
    payload += struct.pack("<I", len(lists))
    for offsets in lists:
        payload += struct.pack("<I", len(offsets))
        previous_word = 0
        for offset in offsets:
            word = offset if encoded else (offset - previous_word) & 0xFFFFFFFF
            payload += struct.pack("<I", word)
            previous_word = word
    payload += struct.pack("<I", len(free))
    for offset in free:
        payload += struct.pack("<I", offset)
    payload += struct.pack("<I", 152) + b"\x06\x00"
    return section_body(".dat", 4, bytes(payload))
