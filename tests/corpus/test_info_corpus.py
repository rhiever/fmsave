"""Corpus checks for fmsave.open and Save.info. Output never includes real save content.

Values read from a save never appear in an assert or a message: each check reduces to a
boolean, and failures are reported by file name and field name only.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import pytest

import fmsave
from fmsave._container import HEADER_SIZE, open_verified, walk_frame_headers, walk_frames
from tests.corpus.reporting import CorpusMismatches

pytestmark = [pytest.mark.corpus, pytest.mark.corpus_fast]

OPEN_SECONDS_TARGET = 1.0
TIMED_OPENS_PER_SAVE = 3
MINIMUM_SECTIONS = 80
MINIMUM_UNLISTED_FRAMES = 1000
UNLISTED_REGION = "unlisted_after_non_pl_hist_ls"
DIRECT_INFO_FIELDS = ("game", "build", "build_number", "known_build", "db_version", "time_slot")


def test_info_matches_golden_values(
    corpus_saves: dict[str, fmsave.Save], golden_values: dict[str, Any]
) -> None:
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = Path(relative_name).name
        golden_entry: Any = golden_values.get(relative_name)
        expected_info: Any = golden_entry.get("info") if isinstance(golden_entry, dict) else None
        if not isinstance(expected_info, dict):
            mismatches.note(f"{label}: no golden values")
            continue
        save_info = career_save.info
        for field_name in DIRECT_INFO_FIELDS:
            field_matches = getattr(save_info, field_name) == expected_info.get(field_name)
            mismatches.check(label, field_name, field_matches)
        game_date = save_info.game_date
        observed_date = game_date.isoformat() if game_date is not None else None
        date_matches = observed_date == expected_info.get("game_date")
        mismatches.check(label, "game_date", date_matches)
        observed_name_digest = hashlib.sha256(save_info.save_name.encode("utf-8")).hexdigest()
        name_matches = observed_name_digest == expected_info.get("save_name_sha256")
        mismatches.check(label, "save_name_sha256", name_matches)
        schemas_match = dict(save_info.section_schemas) == expected_info.get("section_schemas")
        mismatches.check(label, "section_schemas", schemas_match)
    mismatches.fail_if_any()


def test_open_meets_time_target(corpus_save_paths: dict[str, Path]) -> None:
    mismatches = CorpusMismatches()
    for save_path in corpus_save_paths.values():
        fmsave.open(save_path).close()  # warm the operating system file cache
        timed_seconds: list[float] = []
        for _timed_open in range(TIMED_OPENS_PER_SAVE):
            started = time.perf_counter()
            career_save = fmsave.open(save_path)
            timed_seconds.append(time.perf_counter() - started)
            career_save.close()
        fastest_seconds = min(timed_seconds)
        if fastest_seconds >= OPEN_SECONDS_TARGET:
            mismatches.note(
                f"{save_path.name}: fastest of {TIMED_OPENS_PER_SAVE} opens "
                f"took {fastest_seconds:.2f} s"
            )
    mismatches.fail_if_any()


def test_directory_agrees_with_frame_walk(corpus_saves: dict[str, fmsave.Save]) -> None:
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = Path(relative_name).name
        container_index = career_save._require_open()
        with open_verified(container_index) as save_file:
            spans = walk_frame_headers(
                save_file, HEADER_SIZE, container_index.trailer_offset, container_index.file_name
            )
        span_sizes = {span.offset: span.size for span in spans}
        entries_match_frames = all(
            span_sizes.get(entry.frame_offset) == entry.compressed_size
            for entry in container_index.entries
        )
        mismatches.check(label, "directory entry frame sizes", entries_match_frames)
        section_count = len(container_index.sections)
        mismatches.check(label, "section count", section_count >= MINIMUM_SECTIONS)
        unlisted_region_names = [
            name for name, region in container_index.regions.items() if region.entry is None
        ]
        mismatches.check(label, "unlisted regions", unlisted_region_names == [UNLISTED_REGION])
        unlisted_frame_count = (
            len(walk_frames(container_index, UNLISTED_REGION))
            if UNLISTED_REGION in container_index.regions
            else 0
        )
        frames_enough = unlisted_frame_count >= MINIMUM_UNLISTED_FRAMES
        mismatches.check(label, "unlisted frame count", frames_enough)
    mismatches.fail_if_any()
