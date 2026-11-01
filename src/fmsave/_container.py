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
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

from fmsave._errors import (
    ISSUES_URL,
    CorruptSaveError,
    NotAFmSaveError,
    SaveChangedError,
)
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
# The directory entries that are not sections but hold one per-match file each. They carry the
# injury-type name table, which no section holds.
MATCH_FILE_EXTENSIONS = frozenset({".apm", ".scm"})
# Decompressed output is bounded relative to the file, not by fixed sizes, so a save opens
# however large it grows while a damaged or crafted part claiming far more than its compressed
# bytes could hold is refused before the memory is spent. Measured on 56 FM26 and FM27 saves of
# 32 MiB to 953 MiB: no part over 1 MiB expands more than 41 times and none over 64 MiB more
# than 11 times, while some nearly empty parts under 1 MiB expand over 1,000 times; no save's
# parts and unlisted frames add up to more than 4.7 times its file size.
EXPANSION_ALLOWANCE = 64 * 1024**2
MAX_PART_EXPANSION = 64
MAX_SAVE_EXPANSION = 32
# What the measured saves show, quoted when a bound is exceeded.
OBSERVED_PART_EXPANSION = 41
OBSERVED_SAVE_EXPANSION = 5
MAX_TRAILER_COMPRESSED_BYTES = 64 * 1024**2
MAX_TRAILER_DECOMPRESSED_BYTES = 64 * 1024**2
MAX_SAVE_NAME_BYTES = 4096
MAX_ENTRY_NAME_BYTES = 256
MAX_DIRECTORY_ENTRIES = 100_000
ENTRY_FIXED_TAIL_BYTES = 40
ENTRY_NAME_PATTERN = re.compile(rb"[A-Za-z0-9_]+")
EXTENSION_PATTERN = re.compile(rb"\.[A-Za-z0-9]{3}")
UNLISTED_REGION_PREFIX = "unlisted_after_"
RETRY_HINT = "If the game was saving, wait for it to finish or copy the file, then try again."
HEAD_READ_BYTES = 128 * 1024 + 32
MAX_FRAMES_PER_REGION = 1_000_000
ZSTD_FRAME_MAGIC = 0xFD2FB528
SKIPPABLE_MAGIC_FIRST = 0x184D2A50
SKIPPABLE_MAGIC_LAST = 0x184D2A5F
ZSTD_MAX_BLOCK_BYTES = 128 * 1024
BLOCK_TYPE_RLE = 1
BLOCK_TYPE_RESERVED = 3


@dataclass(frozen=True, slots=True)
class ContainerLimits:
    """Bounds on decompressed output that hold off damaged or crafted input.

    One part may decompress to `part_expansion` times its compressed size, and the whole save
    to `save_expansion` times the file's size, but each may always reach `expansion_allowance`
    bytes, so a small, highly compressible part reads whatever its ratio. The absolute caps
    are `int | None`: None, the default, sets no fixed cap, and a caller's own cap applies on
    top of the ratio bounds.
    """

    total_decompressed_cap: int | None = None
    frame_decompressed_cap: int | None = None
    part_expansion: int = MAX_PART_EXPANSION
    save_expansion: int = MAX_SAVE_EXPANSION
    expansion_allowance: int = EXPANSION_ALLOWANCE

    def part_bound(self, compressed_size: int) -> int:
        """The most bytes a part of `compressed_size` compressed bytes may decompress to."""
        bound = max(self.expansion_allowance, self.part_expansion * compressed_size)
        cap = self.frame_decompressed_cap
        return bound if cap is None else min(bound, cap)

    def save_bound(self, file_size: int) -> int:
        """The most bytes a save of `file_size` bytes may decompress to in all."""
        bound = max(self.expansion_allowance, self.save_expansion * file_size)
        cap = self.total_decompressed_cap
        return bound if cap is None else min(bound, cap)


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
    path: Path = field(repr=False)
    fingerprint: Fingerprint
    save_name: str = field(repr=False)
    trailer_offset: int
    entries: tuple[DirectoryEntry, ...]
    sections: Mapping[str, DirectoryEntry] = field(compare=False)
    regions: Mapping[str, Region] = field(compare=False)
    limits: ContainerLimits = field(default_factory=ContainerLimits)

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class FrameSpan:
    offset: int
    size: int
    skippable: bool


