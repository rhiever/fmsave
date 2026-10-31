"""Bounded raw FM27 data are explicitly separate from semantic fixture tables."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest

import fmsave
import fmsave._save
from fmsave._container import (
    FM27_FRAME_DECOMPRESSED_CAP,
    FM27_TOTAL_DECOMPRESSED_CAP,
    read_index,
    read_section,
)
from fmsave.readers.fm27_span import Fm27SpanLimits
from tests.fixtures.container import SectionFrame, build_container_fragment, section_body, zstd
from tests.test_fm27_experimental import fm27_fragment
from tests.test_fm27_span import core, packet, rules


def span_fragment(tmp_path: Path) -> Path:
    index = read_index(fm27_fragment(tmp_path))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    raw = core() + b"\x01" + packet() + core(home=1301, away=1302) + rules()
    sections.append(
        SectionFrame(
            "non_pl_hist_ls",
            section_body(".dat", 4, bytes(4)),
            unlisted_frames_after=(zstd.compress(raw),),
        )
    )
    return build_container_fragment(sections).write(tmp_path / "raw-span.bin")


def test_raw_fm27_span_is_explicit_cached_bounded_and_survives_close(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(span_fragment(tmp_path))
    with save:
        span = save.experimental_span()
        assert save.experimental_span() is span
        assert len(span.fixtures) == 2
        assert span.fixtures[0].played is None
        assert span.fixtures[1].played is True
        assert span.fixtures[1].home_goals == 2
        assert len(span.rules) == 1
    assert span.fixtures[0].home_team_id == 1201
    with pytest.raises(fmsave.SaveClosedError):
        save.experimental_span()


def test_validation_raw_span_counts_never_include_raw_identities(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(span_fragment(tmp_path))
    with save:
        report = fmsave.validate_save(save)
    counts = report.experimental_counts
    assert counts["raw_fixture_cores"] == 2
    assert counts["fixtures_with_owned_status"] == 1
    assert counts["raw_rules_parents"] == 1
    assert counts["span_parse_errors"] == 0
    rendered = json.dumps(report.to_json_dict())
    assert '"home_team_id"' not in rendered
    assert '"promotion_quad"' not in rendered


def test_raw_span_is_not_an_fm26_fallback(tmp_path: Path) -> None:
    path = build_container_fragment().write(tmp_path / "example.bin")
    with fmsave.open(path) as save, pytest.raises(fmsave.UnsupportedGameError):
        save.experimental_span()
    assert "experimental_counts" not in fmsave.validate_save(fmsave.open(path)).to_json_dict()


def test_raw_span_byte_limits_sit_inside_the_fm27_read_budget() -> None:
    limits = Fm27SpanLimits()
    assert limits.maximum_frame_bytes <= limits.maximum_span_bytes
    assert limits.maximum_span_bytes <= FM27_TOTAL_DECOMPRESSED_CAP
    assert limits.maximum_frame_bytes <= FM27_FRAME_DECOMPRESSED_CAP


def test_integrated_raw_span_limits_decompression_before_parser_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame_limit = 64 * 1024
    monkeypatch.setattr(
        fmsave._save, "Fm27SpanLimits", partial(Fm27SpanLimits, maximum_frame_bytes=frame_limit)
    )
    index = read_index(fm27_fragment(tmp_path))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    sections.append(
        SectionFrame(
            "non_pl_hist_ls",
            section_body(".dat", 4, bytes(4)),
            unlisted_frames_after=(zstd.compress(bytes(frame_limit + 1)),),
        )
    )
    path = build_container_fragment(sections).write(tmp_path / "large-output.bin")
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save, pytest.raises(fmsave.CorruptSaveError, match=f"more than {frame_limit} bytes"):
        save.experimental_span()
