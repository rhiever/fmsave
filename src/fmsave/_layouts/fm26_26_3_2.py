"""Layouts for FM26 build 26.3.2+2329565, the final FM26 update."""

from __future__ import annotations

from fmsave._layouts import GameInfoLayout, LayoutEntry, SaveSummaryLayout

BUILD = "26.3.2+2329565"

GAME_INFO = GameInfoLayout(
    db_version_length_offset=8,
    max_db_version_bytes=64,
    build_number_offsets_after_db_version=(34, 38, 202),
    game_date_offset_after_db_version=172,
)

SAVE_SUMMARY = SaveSummaryLayout(
    version_pattern=r"(?<![0-9.])([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,4})\+([0-9]{1,10})(?![0-9])",
    max_version_bytes=32,
)

LAYOUTS: tuple[LayoutEntry, ...] = (
    LayoutEntry(region="game_info", schema=46, build=BUILD, layout=GAME_INFO),
    LayoutEntry(region="save_game_summary", schema=29, build=BUILD, layout=SAVE_SUMMARY),
)