def read_exact(save_file: BinaryIO, offset: int, length: int, file_name: str) -> bytes:
    save_file.seek(offset)
    data = save_file.read(length)
    if len(data) != length:
        raise CorruptSaveError(
            f"{file_name} ended early while reading {length} bytes at offset {offset}. {RETRY_HINT}"
        )
    return data


def decompress_frame(
    compressed: bytes,
    *,
    expected_size: int | None,
    cap: int,
    what: str,
    file_name: str,
    overrun: Callable[[], CorruptSaveError] | None = None,
) -> bytes:
    """Decompress exactly one frame without ever producing more than the allowed bytes.

    The decompressor itself stops one byte past `cap`, so no more memory is spent. Output past
    `cap` raises the error `overrun` builds, which names the bound `cap` came from, or a plain
    `CorruptSaveError` without one; output past a declared size is always the plain error.
    """
    output_limit = cap if expected_size is None else min(expected_size, cap)
    decompressor = zstd.ZstdDecompressor()
    try:
        data = decompressor.decompress(compressed, max_length=output_limit + 1)
    except zstd.ZstdError as error:
        raise CorruptSaveError(
            f"{file_name}: {what} could not be decompressed. {RETRY_HINT}"
        ) from error
    if len(data) > output_limit:
        if overrun is not None and (expected_size is None or expected_size > cap):
            raise overrun()
        raise CorruptSaveError(
            f"{file_name}: {what} decompresses to more than {output_limit} bytes"
        )
    if not decompressor.eof:
        raise CorruptSaveError(f"{file_name}: {what} is truncated. {RETRY_HINT}")
    if decompressor.unused_data:
        raise CorruptSaveError(
            f"{file_name}: {what} has unexpected bytes after its frame. {RETRY_HINT}"
        )
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
    # Later reads reopen the file, so a relative path must not follow a change of folder.
    save_path = Path(path).absolute()
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
            raise CorruptSaveError(
                f"{file_name}: the save directory is implausibly large. {RETRY_HINT}"
            )
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
    validate_entries(entries, trailer_offset, effective_limits, file_name, file_size)
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


def damaged_part_error(file_name: str, part: str, error: CorruptSaveError) -> CorruptSaveError:
    """Restate a low-level read error with the file name and the part of the save being read."""
    return CorruptSaveError(
        f"{file_name}: {part} is damaged or was being written ({error}). {RETRY_HINT}"
    )


def parse_directory(
    trailer_payload: bytes, file_name: str
) -> tuple[str, tuple[DirectoryEntry, ...]]:
    try:
        save_name, cursor = read_length_prefixed_string(trailer_payload, 0, MAX_SAVE_NAME_BYTES)
    except CorruptSaveError as error:
        raise damaged_part_error(file_name, "the save directory", error) from error
    cursor += 4  # a u32 whose meaning is not identified
    entries: list[DirectoryEntry] = []
    while (parsed := parse_directory_entry(trailer_payload, cursor)) is not None:
        entry, cursor = parsed
        entries.append(entry)
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            raise CorruptSaveError(
                f"{file_name}: the save directory has too many directory entries "
                f"(more than {MAX_DIRECTORY_ENTRIES})"
            )
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
    file_size: int,
) -> None:
    """Check every entry's frame bounds and declared size before anything is decompressed."""
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
        if entry.decompressed_size > limits.part_bound(entry.compressed_size):
            raise part_bound_error(
                limits, entry.compressed_size, label, file_name, entry.decompressed_size
            )
        total_decompressed += entry.decompressed_size
        previous_end = entry.frame_end
    if total_decompressed > limits.save_bound(file_size):
        raise save_bound_error(limits, file_size, "the save", file_name, total_decompressed)


