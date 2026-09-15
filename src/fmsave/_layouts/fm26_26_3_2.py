"""Layouts for FM26 build 26.3.2+2329565, the final FM26 update."""

from __future__ import annotations

import struct

from fmsave._layouts import (
    FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    ClubRecordLayout,
    ClubStatusLayout,
    GameInfoLayout,
    LayoutEntry,
    NamePoolLayout,
    SaveSummaryLayout,
    TeamListLayout,
)

BUILD = "26.3.2+2329565"

GAME_INFO = GameInfoLayout(
    db_version_length_offset=8,
    max_db_version_bytes=64,
    build_number_offsets_after_db_version=(34, 38, 202),
    game_date_offset_after_db_version=172,
)

SAVE_SUMMARY = SaveSummaryLayout(
    version_pattern=r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,4})\+([0-9]{1,10})",
    max_version_bytes=32,
)

NAME_POOLS = NamePoolLayout(
    signature=struct.pack("<6I", 46421, 0, 1024, 256, 2048, 0),
    max_name_bytes=64,
    minimum_entries_per_pool=50_000,
    minimum_applies_from_bytes=FULL_SAVE_MINIMUM_GAME_DB_BYTES,
)

CLUB_RECORDS = ClubRecordLayout(
    anchor=b"\xff\xff\xff\xff",
    anchor_offset=17,
    club_index_offset=0,
    uid_offset=4,
    uid_copy_offset=8,
    zero_byte_offset=12,
    nation_offset=13,
    fa_nation_offset=21,
    nation_copy_offset=25,
    city_offset=29,
    long_name_offset=39,
    nation_id_range=(1, 999),
    max_name_bytes=64,
    stop_gap_bytes=64 * 1024,
)

# A null date is day 1 of 1900; the float anchor is 1.0.
TEAM_LISTS = TeamListLayout(
    null_date_triple=struct.pack("<HH", 1, 1900) * 3,
    float_anchor=struct.pack("<f", 1.0),
    float_anchor_offset=33,
    minimum_float_anchor_record_offset=40,
    counts_offset=37,
    first_entry_bytes=25,
    first_entry_lead_byte=0x02,
    second_entry_bytes=12,
    second_entry_lead_byte=0x01,
    filler_bytes=9,
    team_count_range=(1, 8),
    team_id_range=(1, 3_000_000),
)

CLUB_STATUSES = ClubStatusLayout(
    ordinal_offset=-4,
    ordinal_limit=200_000,
    kind_offset=8,
    normal_kind=0x0A,
    stub_kind=0x0B,
    position_offset=10,
    reputation_offset=11,
    reputation_range=(1, 10_000),
    # A power of two at least four times the largest gap between consecutive accepted status
    # records measured on real saves.
    search_window_bytes=256 * 1024,
    maximum_leading_misses=16,
)

LAYOUTS: tuple[LayoutEntry, ...] = (
    LayoutEntry(region="game_info", schema=46, build=BUILD, layout=GAME_INFO),
    LayoutEntry(region="save_game_summary", schema=29, build=BUILD, layout=SAVE_SUMMARY),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=NAME_POOLS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=CLUB_RECORDS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=TEAM_LISTS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=CLUB_STATUSES),
)
