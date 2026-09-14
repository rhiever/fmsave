"""The save container: header, trailer directory, regions, fingerprint and frame reads.

A save is a 26-byte header, a run of Zstandard frames, and a trailer holding one
frame whose payload lists the named frames (the directory). No file handle or
memory map outlives a call: every function that reads frames reopens the file and
checks the fingerprint recorded by `read_index`, so a save rewritten by the game is
reported instead of misread.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

from fmsave._errors import CorruptSaveError, NotAFmSaveError
from fmsave._scan import read_length_prefixed_string, read_u32, read_u64

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

FILE_MAGIC = b"\x02\x01fmf."
HEADER_SIZE = 26
TRAILER_POINTER_AT = 9
TRAILER_HEADER_SIZE = 9
FRAME_BASE = 26
SECTION_EXTENSIONS = frozenset({".dat", ".cmt"})
DEFAULT_TOTAL_DECOMPRESSED_CAP = 4 * 1024**3
DEFAULT_FRAME_DECOMPRESSED_CAP = 1024**3
MAX_TRAILER_COMPRESSED_BYTES = 64 * 1024**2
MAX_TRAILER_DECOMPRESSED_BYTES = 64 * 1024**2
MAX_SAVE_NAME_BYTES = 4096
MAX_ENTRY_NAME_BYTES = 256
ENTRY_FIXED_TAIL_BYTES = 40
ENTRY_NAME_PATTERN = re.compile(rb"[A-Za-z0-9_]+")
EXTENSION_PATTERN = re.compile(rb"\.[A-Za-z0-9]{3}")
UNLISTED_REGION_PREFIX = "unlisted_after_"
RETRY_HINT = "If the game was saving, wait for it to finish or copy the file, then try again."


@dataclass(frozen=True, slots=True)
class ContainerLimits:
    """Caps that bound memory use on hostile or damaged input."""

    total_decompressed_cap: int = DEFAULT_TOTAL_DECOMPRESSED_CAP
    frame_decompressed_cap: int = DEFAULT_FRAME_DECOMPRESSED_CAP


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One named frame listed in the trailer directory."""

    name: str
    extension: str
    frame_offset: int
    compressed_size: int
    decompressed_size: int
    trailing_values: tuple[int, int]

    @property
    def is_section(self) -> bool:
        return self.extension in SECTION_EXTENSIONS

    @property
    def frame_end(self) -> int:
        return self.frame_offset + self.compressed_size


@dataclass(frozen=True, slots=True)
class Region:
    """A byte range of the file: one section frame, or an unlisted run of frames."""

    name: str
    start: int
    end: int
    entry: DirectoryEntry | None


@dataclass(frozen=True, slots=True)
class Fingerprint:
    file_size: int
    mtime_ns: int
    header_digest: str


@dataclass(frozen=True, slots=True)
class ContainerIndex:
    path: Path
    fingerprint: Fingerprint
    save_name: str
    trailer_offset: int
    entries: tuple[DirectoryEntry, ...]
    sections: Mapping[str, DirectoryEntry] = field(compare=False)
    regions: Mapping[str, Region] = field(compare=False)
    limits: ContainerLimits = field(default_factory=ContainerLimits)

    @property
    def file_name(self) -> str:
        return self.path.name


def read_exact(save_file: BinaryIO, offset: int, length: int, file_name: str) -> bytes:
    save_file.seek(offset)
    data = save_file.read(length)
    if len(data) != length:
        raise CorruptSaveError(
            f"{file_name} ended early while reading {length} bytes at offset {offset}. {RETRY_HINT}"
        )
    return data