def format_size(size: int) -> str:
    """A byte count as whole GiB or MiB where it is one, otherwise in bytes."""
    for unit, unit_bytes in (("GiB", 1024**3), ("MiB", 1024**2)):
        if size >= unit_bytes and size % unit_bytes == 0:
            return f"{size // unit_bytes} {unit}"
    return f"{size:,} bytes"


def format_ratio(ratio: float) -> str:
    return f"{ratio:,.0f}" if ratio >= 10 else f"{ratio:.1f}"


def report_hint(file_name: str) -> str:
    return (
        f"The save is probably damaged. {RETRY_HINT} If the game opens {file_name} and a "
        f"fresh copy fails too, please report it at {ISSUES_URL}"
    )


def part_bound_error(
    limits: ContainerLimits,
    compressed_size: int,
    what: str,
    file_name: str,
    claimed: int | None = None,
) -> CorruptSaveError:
    """The error for a part that claims, or decompresses to, more than `limits` allow.

    `claimed` is the declared size; without one, the part decompressed past its bound.
    """
    bound = limits.part_bound(compressed_size)
    cap = limits.frame_decompressed_cap
    if (
        cap is not None
        and replace(limits, frame_decompressed_cap=None).part_bound(compressed_size) > cap
    ):
        return CorruptSaveError(
            f"{file_name}: {what} is larger than the limit of {format_size(cap)} set for one "
            "part of a save"
        )
    compressed_size = max(compressed_size, 1)
    if claimed is None:
        claim = f"decompresses to more than {bound:,} bytes"
        ratio = f"over {limits.part_expansion}"
    else:
        claim = f"claims {claimed:,} bytes"
        ratio = format_ratio(claimed / compressed_size)
    return CorruptSaveError(
        f"{file_name}: {what} {claim} from {compressed_size:,} compressed bytes, {ratio} times "
        f"as many. fmsave allows up to {limits.part_expansion} times for a part over "
        f"{format_size(limits.expansion_allowance)}, and parts of real saves expand at most "
        f"about {OBSERVED_PART_EXPANSION} times. {report_hint(file_name)}"
    )


def save_bound_error(
    limits: ContainerLimits,
    file_size: int,
    what: str,
    file_name: str,
    claimed: int | None = None,
) -> CorruptSaveError:
    """The error for a save whose parts add up to more than `limits` allow.

    `claimed` is the total so far; without one, a frame decompressed past what was left.
    """
    bound = limits.save_bound(file_size)
    cap = limits.total_decompressed_cap
    if cap is not None and replace(limits, total_decompressed_cap=None).save_bound(file_size) > cap:
        return CorruptSaveError(
            f"{file_name}: {what} holds more than the limit of {format_size(cap)} set for a "
            "whole save"
        )
    file_size = max(file_size, 1)
    if claimed is None:
        claim = f"decompresses to more than {bound:,} bytes in all"
        ratio = f"over {limits.save_expansion}"
    else:
        claim = f"claims {claimed:,} bytes in all"
        ratio = format_ratio(claimed / file_size)
    return CorruptSaveError(
        f"{file_name}: {what} {claim}, {ratio} times the file's {file_size:,} bytes. fmsave "
        f"allows up to {limits.save_expansion} times, and real saves stay under "
        f"{OBSERVED_SAVE_EXPANSION} times. {report_hint(file_name)}"
    )


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


def changed_on_disk_error(file_name: str) -> SaveChangedError:
    return SaveChangedError(
        f"{file_name} changed on disk after it was opened. Open it again; if the game is running, copy the file first."
    )


def status_differs(file_status: os.stat_result, fingerprint: Fingerprint) -> bool:
    return (
        file_status.st_size != fingerprint.file_size
        or file_status.st_mtime_ns != fingerprint.mtime_ns
    )


def changed_since_index(container_index: ContainerIndex) -> bool:
    """Whether the save's path can no longer be read or no longer has its recorded size and mtime."""
    try:
        file_status = container_index.path.stat()
    except OSError:
        return True
    return status_differs(file_status, container_index.fingerprint)


