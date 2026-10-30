"""Partial layouts observed on one registered FM27 build.

These registrations establish structural compatibility, not in-game verification.
Unregistered layouts must not fall back to another game edition.
"""

from __future__ import annotations

from dataclasses import replace

from fmsave._layouts import GameInfoLayout, LayoutEntry, SaveSummaryLayout, SummaryStringsLayout
from fmsave._layouts.fm26_26_3_2 import (
    AFFILIATE_GROUPS,
    CLUB_RECORDS,
    CLUB_STATUSES,
    COMPETITION_ID_PAIRS,
    CONTRACTS,
    FACILITY_BYTE,
    FINANCE_CHAINS,
    GATE_BOUNDS,
    HUMANS,
    JOB_CENTRE,
    NAME_POOLS,
    NATION_TABLE,
    PLAYER_RECORDS,
    SPONSOR_CHAINS,
    STADIUM_TABLE,
    STAGE_TABLE,
    TAGGED_STREAM,
    TEAM_LISTS,
    TRANSFER_WINDOWS,
)
from fmsave._layouts.fm26_26_3_2 import (
    CLUB_TABLE as FM26_CLUB_TABLE,
)
from fmsave._layouts.fm26_26_3_2 import (
    INJURY_MANAGER as FM26_INJURY_MANAGER,
)
from fmsave._layouts.fm26_26_3_2 import (
    INJURY_TYPE_TABLE as FM26_INJURY_TYPE_TABLE,
)
from fmsave._layouts.fm26_26_3_2 import (
    MATCH_RECORDS as FM26_MATCH_RECORDS,
)
from fmsave._layouts.fm26_26_3_2 import (
    PERSON_BLOCKS as FM26_PERSON_BLOCKS,
)
from fmsave._layouts.fm26_26_3_2 import (
    SEASON_HISTORY as FM26_SEASON_HISTORY,
)
from fmsave._layouts.fm26_26_3_2 import (
    SEASON_STATS as FM26_SEASON_STATS,
)
from fmsave._layouts.fm26_26_3_2 import (
    STAFF as FM26_STAFF,
)
from fmsave._layouts.fm26_26_3_2 import (
    TACTICS as FM26_TACTICS,
)
from fmsave._layouts.fm26_26_3_2 import (
    TRAINING as FM26_TRAINING,
)

BUILD = "27.0.0+2486695"
# No full reader set or independent UI validation exists for this build.
KNOWN_BUILDS: tuple[str, ...] = ()

GAME_INFO = GameInfoLayout(
    db_version_length_offset=8,
    max_db_version_bytes=64,
    build_number_offsets_after_db_version=(38,),
    game_date_offset_after_db_version=174,
    late_build_number_window_after_db_version=(382, 446),
    filename_count_offset_after_db_version=165,
)
SAVE_SUMMARY = SaveSummaryLayout(
    version_pattern=r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,4})\+([0-9]{1,10})",
    max_version_bytes=32,
)
SUMMARY_STRINGS = SummaryStringsLayout(
    strings_start_offset=8, string_length_range=(2, 120), lowest_code_point=0x20
)
# The counted nation walk, ordinal identities and duplicated database ids all validate.
# No other database layout is implied by this registration. Require both checks even
# for tiny fragments: an empty or ambiguous input must never look like success.
NATION_BOUNDS = replace(
    GATE_BOUNDS,
    nation_tables_found=(1, 1),
    nation_database_id_copies=(1, 1),
    season_stats_records_keyed_to_players=(1, 1),
    season_stats_players_with_record=(1, 1),
    season_stats_overall_sums_competitions=(1, 1),
    season_stats_minutes_in_range=(1, 1),
)
CLUB_TABLE = replace(
    FM26_CLUB_TABLE,
    full_finance=(replace(FM26_CLUB_TABLE.full_finance[0], lead_bytes=66),)
    + FM26_CLUB_TABLE.full_finance[1:],
    after_finance=tuple(
        replace(step, count_bytes=2) if index in (5, 6, 7) else step
        for index, step in enumerate(FM26_CLUB_TABLE.after_finance)
    ),
)

PERSON_BLOCKS = replace(
    FM26_PERSON_BLOCKS,
    personality_offset_from_birth=22,
    date_zero_bytes_offset_from_birth=15,
    nation_id_offset_from_birth=14,
    relation_present_offset_from_birth=38,
    relation_count_offset_from_birth=39,
    relation_entries_offset_from_birth=40,
    require_unique_candidate=True,
)

