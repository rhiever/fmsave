from __future__ import annotations

import dataclasses

import pytest
from syrupy.assertion import SnapshotAssertion

import fmsave._layouts as layouts_module
from fmsave._layouts import (
    FALLBACK_BUILD,
    FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    FULL_SAVE_MINIMUM_SPAN_BYTES,
    SPAN_CARRY_OVER_BYTES,
    ClubRecordLayout,
    FixtureCalendarLayout,
    GameInfoLayout,
    GateBounds,
    LayoutEntry,
    LeagueTableLayout,
    NamePoolLayout,
    RulesPreambleLayout,
    SaveSummaryLayout,
    find_layout,
    known_builds,
    registered_layouts,
)
from fmsave.readers._common import SPAN_REGION

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


def test_name_pool_layout_is_registered_for_game_db() -> None:
    match = find_layout(NamePoolLayout, "game_db", 4000, "")
    assert match.exact
    assert match.layout.minimum_applies_from_bytes == FULL_SAVE_MINIMUM_GAME_DB_BYTES


def test_gate_bounds_are_registered_for_game_db_with_the_full_save_threshold() -> None:
    match = find_layout(GateBounds, "game_db", 4000, "")
    assert match.exact
    assert match.layout.minimum_applies_from_bytes == FULL_SAVE_MINIMUM_GAME_DB_BYTES
    assert match.layout.players_minimum == (5_000, None)
    assert match.layout.past_dated_tail_ends == (None, 0.05)


def test_span_layouts_are_registered_for_the_span_region_without_a_schema() -> None:
    for layout_type in (FixtureCalendarLayout, LeagueTableLayout, RulesPreambleLayout):
        match = find_layout(layout_type, SPAN_REGION, None, FALLBACK_BUILD)
        assert match.exact, layout_type.__name__
        assert isinstance(match.layout, layout_type)


def test_the_span_carry_over_is_far_longer_than_the_longest_span_record() -> None:
    fixtures = find_layout(FixtureCalendarLayout, SPAN_REGION, None, FALLBACK_BUILD).layout
    tables = find_layout(LeagueTableLayout, SPAN_REGION, None, FALLBACK_BUILD).layout
    longest_table_block = (
        tables.matches_offset
        + tables.row_bytes * 2 * tables.rounds_per_venue_range[1]
        - tables.team_id_offset
    )
    assert fixtures.record_bytes - fixtures.marker_byte_offset < SPAN_CARRY_OVER_BYTES
    assert longest_table_block < SPAN_CARRY_OVER_BYTES


def test_gate_bounds_carry_the_span_threshold() -> None:
    match = find_layout(GateBounds, "game_db", 4000, "")
    assert match.layout.span_minimum_applies_from_bytes == FULL_SAVE_MINIMUM_SPAN_BYTES


def test_every_game_db_schema_with_club_records_has_gate_bounds() -> None:
    club_record_keys = {
        (entry.schema, entry.build)
        for entry in registered_layouts()
        if entry.region == "game_db" and isinstance(entry.layout, ClubRecordLayout)
    }
    gate_bounds_keys = {
        (entry.schema, entry.build)
        for entry in registered_layouts()
        if entry.region == "game_db" and isinstance(entry.layout, GateBounds)
    }
    assert club_record_keys
    assert club_record_keys <= gate_bounds_keys


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