def verify_unchanged(container_index: ContainerIndex, save_file: BinaryIO) -> None:
    fingerprint = container_index.fingerprint
    if status_differs(os.fstat(save_file.fileno()), fingerprint):
        raise changed_on_disk_error(container_index.file_name)
    # Plain bounded reads: a file that shrank after fstat reads short and fails the digest check.
    save_file.seek(0)
    header = save_file.read(HEADER_SIZE)
    save_file.seek(container_index.trailer_offset)
    trailer_bytes = save_file.read(fingerprint.file_size - container_index.trailer_offset)
    if trailer_digest(header, trailer_bytes) != fingerprint.header_digest:
        raise changed_on_disk_error(container_index.file_name)


@contextmanager
def open_verified(container_index: ContainerIndex) -> Generator[BinaryIO]:
    """Open the save and check its fingerprint.

    A CorruptSaveError raised while the file is open (such as a short read because the file
    shrank after the check) becomes SaveChangedError when the file on disk has changed.
    """
    try:
        save_file = container_index.path.open("rb")
    except FileNotFoundError as error:
        raise changed_on_disk_error(container_index.file_name) from error
    with save_file:
        verify_unchanged(container_index, save_file)
        try:
            yield save_file
        except CorruptSaveError as error:
            if changed_since_index(container_index):
                raise changed_on_disk_error(container_index.file_name) from error
            raise


def section_entry(container_index: ContainerIndex, name: str) -> DirectoryEntry:
    entry = container_index.sections.get(name)
    if entry is None:
        raise CorruptSaveError(f"{container_index.file_name} has no {name!r} section")
    return entry


def read_section(container_index: ContainerIndex, name: str) -> bytes:
    entry = section_entry(container_index, name)
    with open_verified(container_index) as save_file:
        compressed = read_exact(
            save_file, entry.frame_offset, entry.compressed_size, container_index.file_name
        )
    return decompress_entry(container_index, entry, compressed, f"section {name!r}")


def decompress_entry(
    container_index: ContainerIndex, entry: DirectoryEntry, compressed: bytes, what: str
) -> bytes:
    """Decompress a directory entry's frame, never past its declared size or its bound."""
    limits = container_index.limits
    file_name = container_index.file_name
    return decompress_frame(
        compressed,
        expected_size=entry.decompressed_size,
        cap=limits.part_bound(entry.compressed_size),
        what=what,
        file_name=file_name,
        overrun=lambda: part_bound_error(
            limits, entry.compressed_size, what, file_name, entry.decompressed_size
        ),
    )


def match_file_entries(container_index: ContainerIndex) -> tuple[DirectoryEntry, ...]:
    """The per-match directory entries, in directory order.

    These are not sections, so `build_regions` exposes them as no region and `read_section`
    cannot reach them; a save may list none at all.
    """
    return tuple(
        entry
        for entry in container_index.entries
        if not entry.is_section and entry.extension in MATCH_FILE_EXTENSIONS
    )


def read_directory_entry(container_index: ContainerIndex, entry: DirectoryEntry) -> bytes:
    """The decompressed bytes of one directory entry that is not a section.

    The frame is read and decompressed under the same bounds a section read uses, so a damaged
    entry cannot decompress past them.
    """
    file_name = container_index.file_name
    with open_verified(container_index) as save_file:
        compressed = read_exact(save_file, entry.frame_offset, entry.compressed_size, file_name)
    try:
        return decompress_entry(
            container_index, entry, compressed, f"entry {entry.name}{entry.extension}"
        )
    except CorruptSaveError as error:
        # The frame was read while the file was verified, so bytes that no longer decompress
        # mean the save was rewritten under the read rather than that it is damaged.
        if changed_since_index(container_index):
            raise changed_on_disk_error(file_name) from error
        raise


