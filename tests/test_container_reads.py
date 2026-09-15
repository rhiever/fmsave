from __future__ import annotations

import io
import itertools
import os
import random
import struct
import sys
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

import pytest

import fmsave._container as container_module
from fmsave._container import (
    ContainerIndex,
    ContainerLimits,
    open_verified,
    read_index,
    read_region_frames,
    read_section,
    read_section_heads,
    walk_frame_headers,
    walk_frames,
)
from fmsave._errors import CorruptSaveError, SaveChangedError
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    section_body,
)

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

UNLISTED_REGION = "unlisted_after_non_pl_hist_ls"
ZSTD_MAGIC = struct.pack("<I", 0xFD2FB528)
SKIPPABLE_MAGIC = struct.pack("<I", 0x184D2A5F)
BYTES_AFTER_REGION = bytes(512)


@pytest.fixture
def fragment_path(tmp_path: Path) -> Path:
    return build_container_fragment().write(tmp_path / "fragment.bin")


def test_read_section_returns_exact_bodies(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    for section in default_sections():
        assert read_section(container_index, section.name) == section.body


def test_unknown_section_is_corrupt(fragment_path: Path) -> None:
    with pytest.raises(CorruptSaveError):
        read_section(read_index(fragment_path), "no_such_section")


def test_section_heads(tmp_path: Path) -> None:
    large_body = section_body(".dat", 4000, os.urandom(1024 * 1024))
    sections = default_sections() + [
        SectionFrame("large_example", large_body),
        SectionFrame("tiny_example", section_body(".dat", 1, b"")),
    ]
    container_index = read_index(
        build_container_fragment(sections).write(tmp_path / "fragment.bin")
    )
    heads = read_section_heads(container_index, ["game_info", "large_example", "tiny_example"], 16)
    assert heads["game_info"] == default_sections()[0].body[:16]
    assert heads["large_example"] == large_body[:16]
    assert heads["tiny_example"] == section_body(".dat", 1, b"")


def test_walk_frames_over_unlisted_region(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    region = container_index.regions[UNLISTED_REGION]
    spans = walk_frames(container_index, UNLISTED_REGION)
    assert [span.skippable for span in spans] == [False, False, True]
    assert spans[0].offset == region.start
    assert spans[-1].offset + spans[-1].size == region.end
    for earlier_span, later_span in itertools.pairwise(spans):
        assert earlier_span.offset + earlier_span.size == later_span.offset


def test_walk_frames_over_section_region(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    entry = container_index.sections["game_db"]
    spans = walk_frames(container_index, "game_db")
    assert [(span.offset, span.size, span.skippable) for span in spans] == [
        (entry.frame_offset, entry.compressed_size, False)
    ]


def test_read_region_frames(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    assert list(read_region_frames(container_index, UNLISTED_REGION)) == [b"A" * 32, b"B" * 48]


def test_unknown_region_is_corrupt(fragment_path: Path) -> None:
    with pytest.raises(CorruptSaveError):
        walk_frames(read_index(fragment_path), "no_such_region")


def test_garbage_in_region_is_corrupt(tmp_path: Path) -> None:
    sections = default_sections()
    sections[4] = SectionFrame(
        "non_pl_hist_ls",
        section_body(".dat", 5, bytes(16)),
        unlisted_frames_after=(b"not a frame at all",),
    )
    container_index = read_index(
        build_container_fragment(sections).write(tmp_path / "fragment.bin")
    )
    with pytest.raises(CorruptSaveError):
        walk_frames(container_index, UNLISTED_REGION)


def test_section_decompression_bomb_is_bounded(tmp_path: Path) -> None:
    bomb_body = section_body(".dat", 4000, bytes(64 * 1024 * 1024))
    compressed_size = len(zstd.compress(bomb_body))
    sections = [
        section if section.name != "game_db" else SectionFrame("game_db", bomb_body)
        for section in default_sections()
    ]
    fragment = build_container_fragment(
        sections, declared_sizes={"game_db.dat": (compressed_size, 16)}
    )
    container_index = read_index(fragment.write(tmp_path / "fragment.bin"))
    del fragment, sections, bomb_body
    tracemalloc.start()
    try:
        with pytest.raises(CorruptSaveError):
            read_section(container_index, "game_db")
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak_bytes < 4 * 1024 * 1024


def test_region_frame_cap_is_bounded(tmp_path: Path) -> None:
    sections = default_sections()
    sections[4] = SectionFrame(
        "non_pl_hist_ls",
        section_body(".dat", 5, bytes(16)),
        unlisted_frames_after=(zstd.compress(bytes(64 * 1024 * 1024)),),
    )
    fragment_path = build_container_fragment(sections).write(tmp_path / "fragment.bin")
    container_index = read_index(fragment_path, ContainerLimits(frame_decompressed_cap=1024 * 1024))
    tracemalloc.start()
    try:
        with pytest.raises(CorruptSaveError):
            list(read_region_frames(container_index, UNLISTED_REGION))
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak_bytes < 8 * 1024 * 1024


def test_region_total_cap(fragment_path: Path) -> None:
    declared_total = sum(entry.decompressed_size for entry in read_index(fragment_path).entries)
    container_index = read_index(
        fragment_path, ContainerLimits(total_decompressed_cap=declared_total + 50)
    )
    with pytest.raises(CorruptSaveError):
        list(read_region_frames(container_index, UNLISTED_REGION))


def test_rewritten_file_raises_save_changed(tmp_path: Path, fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    build_container_fragment(save_name="Another Example").write(fragment_path)
    with pytest.raises(SaveChangedError) as error_info:
        read_section(container_index, "humans")
    assert str(tmp_path) not in str(error_info.value)


def test_touched_file_raises_save_changed(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    file_status = fragment_path.stat()
    os.utime(fragment_path, ns=(file_status.st_atime_ns, file_status.st_mtime_ns + 1_000_000_000))
    with pytest.raises(SaveChangedError):
        read_section(container_index, "humans")


def test_truncated_file_raises_save_changed(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    fragment_path.write_bytes(fragment_path.read_bytes()[:100])
    with pytest.raises(SaveChangedError):
        read_section(container_index, "humans")


def verify_then_change(monkeypatch: pytest.MonkeyPatch, change_file: Callable[[], None]) -> None:
    """Pass the fingerprint check, then change the file before any frame is read."""
    original_verify = container_module.verify_unchanged

    def verify_and_change(container_index: ContainerIndex, save_file: BinaryIO) -> None:
        original_verify(container_index, save_file)
        change_file()

    monkeypatch.setattr(container_module, "verify_unchanged", verify_and_change)


def test_file_shrinking_after_verification_raises_save_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fragment_path: Path
) -> None:
    container_index = read_index(fragment_path)
    shrunk_size = container_index.sections["humans"].frame_offset + 1
    verify_then_change(monkeypatch, lambda: os.truncate(fragment_path, shrunk_size))
    with pytest.raises(SaveChangedError) as error_info:
        read_section(container_index, "humans")
    assert isinstance(error_info.value.__cause__, CorruptSaveError)
    assert "fragment.bin" in str(error_info.value)
    assert str(tmp_path) not in str(error_info.value)


def make_path_stat_fail(patcher: pytest.MonkeyPatch, path: Path, stat_error: type[OSError]) -> None:
    """Make stat on the save's path fail, as it does once the file is deleted or unreadable.

    Simulated because Windows refuses to delete a file that is still open.
    """

    def raise_stat_error(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        raise stat_error("fictional stat failure")

    patcher.setattr(type(path), "stat", raise_stat_error)


@pytest.mark.parametrize("stat_error", [FileNotFoundError, PermissionError, OSError])
def test_unreadable_path_during_a_verified_read_raises_save_changed(
    fragment_path: Path, stat_error: type[OSError]
) -> None:
    container_index = read_index(fragment_path)
    with pytest.MonkeyPatch.context() as patcher:
        make_path_stat_fail(patcher, fragment_path, stat_error)
        with pytest.raises(SaveChangedError) as error_info, open_verified(container_index):
            raise CorruptSaveError("fictional short read")
    assert isinstance(error_info.value.__cause__, CorruptSaveError)


def test_corrupt_error_on_an_unchanged_file_propagates(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    with (
        pytest.raises(CorruptSaveError, match="fictional damage") as error_info,
        open_verified(container_index),
    ):
        raise CorruptSaveError("fictional damage")
    assert not isinstance(error_info.value, SaveChangedError)


def test_other_errors_on_a_changed_file_are_untouched(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    with pytest.MonkeyPatch.context() as patcher:
        make_path_stat_fail(patcher, fragment_path, FileNotFoundError)
        with (
            pytest.raises(LookupError, match="fictional failure"),
            open_verified(container_index),
        ):
            raise LookupError("fictional failure")


def test_deleted_file_raises_save_changed(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    fragment_path.unlink()
    with pytest.raises(SaveChangedError):
        read_section(container_index, "humans")


def test_file_handles_are_released(tmp_path: Path, fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    read_section(container_index, "humans")
    list(read_region_frames(container_index, UNLISTED_REGION))
    replacement_path = build_container_fragment(save_name="Replacement").write(
        tmp_path / "replacement.bin"
    )
    os.replace(replacement_path, fragment_path)
    os.remove(fragment_path)
    assert not fragment_path.exists()


def block_header(block_size: int, block_type: int, *, last: bool) -> bytes:
    return (block_size << 3 | block_type << 1 | int(last)).to_bytes(3, "little")


def raw_frame(payload: bytes) -> bytes:
    """A single-segment frame with a one-byte content size and one raw block."""
    return (
        ZSTD_MAGIC
        + bytes([0x20, len(payload)])
        + block_header(len(payload), 0, last=True)
        + payload
    )


def skippable_frame_bytes(payload: bytes) -> bytes:
    """A skippable frame using the last magic number of the skippable range."""
    return SKIPPABLE_MAGIC + struct.pack("<I", len(payload)) + payload


def walk_region_bytes(region_bytes: bytes) -> tuple[int, ...]:
    """Walk a region followed by more file bytes, returning each frame's size."""
    save_file = io.BytesIO(region_bytes + BYTES_AFTER_REGION)
    return tuple(
        span.size for span in walk_frame_headers(save_file, 0, len(region_bytes), "fragment.bin")
    )


HEADER_VARIANT_FRAMES = {
    "single segment, one-byte content size": raw_frame(b"example"),
    "window byte, no content size": ZSTD_MAGIC
    + bytes([0x00, 0x00])
    + block_header(4, 0, last=True)
    + b"four",
    "window byte, two-byte content size": ZSTD_MAGIC
    + bytes([0x40, 0x00])
    + struct.pack("<H", 300 - 256)
    + block_header(300, 1, last=True)
    + b"R",
    "single segment, four-byte content size, two blocks": ZSTD_MAGIC
    + bytes([0xA0])
    + struct.pack("<I", 9)
    + block_header(5, 0, last=False)
    + b"first"
    + block_header(4, 1, last=True)
    + b"x",
    "single segment, eight-byte content size": ZSTD_MAGIC
    + bytes([0xE0])
    + struct.pack("<Q", 3)
    + block_header(3, 0, last=True)
    + b"abc",
    "checksum": zstd.compress(
        b"checked " * 8, options={zstd.CompressionParameter.checksum_flag: 1}
    ),
}


@pytest.mark.parametrize("frame", HEADER_VARIANT_FRAMES.values(), ids=HEADER_VARIANT_FRAMES.keys())
def test_frame_walker_sizes_real_frames(frame: bytes) -> None:
    zstd.decompress(frame)
    assert walk_region_bytes(frame + skippable_frame_bytes(b"gap") + frame) == (
        len(frame),
        11,
        len(frame),
    )


@pytest.mark.parametrize(
    ("descriptor", "dictionary_id_bytes"),
    [(0x21, 1), (0x22, 2), (0x23, 4)],
    ids=["one", "two", "four"],
)
def test_frame_walker_counts_dictionary_id_bytes(descriptor: int, dictionary_id_bytes: int) -> None:
    frame = (
        ZSTD_MAGIC
        + bytes([descriptor])
        + bytes(dictionary_id_bytes)
        + bytes([2])
        + block_header(2, 0, last=True)
        + b"ok"
    )
    assert walk_region_bytes(frame) == (len(frame),)


MALFORMED_REGIONS = {
    "stray bytes": (raw_frame(b"example") + b"\x28\xb5\x2f", "stray bytes at offset 16"),
    "truncated skippable frame": (SKIPPABLE_MAGIC + b"\x04\x00", "truncated skippable frame"),
    "skippable frame past region": (
        SKIPPABLE_MAGIC + struct.pack("<I", 100) + bytes(4),
        "skippable frame at offset 0 runs past its region",
    ),
    "bad magic": (b"not a frame at all", "expected a compressed frame at offset 0"),
    "reserved descriptor bit": (
        ZSTD_MAGIC + bytes([0x28, 1]) + block_header(1, 0, last=True) + b"x",
        "invalid frame header",
    ),
    "block header past region": (ZSTD_MAGIC + bytes([0x20, 1]) + b"\x00", "runs past its region"),
    "non-last block past region": (
        ZSTD_MAGIC + bytes([0x20, 1]) + block_header(8, 0, last=False) + b"abc",
        "runs past its region",
    ),
    "reserved block type": (
        ZSTD_MAGIC + bytes([0x20, 1]) + block_header(1, 3, last=True) + b"x",
        "invalid block",
    ),
    "block over 128 KiB": (
        ZSTD_MAGIC + bytes([0x20, 1]) + block_header(128 * 1024 + 1, 2, last=True) + bytes(8),
        "invalid block",
    ),
    "last block past region": (
        raw_frame(b"example")[:-2],
        "frame at offset 0 runs past its region",
    ),
    "checksum past region": (
        ZSTD_MAGIC + bytes([0x24, 1]) + block_header(1, 0, last=True) + b"x" + bytes(2),
        "frame at offset 0 runs past its region",
    ),
}


@pytest.mark.parametrize(
    ("region_bytes", "message"), MALFORMED_REGIONS.values(), ids=MALFORMED_REGIONS.keys()
)
def test_frame_walker_rejects_malformed_regions(region_bytes: bytes, message: str) -> None:
    with pytest.raises(CorruptSaveError, match=message):
        walk_region_bytes(region_bytes)


def test_frame_walker_caps_frame_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fmsave._container.MAX_FRAMES_PER_REGION", 2)
    assert walk_region_bytes(skippable_frame_bytes(b"") * 2) == (8, 8)
    with pytest.raises(CorruptSaveError, match="too many frames"):
        walk_region_bytes(skippable_frame_bytes(b"") * 3)


def test_frame_running_into_next_section_is_corrupt(tmp_path: Path) -> None:
    sections = default_sections()
    sections[4] = SectionFrame(
        "non_pl_hist_ls",
        section_body(".dat", 5, bytes(16)),
        unlisted_frames_after=(zstd.compress(bytes(range(40)))[:-2],),
    )
    container_index = read_index(
        build_container_fragment(sections).write(tmp_path / "fragment.bin")
    )
    with pytest.raises(CorruptSaveError, match="runs past its region"):
        walk_frames(container_index, UNLISTED_REGION)


def test_same_size_edit_with_restored_mtime_raises_save_changed(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    file_status = fragment_path.stat()
    edited_content = bytearray(fragment_path.read_bytes())
    edited_content[25] ^= 0xFF
    fragment_path.write_bytes(bytes(edited_content))
    os.utime(fragment_path, ns=(file_status.st_atime_ns, file_status.st_mtime_ns))
    with pytest.raises(SaveChangedError):
        read_section(container_index, "humans")


def test_section_head_shorter_than_declared_is_corrupt(tmp_path: Path) -> None:
    humans_body = default_sections()[5].body
    fragment = build_container_fragment(
        declared_sizes={"humans.dat": (len(zstd.compress(humans_body)), len(humans_body) + 100)}
    )
    container_index = read_index(fragment.write(tmp_path / "fragment.bin"))
    with pytest.raises(CorruptSaveError, match="shorter than its directory entry says"):
        read_section_heads(container_index, ["humans"], len(humans_body) + 1)


def test_damaged_section_head_is_corrupt(tmp_path: Path) -> None:
    fragment = build_container_fragment()
    humans_offset = fragment.frame_offsets["humans.dat"]
    damaged_content = bytearray(fragment.content)
    damaged_content[humans_offset + 4] |= 0x08
    damaged_path = tmp_path / "fragment.bin"
    damaged_path.write_bytes(bytes(damaged_content))
    container_index = read_index(damaged_path)
    with pytest.raises(CorruptSaveError, match="could not be decompressed"):
        read_section_heads(container_index, ["humans"], 8)


def test_section_heads_beyond_the_first_block(tmp_path: Path) -> None:
    large_body = section_body(".dat", 4000, os.urandom(1024 * 1024))
    sections = [*default_sections(), SectionFrame("large_example", large_body)]
    container_index = read_index(
        build_container_fragment(sections).write(tmp_path / "fragment.bin")
    )
    heads = read_section_heads(container_index, ["large_example"], 200000)
    assert heads["large_example"] == large_body[:200000]


def early_flushed_frame(body: bytes, first_block_bytes: int) -> bytes:
    """A valid frame whose first block holds only `first_block_bytes` bytes."""
    compressor = zstd.ZstdCompressor()
    first_part = compressor.compress(body[:first_block_bytes], mode=zstd.ZstdCompressor.FLUSH_BLOCK)
    return first_part + compressor.compress(
        body[first_block_bytes:], mode=zstd.ZstdCompressor.FLUSH_FRAME
    )


@pytest.mark.parametrize("length", [64, 140000])
def test_section_heads_with_a_small_first_block(tmp_path: Path, length: int) -> None:
    flushed_body = section_body(".dat", 4000, os.urandom(300000))
    flushed_frame = early_flushed_frame(flushed_body, 10)
    placeholder_body = os.urandom(len(flushed_body) + 256)
    assert len(zstd.compress(placeholder_body)) >= len(flushed_frame)
    fragment = build_container_fragment(
        [*default_sections(), SectionFrame("flushed_example", placeholder_body)],
        declared_sizes={"flushed_example.dat": (len(flushed_frame), len(flushed_body))},
    )
    frame_offset = fragment.frame_offsets["flushed_example.dat"]
    spliced_content = bytearray(fragment.content)
    spliced_content[frame_offset : frame_offset + len(flushed_frame)] = flushed_frame
    spliced_path = tmp_path / "fragment.bin"
    spliced_path.write_bytes(bytes(spliced_content))
    container_index = read_index(spliced_path)
    assert read_section(container_index, "flushed_example") == flushed_body
    heads = read_section_heads(container_index, ["flushed_example"], length)
    assert heads["flushed_example"] == flushed_body[:length]


def test_short_large_section_head_is_corrupt(tmp_path: Path) -> None:
    large_body = section_body(".dat", 4000, os.urandom(300000))
    fragment = build_container_fragment(
        [*default_sections(), SectionFrame("large_example", large_body)],
        declared_sizes={
            "large_example.dat": (len(zstd.compress(large_body)), len(large_body) + 1000)
        },
    )
    container_index = read_index(fragment.write(tmp_path / "fragment.bin"))
    with pytest.raises(CorruptSaveError, match="shorter than its directory entry says"):
        read_section_heads(container_index, ["large_example"], len(large_body) + 1)


def test_frame_walker_checks_region_before_reading_descriptor() -> None:
    region_bytes = ZSTD_MAGIC
    with pytest.raises(CorruptSaveError, match="frame at offset 0 runs past its region"):
        walk_frame_headers(io.BytesIO(region_bytes), 0, len(region_bytes), "fragment.bin")


def test_file_shrinking_during_verification_raises_save_changed(
    fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_index = read_index(fragment_path)
    fingerprint = container_index.fingerprint
    fragment_path.write_bytes(fragment_path.read_bytes()[:-5])

    def fstat_reporting_the_opened_size(file_descriptor: int) -> SimpleNamespace:
        return SimpleNamespace(st_size=fingerprint.file_size, st_mtime_ns=fingerprint.mtime_ns)

    monkeypatch.setattr(
        "fmsave._container.os", SimpleNamespace(fstat=fstat_reporting_the_opened_size)
    )
    with pytest.raises(SaveChangedError):
        read_section(container_index, "humans")


def test_section_head_prefix_cut_inside_a_compressed_block_reads_the_whole_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patterned_body = section_body(
        ".dat", 4000, bytes(random.Random(26).choices(b"ABCDEFGH", k=20000))
    )
    sections = [*default_sections(), SectionFrame("patterned_example", patterned_body)]
    container_index = read_index(
        build_container_fragment(sections).write(tmp_path / "fragment.bin")
    )
    entry = container_index.sections["patterned_example"]
    head_read_bytes = 64
    wanted_length = 1000
    frame_prefix = zstd.compress(patterned_body)[:head_read_bytes]
    assert entry.compressed_size > head_read_bytes
    assert zstd.ZstdDecompressor().decompress(frame_prefix, max_length=wanted_length) == b""
    original_read_exact = container_module.read_exact
    read_lengths: list[int] = []

    def recording_read_exact(
        save_file: BinaryIO, offset: int, length: int, file_name: str
    ) -> bytes:
        read_lengths.append(length)
        return original_read_exact(save_file, offset, length, file_name)

    monkeypatch.setattr(container_module, "HEAD_READ_BYTES", head_read_bytes)
    monkeypatch.setattr(container_module, "read_exact", recording_read_exact)
    heads = read_section_heads(container_index, ["patterned_example"], wanted_length)
    assert heads["patterned_example"] == patterned_body[:wanted_length]
    assert read_lengths[-2:] == [head_read_bytes, entry.compressed_size]
