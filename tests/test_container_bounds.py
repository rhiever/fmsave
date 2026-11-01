"""Decompressed output is bounded relative to the file, not by fixed sizes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import fmsave._container as container
from fmsave._container import (
    EXPANSION_ALLOWANCE,
    ContainerLimits,
    DirectoryEntry,
    read_index,
    read_region_frames,
    read_section,
    validate_entries,
)
from fmsave._errors import CorruptSaveError
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


def entry(name: str, offset: int, compressed: int, decompressed: int) -> DirectoryEntry:
    return DirectoryEntry(name, ".dat", offset, compressed, decompressed, (0, 0))


def with_unlisted_frame(tmp_path: Path, payload: bytes) -> Path:
    sections = default_sections()
    sections[4] = SectionFrame(
        "non_pl_hist_ls",
        section_body(".dat", 5, bytes(16)),
        unlisted_frames_after=(zstd.compress(payload),),
    )
    return build_container_fragment(sections).write(tmp_path / "fragment.bin")


class DecompressorSpy:
    """Record each output limit fmsave hands the decompressor."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.output_limits: list[int] = []
        real = zstd.ZstdDecompressor
        spy = self

        class Recording:
            def __init__(self) -> None:
                self._inner = real()

            def decompress(self, data: bytes, max_length: int = -1) -> bytes:
                spy.output_limits.append(max_length)
                return self._inner.decompress(data, max_length=max_length)

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

        monkeypatch.setattr(container.zstd, "ZstdDecompressor", Recording)


def test_parts_and_saves_past_the_old_fixed_caps_pass_at_plausible_ratios() -> None:
    # 7 GiB from 2 GiB and 9 GiB in all from a 3 GiB file: past the old 2 GiB and 4 GiB caps.
    entries = (
        entry("game_db", 26, 2 * 1024**3, 7 * 1024**3),
        entry("humans", 26 + 2 * 1024**3, 1024**3, 2 * 1024**3),
    )
    validate_entries(entries, 3 * 1024**3 + 26, ContainerLimits(), "example.fm", 3 * 1024**3 + 64)


def test_small_parts_read_whatever_their_ratio(tmp_path: Path) -> None:
    sections = default_sections()
    sections[1] = SectionFrame("memory_pools", section_body(".dat", 3, bytes(4 * 1024**2)))
    path = build_container_fragment(sections).write(tmp_path / "fragment.bin")
    index = read_index(path)
    assert index.sections["memory_pools"].compressed_size * 1000 < 4 * 1024**2
    assert len(read_section(index, "memory_pools")) == 4 * 1024**2 + 8


def test_a_bomb_shaped_part_is_refused_before_it_is_decompressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = next(section for section in default_sections() if section.name == "game_db")
    compressed_size = len(zstd.compress(database.body))
    path = build_container_fragment(
        declared_sizes={"game_db.dat": (compressed_size, EXPANSION_ALLOWANCE + 1)}
    ).write(tmp_path / "fragment.bin")
    spy = DecompressorSpy(monkeypatch)
    with pytest.raises(CorruptSaveError) as error_info:
        read_index(path)
    # Only the directory was decompressed, under its own small bound.
    assert spy.output_limits == [container.MAX_TRAILER_DECOMPRESSED_BYTES + 1]
    message = str(error_info.value)
    assert (
        f"game_db.dat claims {EXPANSION_ALLOWANCE + 1:,} bytes from {compressed_size:,}" in message
    )
    assert "fmsave allows up to 64 times for a part over 64 MiB" in message
    assert "parts of real saves expand at most about 41 times" in message
    assert "please report it at" in message


def test_a_frame_expanding_past_its_bound_is_stopped_while_decompressing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = with_unlisted_frame(tmp_path, bytes(1024**2))
    compressed_size = len(zstd.compress(bytes(1024**2)))
    index = read_index(path, ContainerLimits(expansion_allowance=4096))
    bound = max(4096, 64 * compressed_size)
    spy = DecompressorSpy(monkeypatch)
    with pytest.raises(CorruptSaveError, match="over 64 times as many") as error_info:
        list(read_region_frames(index, UNLISTED_REGION))
    assert f"decompresses to more than {bound:,} bytes" in str(error_info.value)
    # The decompressor itself was stopped one byte past the bound.
    assert max(spy.output_limits) == bound + 1


def test_unlisted_frames_count_against_the_whole_save_bound(tmp_path: Path) -> None:
    path = with_unlisted_frame(tmp_path, bytes(200_000))
    limits = ContainerLimits(part_expansion=10**6, expansion_allowance=1024)
    index = read_index(path, limits)
    assert limits.save_bound(index.fingerprint.file_size) < 200_000
    with pytest.raises(CorruptSaveError, match="in all, over 32 times the file's") as error_info:
        list(read_region_frames(index, UNLISTED_REGION))
    assert "real saves stay under 5 times" in str(error_info.value)


def test_a_callers_absolute_caps_apply_on_top_of_the_ratio_bounds() -> None:
    limits = ContainerLimits(total_decompressed_cap=1000, frame_decompressed_cap=100)
    assert limits.part_bound(10) == 100
    assert limits.save_bound(10) == 1000
    # Without caps, only the ratio bounds and the allowance apply.
    assert ContainerLimits().part_bound(10) == EXPANSION_ALLOWANCE
    assert ContainerLimits().part_bound(2 * 1024**3) == 128 * 1024**3
    assert ContainerLimits().save_bound(2 * 1024**3) == 64 * 1024**3