def read_section_heads(
    container_index: ContainerIndex, names: Sequence[str], length: int
) -> dict[str, bytes]:
    """The first `length` bytes of each section, decoding only as much of each frame as needed.

    A capped prefix of each frame is decoded first; the whole frame is read only when
    that prefix yields too few bytes.
    """
    file_name = container_index.file_name
    entries = {name: section_entry(container_index, name) for name in names}
    heads: dict[str, bytes] = {}
    with open_verified(container_index) as save_file:
        for name, entry in entries.items():
            wanted_length = min(length, entry.decompressed_size)
            prefix_size = min(entry.compressed_size, HEAD_READ_BYTES)
            prefix = read_exact(save_file, entry.frame_offset, prefix_size, file_name)
            head = decompress_head(prefix, wanted_length, name, file_name)
            if len(head) < wanted_length and prefix_size < entry.compressed_size:
                whole_frame = read_exact(
                    save_file, entry.frame_offset, entry.compressed_size, file_name
                )
                head = decompress_head(whole_frame, wanted_length, name, file_name)
            if len(head) < wanted_length:
                raise CorruptSaveError(
                    f"{file_name}: section {name!r} is shorter than its directory entry says"
                )
            heads[name] = head
    return heads


def decompress_head(compressed: bytes, wanted_length: int, name: str, file_name: str) -> bytes:
    try:
        return zstd.ZstdDecompressor().decompress(compressed, max_length=wanted_length)
    except zstd.ZstdError as error:
        raise CorruptSaveError(
            f"{file_name}: section {name!r} could not be decompressed. {RETRY_HINT}"
        ) from error


def walk_frame_headers(
    save_file: BinaryIO, start: int, end: int, file_name: str, *, maximum_frames: int | None = None
) -> tuple[FrameSpan, ...]:
    """Locate every frame in [start, end) from frame and block headers, without decompressing."""
    frame_limit = (
        MAX_FRAMES_PER_REGION
        if maximum_frames is None
        else min(MAX_FRAMES_PER_REGION, maximum_frames)
    )
    if frame_limit <= 0:
        raise ValueError("maximum_frames must be positive")
    spans: list[FrameSpan] = []
    position = start
    while position < end:
        if len(spans) >= frame_limit:
            raise CorruptSaveError(
                f"{file_name}: too many frames between offsets {start} and {end}"
            )
        if position + 4 > end:
            raise CorruptSaveError(f"{file_name}: stray bytes at offset {position}")
        magic = read_u32(read_exact(save_file, position, 4, file_name), 0)
        if SKIPPABLE_MAGIC_FIRST <= magic <= SKIPPABLE_MAGIC_LAST:
            if position + 8 > end:
                raise CorruptSaveError(
                    f"{file_name}: truncated skippable frame at offset {position}"
                )
            frame_size = 8 + read_u32(read_exact(save_file, position + 4, 4, file_name), 0)
            if position + frame_size > end:
                raise CorruptSaveError(
                    f"{file_name}: skippable frame at offset {position} runs past its region"
                )
            spans.append(FrameSpan(position, frame_size, skippable=True))
            position += frame_size
            continue
        if magic != ZSTD_FRAME_MAGIC:
            raise CorruptSaveError(f"{file_name}: expected a compressed frame at offset {position}")
        frame_end = compressed_frame_end(save_file, position, end, file_name)
        spans.append(FrameSpan(position, frame_end - position, skippable=False))
        position = frame_end
    return tuple(spans)


def compressed_frame_end(
    save_file: BinaryIO, frame_start: int, region_end: int, file_name: str
) -> int:
    if frame_start + 5 > region_end:
        raise CorruptSaveError(f"{file_name}: frame at offset {frame_start} runs past its region")
    descriptor = read_exact(save_file, frame_start + 4, 1, file_name)[0]
    if descriptor & 0x08:
        raise CorruptSaveError(f"{file_name}: invalid frame header at offset {frame_start}")
    single_segment = bool(descriptor & 0x20)
    header_size = (
        5
        + (0 if single_segment else 1)
        + (0, 1, 2, 4)[descriptor & 0x03]
        + ((1 if single_segment else 0), 2, 4, 8)[descriptor >> 6]
    )
    block_position = frame_start + header_size
    while True:
        if block_position + 3 > region_end:
            raise CorruptSaveError(
                f"{file_name}: frame at offset {frame_start} runs past its region"
            )
        block_header_bytes = read_exact(save_file, block_position, 3, file_name)
        block_header = int.from_bytes(block_header_bytes, "little")
        block_type = (block_header >> 1) & 0x03
        block_size = block_header >> 3
        if block_type == BLOCK_TYPE_RESERVED or block_size > ZSTD_MAX_BLOCK_BYTES:
            raise CorruptSaveError(f"{file_name}: invalid block in frame at offset {frame_start}")
        block_position += 3 + (1 if block_type == BLOCK_TYPE_RLE else block_size)
        if block_header & 0x01:
            break
    if descriptor & 0x04:
        block_position += 4
    if block_position > region_end:
        raise CorruptSaveError(f"{file_name}: frame at offset {frame_start} runs past its region")
    return block_position


