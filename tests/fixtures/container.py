"""In-memory container fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail
tests built here. Fragments are tiny synthetic containers with fictional content,
not game saves.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

FILE_MAGIC = bytes.fromhex("0201666d662e")
HEADER_SIZE = 26
TRAILER_HEADER = FILE_MAGIC + struct.pack("<HB", 8, 0)
SKIPPABLE_FRAME_MAGIC = 0x184D2A50


def length_prefixed(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def packed_date(day_of_year: int, year: int, time_slot: int = 0) -> bytes:
    return struct.pack("<HH", day_of_year | time_slot << 9, year)


def section_body(extension: str, schema: int, payload: bytes) -> bytes:
    return b"\x03\x01" + extension[::-1].encode("ascii") + struct.pack("<H", schema) + payload


def game_info_body(
    *,
    db_version: str = "26.2.0+0",
    build_numbers: tuple[int, int, int] = (2329565, 2329565, 2329565),
    game_day_of_year: int = 60,
    game_year: int = 2031,
    time_slot: int = 66,
    migration_names: tuple[str, ...] = ("EXAMPLE_PATCH_fm26",),
    schema: int = 46,
) -> bytes:
    version_field = length_prefixed(db_version)
    base = 8 + len(version_field)
    body = bytearray(section_body(".dat", schema, version_field))
    body.extend(bytes(base + 210 - len(body)))
    struct.pack_into("<I", body, base + 34, build_numbers[0])
    struct.pack_into("<I", body, base + 38, build_numbers[1])
    body[base + 172 : base + 176] = packed_date(game_day_of_year, game_year, time_slot)
    struct.pack_into("<I", body, base + 202, build_numbers[2])
    struct.pack_into("<I", body, base + 206, len(migration_names))
    del body[base + 210 :]
    for migration_name in migration_names:
        body.extend(length_prefixed(migration_name))
    return bytes(body)


def save_summary_body(
    *,
    version: str = "26.3.2+2329565",
    leading_strings: tuple[str, ...] = ("Alex Example", "Example League"),
    trailing_strings: tuple[str, ...] = ("Northbridge FC",),
    schema: int = 29,
) -> bytes:
    payload = b"".join(length_prefixed(text) for text in leading_strings)
    payload += struct.pack("<I", 7) + length_prefixed(version)
    payload += b"".join(length_prefixed(text) for text in trailing_strings)
    return section_body(".dat", schema, payload)


def skippable_frame(payload: bytes) -> bytes:
    return struct.pack("<II", SKIPPABLE_FRAME_MAGIC, len(payload)) + payload


@dataclass(frozen=True)
class SectionFrame:
    name: str
    body: bytes
    extension: str = ".dat"
    unlisted_frames_after: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class ContainerFragment:
    content: bytes
    frame_offsets: dict[str, int]
    trailer_offset: int

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.content)
        return path


def default_sections() -> list[SectionFrame]:
    return [
        SectionFrame("game_info", game_info_body()),
        SectionFrame("memory_pools", section_body(".dat", 3, bytes(64))),
        SectionFrame("save_game_summary", save_summary_body()),
        SectionFrame("game_db", section_body(".dat", 4000, bytes(range(256)))),
        SectionFrame(
            "non_pl_hist_ls",
            section_body(".dat", 5, bytes(16)),
            unlisted_frames_after=(
                zstd.compress(b"A" * 32),
                zstd.compress(b"B" * 48),
                skippable_frame(b"skip"),
            ),
        ),
        SectionFrame("humans", section_body(".dat", 21, bytes(32))),
        SectionFrame("tc_history_dt", section_body(".cmt", 7, bytes(24)), extension=".cmt"),
    ]


def build_container_fragment(
    sections: list[SectionFrame] | None = None,
    *,
    save_name: str = "Example Career",
    attachments: tuple[tuple[str, str, bytes], ...] = (("1_2_3", ".apm", b"attachment"),),
    declared_sizes: dict[str, tuple[int, int]] | None = None,
    trailer_unidentified: int = 300,
) -> ContainerFragment:
    chosen_sections = default_sections() if sections is None else sections
    overrides = declared_sizes or {}
    stream = bytearray()
    directory_rows: list[tuple[str, str, int, int, int]] = []
    frame_offsets: dict[str, int] = {}

    def add_listed_frame(name: str, extension: str, body: bytes) -> None:
        compressed = zstd.compress(body)
        relative_offset = len(stream)
        stream.extend(compressed)
        key = name + extension
        frame_offsets[key] = HEADER_SIZE + relative_offset
        compressed_size, decompressed_size = overrides.get(key, (len(compressed), len(body)))
        directory_rows.append(
            (name, extension, relative_offset, compressed_size, decompressed_size)
        )

    for section in chosen_sections:
        add_listed_frame(section.name, section.extension, section.body)
        for raw_frame in section.unlisted_frames_after:
            stream.extend(raw_frame)
    for attachment_name, attachment_extension, attachment_payload in attachments:
        add_listed_frame(attachment_name, attachment_extension, attachment_payload)

    trailer_payload = bytearray(length_prefixed(save_name))
    trailer_payload.extend(struct.pack("<I", trailer_unidentified))
    for name, extension, relative_offset, compressed_size, decompressed_size in reversed(
        directory_rows
    ):
        trailer_payload.extend(struct.pack("<I", len(name)) + name.encode("ascii"))
        trailer_payload.extend(struct.pack("<I", 4) + extension.encode("ascii"))
        trailer_payload.extend(
            struct.pack("<5Q", relative_offset, compressed_size, decompressed_size, 0, 0)
        )
    trailer_payload.extend(bytes(16))

    trailer_offset = HEADER_SIZE + len(stream)
    header = FILE_MAGIC + struct.pack("<HBQQB", 8, 0, trailer_offset - 9, 17, 3)
    content = header + bytes(stream) + TRAILER_HEADER + zstd.compress(bytes(trailer_payload))
    return ContainerFragment(
        content=content, frame_offsets=frame_offsets, trailer_offset=trailer_offset
    )