def decompress_frame(
    compressed: bytes, *, expected_size: int | None, cap: int, what: str, file_name: str
) -> bytes:
    """Decompress exactly one frame without ever producing more than the allowed bytes."""
    output_limit = cap if expected_size is None else min(expected_size, cap)
    decompressor = zstd.ZstdDecompressor()
    try:
        data = decompressor.decompress(compressed, max_length=output_limit + 1)
    except zstd.ZstdError as error:
        raise CorruptSaveError(
            f"{file_name}: {what} could not be decompressed. {RETRY_HINT}"
        ) from error
    if len(data) > output_limit:
        raise CorruptSaveError(
            f"{file_name}: {what} decompresses to more than {output_limit} bytes"
        )
    if not decompressor.eof:
        raise CorruptSaveError(f"{file_name}: {what} is truncated. {RETRY_HINT}")
    if decompressor.unused_data:
        raise CorruptSaveError(f"{file_name}: {what} has unexpected bytes after its frame")
    if expected_size is not None and len(data) != expected_size:
        raise CorruptSaveError(
            f"{file_name}: {what} decompressed to {len(data)} bytes, expected {expected_size}"
        )
    return data


def trailer_digest(header: bytes, trailer_bytes: bytes) -> str:
    return hashlib.sha256(header + trailer_bytes).hexdigest()


def read_index(
    path: str | os.PathLike[str], limits: ContainerLimits | None = None
) -> ContainerIndex:
    """Read the header and trailer directory; the file is closed before this returns."""
    save_path = Path(path)
    file_name = save_path.name
    effective_limits = limits or ContainerLimits()
    with save_path.open("rb") as save_file:
        file_status = os.fstat(save_file.fileno())
        file_size = file_status.st_size
        header = save_file.read(HEADER_SIZE)
        if len(header) < len(FILE_MAGIC) or header[: len(FILE_MAGIC)] != FILE_MAGIC:
            raise NotAFmSaveError(f"{file_name} is not a Football Manager save")
        if len(header) < HEADER_SIZE:
            raise CorruptSaveError(f"{file_name} is too short to be a save. {RETRY_HINT}")
        trailer_offset = TRAILER_POINTER_AT + read_u64(header, TRAILER_POINTER_AT)
        if not HEADER_SIZE <= trailer_offset < file_size - TRAILER_HEADER_SIZE:
            raise CorruptSaveError(f"{file_name}: the save directory is missing. {RETRY_HINT}")
        if file_size - trailer_offset - TRAILER_HEADER_SIZE > MAX_TRAILER_COMPRESSED_BYTES:
            raise CorruptSaveError(f"{file_name}: the save directory is implausibly large")
        trailer_bytes = read_exact(save_file, trailer_offset, file_size - trailer_offset, file_name)
    if trailer_bytes[: len(FILE_MAGIC)] != FILE_MAGIC:
        raise CorruptSaveError(f"{file_name}: the save directory is damaged. {RETRY_HINT}")
    trailer_compressed = trailer_bytes[TRAILER_HEADER_SIZE:]
    trailer_payload = decompress_frame(
        trailer_compressed,
        expected_size=None,
        cap=MAX_TRAILER_DECOMPRESSED_BYTES,
        what="the save directory",
        file_name=file_name,
    )
    save_name, entries = parse_directory(trailer_payload, file_name)
    validate_entries(entries, trailer_offset, effective_limits, file_name)
    sections = {entry.name: entry for entry in entries if entry.is_section}
    if len(sections) != sum(entry.is_section for entry in entries):
        raise CorruptSaveError(f"{file_name}: the save directory lists a section twice")
    return ContainerIndex(
        path=save_path,
        fingerprint=Fingerprint(
            file_size=file_size,
            mtime_ns=file_status.st_mtime_ns,
            header_digest=trailer_digest(header, trailer_bytes),
        ),
        save_name=save_name,
        trailer_offset=trailer_offset,
        entries=entries,
        sections=MappingProxyType(sections),
        regions=MappingProxyType(build_regions(entries, trailer_offset, file_name)),
        limits=effective_limits,
    )


