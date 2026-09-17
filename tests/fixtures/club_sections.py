"""Byte builders for the small club-side sections: `feeder_man` and `job_centre`.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All ids and values are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import section_body

FEEDER_SCHEMA = 5
JOB_CENTRE_SCHEMA = 1
JOB_RECORD_BYTES = 25
JOB_RECORD_TAG = b"\x06\x00\x00"
NO_JOB_COMPETITION = 0xFFFF

_FEEDER_HEADER = struct.Struct("<HHI")
_GROUP_SIZE = struct.Struct("<I")
_CLUB_INDEX = struct.Struct("<I")
_JOB_COUNT = struct.Struct("<I")


def feeder_body(
    groups: Sequence[Sequence[int]], *, schema: int = FEEDER_SCHEMA, stored_count: int | None = None
) -> bytes:
    """The `feeder_man` section: two zero words, a group count, then the groups back to back.

    Each group is a u32 member count followed by that many u32 public club indexes, exactly as
    given. `stored_count` overrides the count written in the header, so a body can claim more
    or fewer groups than it holds.
    """
    written_count = len(groups) if stored_count is None else stored_count
    payload = bytearray(_FEEDER_HEADER.pack(0, 0, written_count))
    for group in groups:
        payload.extend(_GROUP_SIZE.pack(len(group)))
        for club_index in group:
            payload.extend(_CLUB_INDEX.pack(club_index))
    return section_body(".dat", schema, bytes(payload))


def job_record_bytes(
    *,
    team_id: int,
    role: int,
    advertised: bytes,
    date_12: bytes,
    competition_id: int,
    u20: int,
    league_position: int,
    flag: int,
    reserved_u16: int = 0,
    reserved_u8: int = 0,
    tag: bytes = JOB_RECORD_TAG,
) -> bytes:
    """One 25-byte job-centre record."""
    record = bytearray(tag[:3])
    record.extend(struct.pack("<IB", team_id, role))
    record.extend(advertised[:4])
    record.extend(date_12[:4])
    record.extend(
        struct.pack(
            "<HHHBBB", reserved_u16, competition_id, u20, league_position, reserved_u8, flag
        )
    )
    if len(record) != JOB_RECORD_BYTES:
        raise ValueError(f"a job record is {JOB_RECORD_BYTES} bytes, not {len(record)}")
    return bytes(record)


def job_centre_body(
    records: Sequence[bytes],
    *,
    schema: int = JOB_CENTRE_SCHEMA,
    trailing_bytes: bytes = b"",
    stored_count: int | None = None,
) -> bytes:
    """The `job_centre` section: a record count, then the records, then any trailing bytes.

    `stored_count` overrides the count written in the header, and `trailing_bytes` breaks the
    section's size identity, so a body can fail either of the two structural checks alone.
    """
    written_count = len(records) if stored_count is None else stored_count
    payload = _JOB_COUNT.pack(written_count) + b"".join(records) + trailing_bytes
    return section_body(".dat", schema, payload)
