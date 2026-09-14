from __future__ import annotations

import struct
import sys

from tests.fixtures.container import (
    FILE_MAGIC,
    HEADER_SIZE,
    build_container_fragment,
    game_info_body,
    packed_date,
    save_summary_body,
    section_body,
)

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd


def test_header_layout() -> None:
    fragment = build_container_fragment()
    header = fragment.content[:HEADER_SIZE]
    assert header[:6] == FILE_MAGIC
    assert struct.unpack_from("<HB", header, 6) == (8, 0)
    assert struct.unpack_from("<QB", header, 17) == (17, 3)
    assert 9 + struct.unpack_from("<Q", header, 9)[0] == fragment.trailer_offset
    assert fragment.content[fragment.trailer_offset : fragment.trailer_offset + 6] == FILE_MAGIC


def test_trailer_lists_sections_relative_to_byte_26() -> None:
    fragment = build_container_fragment()
    payload = zstd.decompress(fragment.content[fragment.trailer_offset + 9 :])
    name_length = struct.unpack_from("<I", payload, 0)[0]
    assert payload[4 : 4 + name_length] == b"Example Career"
    cursor = 4 + name_length + 4
    listed: dict[str, int] = {}
    while True:
        entry_name_length = struct.unpack_from("<I", payload, cursor)[0]
        if entry_name_length == 0:
            break
        entry_name = payload[cursor + 4 : cursor + 4 + entry_name_length].decode("ascii")
        extension_at = cursor + 4 + entry_name_length
        assert struct.unpack_from("<I", payload, extension_at)[0] == 4
        extension = payload[extension_at + 4 : extension_at + 8].decode("ascii")
        relative_offset = struct.unpack_from("<Q", payload, extension_at + 8)[0]
        listed[entry_name + extension] = HEADER_SIZE + relative_offset
        cursor = extension_at + 8 + 40
    assert listed == fragment.frame_offsets
    assert "game_info.dat" in listed and "1_2_3.apm" in listed


def test_game_info_body_fields() -> None:
    body = game_info_body(
        db_version="26.10.0+0",
        build_numbers=(11, 22, 33),
        game_day_of_year=5,
        game_year=2040,
        time_slot=7,
    )
    assert body[:8] == b"\x03\x01tad." + struct.pack("<H", 46)
    base = 12 + len("26.10.0+0")
    assert struct.unpack_from("<I", body, base + 34)[0] == 11
    assert struct.unpack_from("<I", body, base + 38)[0] == 22
    assert struct.unpack_from("<I", body, base + 202)[0] == 33
    assert body[base + 172 : base + 176] == packed_date(5, 2040, 7)
    assert struct.unpack_from("<I", body, base + 206)[0] == 1


def test_summary_contains_length_prefixed_version() -> None:
    body = save_summary_body(version="26.3.2+2329565")
    position = body.find(b"26.3.2+2329565")
    assert struct.unpack_from("<I", body, position - 4)[0] == 14


def test_section_body_magic_for_cmt() -> None:
    assert section_body(".cmt", 7, b"xy") == bytes.fromhex("0301746d632e0700") + b"xy"
