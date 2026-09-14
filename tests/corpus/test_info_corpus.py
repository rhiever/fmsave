"""Corpus checks for fmsave.open and Save.info. Output never includes real save content."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import pytest

import fmsave
from fmsave._container import HEADER_SIZE, open_verified, walk_frame_headers, walk_frames

pytestmark = [pytest.mark.corpus, pytest.mark.corpus_fast]

OPEN_SECONDS_TARGET = 1.0
MINIMUM_SECTIONS = 80
MINIMUM_UNLISTED_FRAMES = 1000
UNLISTED_REGION = "unlisted_after_non_pl_hist_ls"


def test_info_matches_golden_values(
    corpus_saves: dict[str, fmsave.Save], golden_values: dict[str, Any]
) -> None:
    for relative_name, career_save in corpus_saves.items():
        expected_info = golden_values[relative_name]["info"]
        save_info = career_save.info
        label = Path(relative_name).name
        assert save_info.game == expected_info["game"], label
        assert save_info.build == expected_info["build"], label
        assert save_info.build_number == expected_info["build_number"], label
        assert save_info.known_build == expected_info["known_build"], label
        assert save_info.db_version == expected_info["db_version"], label
        observed_date = save_info.game_date.isoformat() if save_info.game_date else None
        assert observed_date == expected_info["game_date"], label
        assert save_info.time_slot == expected_info["time_slot"], label
        observed_name_digest = hashlib.sha256(save_info.save_name.encode("utf-8")).hexdigest()
        assert observed_name_digest == expected_info["save_name_sha256"], label
        assert dict(save_info.section_schemas) == expected_info["section_schemas"], label


def test_open_meets_time_target(corpus_save_paths: dict[str, Path]) -> None:
    for save_path in corpus_save_paths.values():
        fmsave.open(save_path).close()  # warm the operating system file cache
        started = time.perf_counter()
        career_save = fmsave.open(save_path)
        elapsed_seconds = time.perf_counter() - started
        career_save.close()
        assert elapsed_seconds < OPEN_SECONDS_TARGET, (
            f"{save_path.name} opened in {elapsed_seconds:.2f} s"
        )


def test_directory_agrees_with_frame_walk(corpus_saves: dict[str, fmsave.Save]) -> None:
    for relative_name, career_save in corpus_saves.items():
        label = Path(relative_name).name
        container_index = career_save._require_open()
        with open_verified(container_index) as save_file:
            spans = walk_frame_headers(
                save_file, HEADER_SIZE, container_index.trailer_offset, container_index.file_name
            )
        span_sizes = {span.offset: span.size for span in spans}
        for entry in container_index.entries:
            assert span_sizes.get(entry.frame_offset) == entry.compressed_size, label
        assert len(container_index.sections) >= MINIMUM_SECTIONS, label
        unlisted_region_names = [
            name for name, region in container_index.regions.items() if region.entry is None
        ]
        assert unlisted_region_names == [UNLISTED_REGION], label
        assert len(walk_frames(container_index, UNLISTED_REGION)) >= MINIMUM_UNLISTED_FRAMES, label
