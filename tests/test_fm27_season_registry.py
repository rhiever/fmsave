"""The production whitelist must use the independently tested FM27 season shape."""

from __future__ import annotations

import struct

from fmsave._layouts import SeasonHistoryLayout, SeasonStatsLayout, find_layout
from fmsave.readers.season_history import walk_history_index
from fmsave.readers.season_stats import SeasonPlayer, build_season_stats, walk_season_stats
from tests.fixtures.season_history import history_index
from tests.test_fm27_season_stats import OMITTED, extended_body

BUILD = "27.0.0+2486695"
REGION = "unlisted_after_non_pl_hist_ls"


def test_fm27_season_whitelist_keeps_unmapped_metrics_unknown() -> None:
    layout = find_layout(SeasonStatsLayout, REGION, None, BUILD).layout
    assert layout.require_unique_keys
    assert layout.unsupported_fields == OMITTED
    assert len(walk_season_stats(extended_body(), layout, "example.bin").records) == 1
    body = extended_body()
    rows, _ = build_season_stats(
        walk_season_stats(body, layout, "example.bin"),
        body,
        {11: SeasonPlayer(900001, "Alex Example", 70001, False)},
        {},
        {},
        layout,
    )
    assert rows[0].goals == 1
    assert rows[0].expected_goals == 1.25
    assert all(getattr(rows[0], name) is None for name in OMITTED)


def test_fm27_history_index_uses_new_unit_size_and_footer() -> None:
    layout = find_layout(SeasonHistoryLayout, REGION, None, BUILD).layout
    body = history_index(((0,),))
    body = body[:-6] + struct.pack("<I", 168) + b"\x07\x00"
    index = walk_history_index(body, "example.bin", layout)
    assert index.lists == ((0,),)