def parse_directory(
    trailer_payload: bytes, file_name: str
) -> tuple[str, tuple[DirectoryEntry, ...]]:
    save_name, cursor = read_length_prefixed_string(trailer_payload, 0, MAX_SAVE_NAME_BYTES)
    cursor += 4  # a u32 whose meaning is not identified
    entries: list[DirectoryEntry] = []
    while (parsed := parse_directory_entry(trailer_payload, cursor)) is not None:
        entry, cursor = parsed
        entries.append(entry)
    if not any(entry.is_section for entry in entries):
        raise CorruptSaveError(f"{file_name}: the save directory lists no sections")
    return save_name, tuple(sorted(entries, key=lambda entry: entry.frame_offset))


def parse_directory_entry(trailer_payload: bytes, cursor: int) -> tuple[DirectoryEntry, int] | None:
    """Parse one entry at `cursor`, or return None where the entry list ends."""
    if cursor + 4 > len(trailer_payload):
        return None
    name_length = read_u32(trailer_payload, cursor)
    if not 1 <= name_length <= MAX_ENTRY_NAME_BYTES:
        return None
    extension_length_at = cursor + 4 + name_length
    tail_at = extension_length_at + 8
    if tail_at + ENTRY_FIXED_TAIL_BYTES > len(trailer_payload):
        return None
    name_bytes = trailer_payload[cursor + 4 : extension_length_at]
    extension_bytes = trailer_payload[extension_length_at + 4 : tail_at]
    if (
        ENTRY_NAME_PATTERN.fullmatch(name_bytes) is None
        or read_u32(trailer_payload, extension_length_at) != 4
        or EXTENSION_PATTERN.fullmatch(extension_bytes) is None
    ):
        return None
    (
        relative_offset,
        compressed_size,
        decompressed_size,
        first_trailing_value,
        second_trailing_value,
    ) = struct.unpack_from("<5Q", trailer_payload, tail_at)
    entry = DirectoryEntry(
        name=name_bytes.decode("ascii"),
        extension=extension_bytes.decode("ascii"),
        frame_offset=FRAME_BASE + relative_offset,
        compressed_size=compressed_size,
        decompressed_size=decompressed_size,
        trailing_values=(first_trailing_value, second_trailing_value),
    )
    return entry, tail_at + ENTRY_FIXED_TAIL_BYTES


def validate_entries(
    entries: tuple[DirectoryEntry, ...],
    trailer_offset: int,
    limits: ContainerLimits,
    file_name: str,
) -> None:
    previous_end = HEADER_SIZE
    total_decompressed = 0
    for entry in entries:
        label = f"directory entry {entry.name}{entry.extension}"
        if (
            entry.compressed_size == 0
            or entry.frame_offset < previous_end
            or entry.frame_end > trailer_offset
        ):
            raise CorruptSaveError(
                f"{file_name}: {label} points outside the frame area. {RETRY_HINT}"
            )
        if entry.decompressed_size > limits.frame_decompressed_cap:
            raise CorruptSaveError(f"{file_name}: {label} is larger than the per-frame cap")
        total_decompressed += entry.decompressed_size
        previous_end = entry.frame_end
    if total_decompressed > limits.total_decompressed_cap:
        raise CorruptSaveError(f"{file_name}: the save declares more data than the total cap")


def build_regions(
    entries: tuple[DirectoryEntry, ...], trailer_offset: int, file_name: str
) -> dict[str, Region]:
    regions: dict[str, Region] = {}

    def add_region(region: Region) -> None:
        if region.name in regions:
            raise CorruptSaveError(f"{file_name}: region {region.name!r} appears twice")
        regions[region.name] = region

    cursor = HEADER_SIZE
    previous_name = "header"
    for entry in entries:
        if entry.frame_offset > cursor:
            add_region(
                Region(UNLISTED_REGION_PREFIX + previous_name, cursor, entry.frame_offset, None)
            )
        if entry.is_section:
            add_region(Region(entry.name, entry.frame_offset, entry.frame_end, entry))
            previous_name = entry.name
        else:
            previous_name = entry.name + entry.extension
        cursor = entry.frame_end
    if trailer_offset > cursor:
        add_region(Region(UNLISTED_REGION_PREFIX + previous_name, cursor, trailer_offset, None))
    return regions
