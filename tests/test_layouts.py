from __future__ import annotations

import dataclasses

import pytest
from syrupy.assertion import SnapshotAssertion

from fmsave._layouts import (
    FALLBACK_BUILD,
    GameInfoLayout,
    SaveSummaryLayout,
    find_layout,
    known_builds,
    registered_layouts,
)


def test_layout_registry_snapshot(snapshot: SnapshotAssertion) -> None:
    assert [dataclasses.asdict(entry) for entry in registered_layouts()] == snapshot


def test_known_builds() -> None:
    assert known_builds() == frozenset({"26.3.2+2329565"})
    assert FALLBACK_BUILD in known_builds()


def test_exact_schema_match() -> None:
    match = find_layout(GameInfoLayout, "game_info", 46, "")
    assert match.exact
    assert isinstance(match.layout, GameInfoLayout)


def test_unknown_schema_falls_back_to_build_then_newest() -> None:
    assert not find_layout(GameInfoLayout, "game_info", 999, "26.3.2+2329565").exact
    assert not find_layout(SaveSummaryLayout, "save_game_summary", None, "26.9.9+1").exact


def test_wrong_type_or_region_raises() -> None:
    with pytest.raises(LookupError):
        find_layout(SaveSummaryLayout, "game_info", 46, FALLBACK_BUILD)
    with pytest.raises(LookupError):
        find_layout(GameInfoLayout, "no_such_region", 1, FALLBACK_BUILD)
