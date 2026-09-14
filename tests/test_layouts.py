from __future__ import annotations

import dataclasses

import pytest
from syrupy.assertion import SnapshotAssertion

import fmsave._layouts as layouts_module
from fmsave._layouts import (
    FALLBACK_BUILD,
    GameInfoLayout,
    LayoutEntry,
    SaveSummaryLayout,
    find_layout,
    known_builds,
    registered_layouts,
)

SECOND_BUILD = "26.9.0+2500000"


def test_layout_registry_snapshot(snapshot: SnapshotAssertion) -> None:
    assert [dataclasses.asdict(entry) for entry in registered_layouts()] == snapshot


def test_known_builds() -> None:
    assert known_builds() == frozenset({"26.3.2+2329565"})
    assert FALLBACK_BUILD in known_builds()


def test_exact_schema_match() -> None:
    match = find_layout(GameInfoLayout, "game_info", 46, "")
    assert match.exact
    assert isinstance(match.layout, GameInfoLayout)


def test_unknown_schema_falls_back_to_build_then_fallback_build() -> None:
    assert not find_layout(GameInfoLayout, "game_info", 999, "26.3.2+2329565").exact
    assert not find_layout(SaveSummaryLayout, "save_game_summary", None, "26.9.9+1").exact


def test_build_match_is_used_when_schema_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    second_game_info = GameInfoLayout(
        db_version_length_offset=12,
        max_db_version_bytes=48,
        build_number_offsets_after_db_version=(40, 44),
        game_date_offset_after_db_version=180,
    )
    schemaless_summary = SaveSummaryLayout(
        version_pattern=r"([0-9]{1,3})\.([0-9]{1,3})", max_version_bytes=16
    )
    extended_layouts = registered_layouts() + (
        LayoutEntry(region="game_info", schema=60, build=SECOND_BUILD, layout=second_game_info),
        LayoutEntry(
            region="save_game_summary", schema=None, build=SECOND_BUILD, layout=schemaless_summary
        ),
    )
    monkeypatch.setattr(layouts_module, "registered_layouts", lambda: extended_layouts)

    game_info_match = find_layout(GameInfoLayout, "game_info", 999, SECOND_BUILD)
    assert game_info_match.layout == second_game_info
    assert not game_info_match.exact

    summary_match = find_layout(SaveSummaryLayout, "save_game_summary", 999, SECOND_BUILD)
    assert summary_match.layout == schemaless_summary
    assert summary_match.exact


def test_wrong_type_or_region_raises() -> None:
    with pytest.raises(LookupError):
        find_layout(SaveSummaryLayout, "game_info", 46, FALLBACK_BUILD)
    with pytest.raises(LookupError):
        find_layout(GameInfoLayout, "no_such_region", 1, FALLBACK_BUILD)
