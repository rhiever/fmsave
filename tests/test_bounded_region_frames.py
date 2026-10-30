"""Integrated input/output budgets must apply before accumulating compressed data."""

from __future__ import annotations

from pathlib import Path

import pytest

import fmsave._container as container
from fmsave._errors import CorruptSaveError
from tests.fixtures.container import SectionFrame, build_container_fragment, section_body, zstd


def region_index(tmp_path: Path, payloads: tuple[bytes, ...]):
    sections = [
        SectionFrame(
            "non_pl_hist_ls",
            section_body(".dat", 4, bytes(4)),
            unlisted_frames_after=tuple(zstd.compress(p) for p in payloads),
        )
    ]
    return container.read_index(build_container_fragment(sections).write(tmp_path / "example.bin"))


def read(index, **changes):
    caps = {
        "maximum_compressed_bytes": 4096,
        "maximum_compressed_frame_bytes": 1024,
        "maximum_frames": 10,
        "maximum_decompressed_bytes": 256,
        "maximum_frame_output_bytes": 128,
    }
    caps.update(changes)
    return tuple(
        container.read_region_frames_bounded(index, "unlisted_after_non_pl_hist_ls", **caps)
    )


def test_bounded_region_yields_each_real_frame(tmp_path: Path) -> None:
    assert read(region_index(tmp_path, (b"alpha", b"beta"))) == (b"alpha", b"beta")


@pytest.mark.parametrize("budget", ("maximum_compressed_bytes", "maximum_compressed_frame_bytes"))
def test_bounded_region_rejects_compressed_budgets(tmp_path: Path, budget: str) -> None:
    with pytest.raises(CorruptSaveError, match="compressed"):
        read(region_index(tmp_path, (b"alpha",)), **{budget: 1})


def test_bounded_region_caps_frame_headers_before_building_unlimited_index(tmp_path: Path) -> None:
    with pytest.raises(CorruptSaveError, match="too many frames"):
        read(region_index(tmp_path, (b"a", b"b")), maximum_frames=1)


def test_bounded_region_limits_decompressor_not_only_its_returned_bytes(tmp_path: Path) -> None:
    with pytest.raises(CorruptSaveError, match="more than 32 bytes"):
        read(region_index(tmp_path, (bytes(1000),)), maximum_frame_output_bytes=32)


def test_bounded_region_tracks_aggregate_output_between_frames(tmp_path: Path) -> None:
    with pytest.raises(CorruptSaveError, match="more than 4 bytes"):
        read(region_index(tmp_path, (bytes(60), bytes(60))), maximum_decompressed_bytes=64)


def test_bounded_region_rejects_nonpositive_work_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read(region_index(tmp_path, (b"a",)), maximum_frames=0)
