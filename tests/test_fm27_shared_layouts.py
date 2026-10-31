"""Exact FM27 registrations for structures independently walked and cross-joined.

The existing component tests independently build fictional records for these shared
algorithms. These tests pin the explicit whitelist, not cross-edition fallback.
"""

from __future__ import annotations

import pytest

from fmsave._errors import UnsupportedGameError
from fmsave._layouts import find_layout
from fmsave._layouts import fm26_26_3_2 as observed
from fmsave.readers.affiliates import walk_affiliate_groups
from tests.fixtures.club_sections import feeder_body

BUILD = "27.0.0+2486695"
SHARED = (
    ("game_db", 4000, observed.NAME_POOLS),
    ("game_db", 4000, observed.CONTRACTS),
    ("game_db", 4000, observed.STAGE_TABLE),
    ("game_db", 4000, observed.STADIUM_TABLE),
    ("game_db", 4000, observed.COMPETITION_ID_PAIRS),
    ("game_db", 4000, observed.TAGGED_STREAM),
    ("game_db", 4000, observed.TRANSFER_WINDOWS),
    ("game_db", 4000, observed.FINANCE_CHAINS),
    ("game_db", 4000, observed.FACILITY_BYTE),
    ("humans", 24, observed.HUMANS),
    ("feeder_man", 5, observed.AFFILIATE_GROUPS),
    ("job_centre", 1, observed.JOB_CENTRE),
)


@pytest.mark.parametrize("region,schema,layout", SHARED, ids=lambda value: type(value).__name__)
def test_fm27_observed_structures_are_explicit_not_fallback(region, schema, layout) -> None:
    match = find_layout(type(layout), region, schema, BUILD)
    assert match.exact
    assert match.layout == layout
    with pytest.raises(UnsupportedGameError):
        find_layout(type(layout), region, schema + 1, BUILD)
    with pytest.raises(UnsupportedGameError):
        find_layout(type(layout), region, schema, "27.0.1+3000001")


def test_fm27_affiliate_groups_walk_every_count_and_reject_trailing_data() -> None:
    layout = find_layout(type(observed.AFFILIATE_GROUPS), "feeder_man", 5, BUILD).layout
    data = feeder_body(((1, 2), (3, 4, 5)))
    assert walk_affiliate_groups(data, layout, "example.bin") == ((1, 2), (3, 4, 5))
    from fmsave._errors import ReaderCheckError

    with pytest.raises(ReaderCheckError):
        walk_affiliate_groups(data + b"\x00", layout, "example.bin")


def test_fm27_training_whitelist_does_not_guess_unobserved_substructures() -> None:
    from fmsave._layouts import TrainingLayout

    layout = find_layout(TrainingLayout, "training_man", 32, BUILD).layout
    assert layout.block_lead_byte == 2
    assert layout.day_block_bytes == 8
    assert layout.day_block_lead_byte == 4
    assert layout.week_name_offset == 62
    assert layout.week_record_fixed_bytes == 80
    assert not layout.header_entries_supported
    assert not layout.mentoring_groups_supported


def test_fm27_injury_layouts_are_the_observed_fm26_layouts_registered_exactly() -> None:
    from fmsave._layouts import InjuryManagerLayout, InjuryTypeTableLayout

    types = find_layout(InjuryTypeTableLayout, "match_file", None, BUILD)
    manager = find_layout(InjuryManagerLayout, "injury_manager", 8, BUILD)
    assert types.exact and types.layout == observed.INJURY_TYPE_TABLE
    assert manager.exact and manager.layout == observed.INJURY_MANAGER
    assert types.layout.allow_match_entries
    assert manager.layout.allow_typed_rows
    assert not manager.layout.require_empty_lists
    with pytest.raises(UnsupportedGameError):
        find_layout(InjuryManagerLayout, "injury_manager", 9, BUILD)


def test_fm27_injury_checks_apply_to_early_season_sections_not_fragments() -> None:
    from fmsave._layouts import GateBounds

    bounds = find_layout(GateBounds, "game_db", 4000, BUILD).layout
    assert bounds.injury_manager_minimum_applies_from_bytes == 16 * 1024
    assert bounds.injury_log_recent_team_matches == (0.75, None)
    assert observed.GATE_BOUNDS.injury_manager_minimum_applies_from_bytes == 256 * 1024
    assert observed.GATE_BOUNDS.injury_log_recent_team_matches == (0.90, None)


def test_fm27_tactics_whitelist_allows_only_observed_empty_variants() -> None:
    from fmsave._layouts import TacticsLayout

    layout = find_layout(TacticsLayout, "tactics_man", 26, BUILD).layout
    assert layout.selection_end_marker == b"\x44\x00"
    assert not layout.tactic_records_supported
    assert not layout.named_routines_supported


def test_fm27_match_whitelist_reads_rows_only_behind_declared_histories() -> None:
    from fmsave._layouts import MatchRecordLayout

    layout = find_layout(MatchRecordLayout, "game_db", 4000, BUILD).layout
    assert layout.nonempty_supported
    assert layout.declared_histories_required
    assert not observed.MATCH_RECORDS.declared_histories_required
    cache = layout.cache_layout
    assert cache is not None
    assert cache.header_marker == b"\x0c\x07"
    assert cache.reference_bytes == 15
    assert cache.medical_row_bytes == 33
    assert cache.nullable_suffix_bytes == (43, 60, 70, 14, 18)
    assert cache.nullable_prefix_second_marker == b"\x01\x03"
    assert cache.medical_row_lead_byte == 3
    assert cache.nullable_suffix_first_marker == b"\x01\x04"
    assert cache.nullable_suffix_first_date_offset == 38


def test_fm27_sponsor_boundary_does_not_enable_unknown_schemas_or_builds() -> None:
    layout_type = type(observed.SPONSOR_CHAINS)
    assert find_layout(layout_type, "game_db", 4000, BUILD).exact
    for schema, build in ((4001, BUILD), (4000, "27.0.1+3000001")):
        with pytest.raises(UnsupportedGameError):
            find_layout(layout_type, "game_db", schema, build)