SEASON_HISTORY = replace(
    FM26_SEASON_HISTORY, archive_header=b"\x03\x01tmc.\x07\x00", unit_bytes=168, footer=b"\x07\x00"
)

SEASON_STATS = replace(
    FM26_SEASON_STATS,
    line_marker=b"\x01\x07",
    line_bytes=155,
    unsupported_fields=("goals_outside_box", "pressures_attempted", "pressures_completed"),
    require_unique_keys=True,
)

STAFF = replace(FM26_STAFF, list_count_bytes=2)

TRAINING = replace(
    FM26_TRAINING,
    block_lead_byte=2,
    day_block_bytes=8,
    day_block_lead_byte=4,
    week_name_offset=62,
    week_record_fixed_bytes=80,
    header_entries_supported=False,
    mentoring_groups_supported=False,
)

INJURY_MANAGER = replace(FM26_INJURY_MANAGER, allow_typed_rows=False, require_empty_lists=True)
INJURY_TYPE_TABLE = replace(FM26_INJURY_TYPE_TABLE, allow_match_entries=False)

TACTICS = replace(
    FM26_TACTICS,
    selection_end_marker=b"\x44\x00",
    tactic_records_supported=False,
    named_routines_supported=False,
)

_FM26_MATCH_CACHE = FM26_MATCH_RECORDS.cache_layout
assert _FM26_MATCH_CACHE is not None
MATCH_CACHE = replace(
    _FM26_MATCH_CACHE,
    header_marker=b"\x0c\x07",
    reference_bytes=15,
    medical_row_bytes=33,
    nullable_suffix_bytes=(43, 60, 70, 14, 18),
    nullable_prefix_second_marker=b"\x01\x03",
    medical_row_lead_byte=3,
    nullable_suffix_first_marker=b"\x01\x04",
    nullable_suffix_first_date_offset=38,
)
MATCH_RECORDS = replace(FM26_MATCH_RECORDS, cache_layout=MATCH_CACHE, nonempty_supported=False)

LAYOUTS = (
    LayoutEntry("game_info", 47, BUILD, GAME_INFO),
    LayoutEntry("save_game_summary", 31, BUILD, SAVE_SUMMARY),
    LayoutEntry("save_game_summary", 31, BUILD, SUMMARY_STRINGS),
    LayoutEntry("game_db", 4000, BUILD, NATION_TABLE),
    LayoutEntry("game_db", 4000, BUILD, NATION_BOUNDS),
    LayoutEntry("game_db", 4000, BUILD, CLUB_RECORDS),
    LayoutEntry("game_db", 4000, BUILD, CLUB_TABLE),
    LayoutEntry("game_db", 4000, BUILD, TEAM_LISTS),
    LayoutEntry("game_db", 4000, BUILD, CLUB_STATUSES),
    LayoutEntry("game_db", 4000, BUILD, PERSON_BLOCKS),
    LayoutEntry("game_db", 4000, BUILD, PLAYER_RECORDS),
    LayoutEntry("game_db", 4000, BUILD, STAFF),
    LayoutEntry("game_db", 4000, BUILD, STADIUM_TABLE),
    LayoutEntry("game_db", 4000, BUILD, MATCH_RECORDS),
    LayoutEntry("unlisted_after_non_pl_hist_ls", None, BUILD, SEASON_HISTORY),
    LayoutEntry("unlisted_after_non_pl_hist_ls", None, BUILD, SEASON_STATS),
    *(
        LayoutEntry("game_db", 4000, BUILD, layout)
        for layout in (
            NAME_POOLS,
            CONTRACTS,
            STAGE_TABLE,
            COMPETITION_ID_PAIRS,
            TAGGED_STREAM,
            TRANSFER_WINDOWS,
            FINANCE_CHAINS,
            SPONSOR_CHAINS,
            FACILITY_BYTE,
        )
    ),
    LayoutEntry("humans", 24, BUILD, HUMANS),
    LayoutEntry("feeder_man", 5, BUILD, AFFILIATE_GROUPS),
    LayoutEntry("job_centre", 1, BUILD, JOB_CENTRE),
    LayoutEntry("training_man", 32, BUILD, TRAINING),
    LayoutEntry("injury_manager", 8, BUILD, INJURY_MANAGER),
    LayoutEntry("match_file", None, BUILD, INJURY_TYPE_TABLE),
    LayoutEntry("tactics_man", 26, BUILD, TACTICS),
)