def region_named(container_index: ContainerIndex, region_name: str) -> Region:
    region = container_index.regions.get(region_name)
    if region is None:
        raise CorruptSaveError(f"{container_index.file_name} has no region {region_name!r}")
    return region


def walk_frames(
    container_index: ContainerIndex, region_name: str, *, maximum_frames: int | None = None
) -> tuple[FrameSpan, ...]:
    region = region_named(container_index, region_name)
    with open_verified(container_index) as save_file:
        return walk_frame_headers(
            save_file,
            region.start,
            region.end,
            container_index.file_name,
            maximum_frames=maximum_frames,
        )


def read_region_frames_bounded(
    container_index: ContainerIndex,
    region_name: str,
    *,
    maximum_compressed_bytes: int | None = None,
    maximum_compressed_frame_bytes: int | None = None,
    maximum_frames: int | None = None,
    maximum_decompressed_bytes: int | None = None,
    maximum_frame_output_bytes: int | None = None,
) -> Iterator[bytes]:
    """Read one frame at a time under the container's bounds and any caller budgets.

    Budgets left as None add nothing to the container's bounds. No compressed-frame list is
    retained and no file handle survives a yielded frame. The remaining output budgets also
    limit each decompressor call itself.
    """
    budgets = (
        maximum_compressed_bytes,
        maximum_compressed_frame_bytes,
        maximum_frames,
        maximum_decompressed_bytes,
        maximum_frame_output_bytes,
    )
    if any(budget is not None and budget <= 0 for budget in budgets):
        raise ValueError("bounded region budgets must be positive")
    region = region_named(container_index, region_name)
    if (
        maximum_compressed_bytes is not None
        and region.end - region.start > maximum_compressed_bytes
    ):
        raise CorruptSaveError("region exceeds its compressed byte budget")
    spans = walk_frames(container_index, region_name, maximum_frames=maximum_frames)
    if maximum_compressed_frame_bytes is not None and any(
        span.size > maximum_compressed_frame_bytes for span in spans
    ):
        raise CorruptSaveError("region exceeds its compressed frame byte budget")
    counted = declared_total(container_index)
    produced = 0
    for span in spans:
        if span.skippable:
            continue
        caps = [
            cap
            for cap in (
                container_index.limits.frame_decompressed_cap,
                maximum_frame_output_bytes,
                None
                if maximum_decompressed_bytes is None
                else maximum_decompressed_bytes - produced,
            )
            if cap is not None
        ]
        bounded = replace(
            container_index,
            limits=replace(
                container_index.limits, frame_decompressed_cap=min(caps) if caps else None
            ),
        )
        frame = read_region_frame(bounded, region_name, span, counted=counted + produced)
        produced += len(frame)
        yield frame


def read_region_frames(container_index: ContainerIndex, region_name: str) -> Iterator[bytes]:
    """Read a region's frames with one short file open, then decompress them lazily."""
    region = region_named(container_index, region_name)
    file_name = container_index.file_name
    with open_verified(container_index) as save_file:
        spans = walk_frame_headers(save_file, region.start, region.end, file_name)
        compressed_frames = [
            read_exact(save_file, span.offset, span.size, file_name)
            for span in spans
            if not span.skippable
        ]
    return decompress_region_frames(container_index, compressed_frames, region_name)


def declared_total(container_index: ContainerIndex) -> int:
    return sum(entry.decompressed_size for entry in container_index.entries)


