from dataclasses import replace

import pytest

from fmsave._checks import GateCheckError, enforce, evaluate_tactics
from fmsave._layouts.fm26_26_3_2 import GATE_BOUNDS
from fmsave._reader_stats import TacticStats
from fmsave.readers.tactics import find_tactics_layout, walk_tactic_blocks
from tests.fixtures.tactics import (
    NO_SELECTOR,
    NO_TACTICS_VALUE,
    selection_part_bytes,
    tactics_man_body,
)


@pytest.fixture(params=[False, True], ids=["empty-header", "national-only"])
def empty_club_stats(request: pytest.FixtureRequest) -> TacticStats:
    blocks = (
        (
            selection_part_bytes(
                team_id=999_001,
                label="",
                slots=(),
                list_a=(),
                list_b=(),
                single=NO_SELECTOR,
                tactics_value=NO_TACTICS_VALUE,
                tactic_count=0,
            ),
        )
        if request.param
        else ()
    )
    section = tactics_man_body(selector=123, blocks=blocks)
    rows, counts = walk_tactic_blocks(section, (101, 102), find_tactics_layout(26, ""), "synthetic")
    assert not rows
    assert counts.header_blocks == counts.stored_blocks == len(blocks)
    return TacticStats(
        managed_club_exists=True,
        club_team_count=2,
        header_blocks=counts.header_blocks,
        stored_blocks=counts.stored_blocks,
        stored_club_blocks=counts.stored_club_blocks,
        blocks_found=counts.blocks_found,
        selector_matches=True,
        selection_selectors=0,
        selection_selectors_resolved=0,
        selection_selectors_at_club=0,
        tactic_blocks=0,
        tactic_blocks_count_matching=0,
        stored_tactics=0,
        preset_tactics=0,
        slot_walks_complete=0,
        oop_index_permutations=0,
        routine_blocks=0,
        routine_blocks_complete=0,
        routines=0,
        named_routines=0,
    )


def test_declared_empty_club_inventory_passes_strict(empty_club_stats: TacticStats) -> None:
    gates = evaluate_tactics(empty_club_stats, GATE_BOUNDS, 100 * 1024 * 1024)
    assert all(gate.passed for gate in gates)
    assert not enforce("tactics", gates, strict=True)


@pytest.mark.parametrize("mismatch", ["header", "locator"])
def test_empty_club_inventory_does_not_excuse_structural_mismatch(
    empty_club_stats: TacticStats, mismatch: str
) -> None:
    stats = (
        replace(empty_club_stats, header_blocks=empty_club_stats.header_blocks + 1)
        if mismatch == "header"
        else replace(empty_club_stats, blocks_found=1)
    )
    gates = evaluate_tactics(stats, GATE_BOUNDS, 100 * 1024 * 1024)
    with pytest.raises(GateCheckError, match="tactics_team_blocks_match_club"):
        enforce("tactics", gates, strict=True)