def region_frame_heads(
    container_index: ContainerIndex, region_name: str, length: int
) -> tuple[tuple[FrameSpan, bytes], ...]:
    """Each compressed frame of a region with at most the first `length` bytes of its body.

    Only a capped prefix of each frame is read and only `length` bytes are decoded from it, so
    a reader can pick the frame it wants out of a region of hundreds of megabytes without
    decompressing the rest. A frame whose body is shorter than `length` gives its whole body.
    """
    region = region_named(container_index, region_name)
    file_name = container_index.file_name
    heads: list[tuple[FrameSpan, bytes]] = []
    with open_verified(container_index) as save_file:
        for span in walk_frame_headers(save_file, region.start, region.end, file_name):
            if span.skippable:
                continue
            prefix = read_exact(save_file, span.offset, min(span.size, HEAD_READ_BYTES), file_name)
            heads.append((span, decompress_head(prefix, length, region_name, file_name)))
    return tuple(heads)


def read_region_frame(
    container_index: ContainerIndex,
    region_name: str,
    span: FrameSpan,
    *,
    counted: int | None = None,
) -> bytes:
    """Decompress one frame of a region, located by `region_frame_heads`.

    `counted` is the output already counted against the whole-save bound, by default the
    directory's declared total; the frame may not take the save past that bound.
    """
    file_name = container_index.file_name
    with open_verified(container_index) as save_file:
        compressed = read_exact(save_file, span.offset, span.size, file_name)
    try:
        return decompress_region_frame(
            container_index,
            compressed,
            declared_total(container_index) if counted is None else counted,
            f"a frame of region {region_name!r}",
        )
    except CorruptSaveError as error:
        # As for a directory entry: the frame was read while the file was verified, so bytes
        # that no longer decompress mean the save was rewritten under the read.
        if changed_since_index(container_index):
            raise changed_on_disk_error(file_name) from error
        raise


def decompress_region_frame(
    container_index: ContainerIndex, compressed: bytes, counted: int, what: str
) -> bytes:
    """Decompress a frame with no declared size, stopping at the first bound it would pass.

    The frame may expand no further than a part of its compressed size may, and may not take
    the save's output past the whole-save bound once `counted` bytes are already counted.
    """
    limits = container_index.limits
    file_name = container_index.file_name
    file_size = container_index.fingerprint.file_size
    part_cap = limits.part_bound(len(compressed))
    save_left = max(limits.save_bound(file_size) - counted, 0)
    if part_cap <= save_left:
        cap = part_cap

        def overrun() -> CorruptSaveError:
            return part_bound_error(limits, len(compressed), what, file_name)
    else:
        cap = save_left

        def overrun() -> CorruptSaveError:
            return save_bound_error(limits, file_size, "the save", file_name)

    return decompress_frame(
        compressed, expected_size=None, cap=cap, what=what, file_name=file_name, overrun=overrun
    )


def read_chosen_region_frames(
    container_index: ContainerIndex, region_name: str, spans: Iterable[FrameSpan]
) -> Iterator[bytes]:
    """Decompress the chosen frames of a region one at a time, located by `region_frame_heads`.

    As in `decompress_region_frames`, the frames count against the whole-save bound after the
    directory's data, so a region of many chosen frames cannot decompress past it.
    """
    counted = declared_total(container_index)
    for span in spans:
        frame_bytes = read_region_frame(container_index, region_name, span, counted=counted)
        counted += len(frame_bytes)
        yield frame_bytes


def decompress_region_frames(
    container_index: ContainerIndex, compressed_frames: list[bytes], region_name: str
) -> Iterator[bytes]:
    """Yield each frame's bytes; unlisted data counts against the whole-save bound after the
    directory's."""
    counted = declared_total(container_index)
    for frame_number, compressed_frame in enumerate(compressed_frames):
        frame_bytes = decompress_region_frame(
            container_index,
            compressed_frame,
            counted,
            f"frame {frame_number} of region {region_name!r}",
        )
        counted += len(frame_bytes)
        yield frame_bytes
