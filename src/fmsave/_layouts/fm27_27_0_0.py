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
    JOB_CENTRE,
    NAME_POOLS,
    NATION_TABLE,
    PLAYER_RECORDS,
    STADIUM_TABLE,
    STAGE_TABLE,
    SUSPENSIONS,
    TAGGED_STREAM,
    TEAM_LISTS,
    TRANSFER_WINDOWS,
)
from fmsave._layouts.fm26_26_3_2 import (
    CLUB_TABLE as FM26_CLUB_TABLE,
)
from fmsave._layouts.fm26_26_3_2 import (
    FIXTURE_CALENDAR as FM26_FIXTURE_CALENDAR,
)
from fmsave._layouts.fm26_26_3_2 import (
    HUMANS as FM26_HUMANS,
)
from fmsave._layouts.fm26_26_3_2 import (
    INJURY_MANAGER as FM26_INJURY_MANAGER,
)
from fmsave._layouts.fm26_26_3_2 import (
    INJURY_TYPE_TABLE as FM26_INJURY_TYPE_TABLE,
)
from fmsave._layouts.fm26_26_3_2 import (
    LEAGUE_TABLES as FM26_LEAGUE_TABLES,
)
from fmsave._layouts.fm26_26_3_2 import (
    MATCH_RECORDS as FM26_MATCH_RECORDS,
)
from fmsave._layouts.fm26_26_3_2 import (
    MATCH_SUMMARIES as FM26_MATCH_SUMMARIES,
)
from fmsave._layouts.fm26_26_3_2 import (
    PERSON_BLOCKS as FM26_PERSON_BLOCKS,
)
from fmsave._layouts.fm26_26_3_2 import (
    RULES_PREAMBLES as FM26_RULES_PREAMBLES,
)
from fmsave._layouts.fm26_26_3_2 import (
    SEASON_HISTORY as FM26_SEASON_HISTORY,
)
from fmsave._layouts.fm26_26_3_2 import (
    SEASON_STATS as FM26_SEASON_STATS,
)
from fmsave._layouts.fm26_26_3_2 import (
    SPONSOR_CHAINS as FM26_SPONSOR_CHAINS,
)
from fmsave._layouts.fm26_26_3_2 import (
    STAFF as FM26_STAFF,
)
from fmsave._layouts.fm26_26_3_2 import (
    STAGE_RESULTS as FM26_STAGE_RESULTS,
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
    # Only blocks with a played match are kept, and two careers measured at the start of a
    # season keep 171 and 232 of them, under the FM26 floor of 200.
    table_blocks_minimum=(120, None),
    # The injury section of an early-season career is 21 KB to 50 KB, far below the FM26
    # threshold, so the checks would never run. Fragments stay below this one.
    injury_manager_minimum_applies_from_bytes=16 * 1024,
    # Two season-start saves measured 0.852 and 0.887, and every recent row that missed named
    # another team of the player's current club. Later states measured 0.948 to 0.966.
    injury_log_recent_team_matches=(0.75, None),
    # Early-season careers hold 13 to 33 players with a ban among 29,600 to 42,300, a share of
    # 0.0003 to 0.0011 that falls either side of the FM26 floor within days. The count judges
    # an empty search instead, and the ceiling stays.
    suspension_share_of_players=(None, 0.10),
    suspension_entries_minimum=(1, None),
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

STAFF = replace(
    FM26_STAFF,
    list_count_bytes=2,
    human_personality_floor=0,
    job_offset=16,
    offer_marker_offset=19,
    no_contract_selector_offset=16,
    no_contract_lead=b"\x05\x05",
)

TRAINING = replace(
    FM26_TRAINING,
    block_lead_byte=2,
    day_block_bytes=8,
    day_block_lead_byte=4,
    week_name_offset=62,
    week_record_fixed_bytes=80,
    header_entries_supported=False,
    mentoring_groups_supported=False,
    session_labels_supported=True,
)

# Typed rows and nonempty lists walk the whole section exactly on every save state measured,
# and the name table in a per-match entry matches the FM26 table record for record.
INJURY_MANAGER = FM26_INJURY_MANAGER
INJURY_TYPE_TABLE = FM26_INJURY_TYPE_TABLE

# A team's own tactic record and the game's preset library differ in the last signature byte.
# No second user variant is observed, so the alternate signature repeats the user signature
# and adds no search. Named routines are still unobserved and stay rejected.
_FM27_USER_TACTIC_SIGNATURE = bytes.fromhex("2244001b00000000")
TACTICS = replace(
    FM26_TACTICS,
    selection_end_marker=b"\x44\x00",
    user_signature=_FM27_USER_TACTIC_SIGNATURE,
    alternate_signature=_FM27_USER_TACTIC_SIGNATURE,
    preset_signature=bytes.fromhex("2244001b00000001"),
    slot_tag=bytes.fromhex("440002"),
    slot_constant=bytes.fromhex("000101"),
    unit_lead=bytes.fromhex("020202"),
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
# Populated histories use the FM26 record shape. They are read only while every player's
# declaration is located and the nonempty ones are exactly the lists decoded.
MATCH_RECORDS = replace(
    FM26_MATCH_RECORDS, cache_layout=MATCH_CACHE, declared_histories_required=True
)

# Keep stored boundary dates unchanged; this build can end a row 1 day before it starts.
# Kinds one club's sponsorship screen displayed a type against; 3 and 23 both showed Stadium.
# The balance word matched the finances screen's Overall Balance on two careers.
SPONSOR_CHAINS = replace(
    FM26_SPONSOR_CHAINS,
    minimum_row_days=-1,
    reject_invalid_lists=True,
    balance_offset=22,
    kind_names=(
        (1, "MAIN_KIT"),
        (3, "STADIUM"),
        (4, "GENERAL"),
        (8, "AWAY_KIT"),
        (9, "ADDITIONAL_KIT_SPONSOR"),
        (11, "BACK_OF_SHIRT"),
        (23, "STADIUM"),
    ),
)

# The calendar record is two bytes shorter: four fewer bytes before the season year, and two
# undecoded bytes after the last named field. Its locator and packet markers are 0x1F.
FIXTURE_CALENDAR = replace(
    FM26_FIXTURE_CALENDAR,
    record_bytes=66,
    marker_byte_value=0x1F,
    season_start_year_offset=22,
    match_record_id_offset=28,
    phase_offset=32,
    leg_offset=33,
    round_index_offset=34,
    r39_42_offset=35,
    match_rules_template_offset=39,
    r47_54_offset=43,
    played_offset=53,
    secondary_marker=0x1F,
    cache_primary_bytes=61,
    cache_primary_suffix_offset=43,
)
STAGE_RESULTS = FM26_STAGE_RESULTS
MATCH_SUMMARIES = FM26_MATCH_SUMMARIES
# Some cup group stages count a match in played without counting it as won, drawn or lost.
LEAGUE_TABLES = replace(FM26_LEAGUE_TABLES, results_may_fall_short_of_played=True)
# Twenty bytes separate the doubled promotion quad from the marker, and each round record
# carries six more bytes. Its interstitials are the ten bytes that open with four FF bytes; no
# tagged interstitial shape has been seen, and the inherited tag can never match one of them.
RULES_PREAMBLES = replace(
    FM26_RULES_PREAMBLES,
    marker=bytes.fromhex("ffff000001ffffff00"),
    promotion_quad_offset=-28,
    body_offset=9,
    round_record_bytes=21,
    moved_match_sentinel_offset=0,
    moved_match_tail_offset=0,
)

# The pair matched the finances screen's Scouting Budget on two careers. Each save measured
# holds two hits of the marker, and the second pair is zero on all of them.
HUMANS = replace(
    FM26_HUMANS,
    scouting_budget_marker=bytes.fromhex("01006c07 01006c07 40000002 0f2d0764"),
    scouting_date_offset=-4,
    scouting_budget_offset=16,
    scouting_remaining_offset=20,
    scouting_budget_maximum=100_000_000,
)

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
        LayoutEntry("unlisted_after_non_pl_hist_ls", None, BUILD, layout)
        for layout in (FIXTURE_CALENDAR, STAGE_RESULTS, LEAGUE_TABLES, RULES_PREAMBLES)
    ),
    LayoutEntry("game_db", 4000, BUILD, MATCH_SUMMARIES),
    *(
        LayoutEntry("game_db", 4000, BUILD, layout)
        for layout in (
            NAME_POOLS,
            CONTRACTS,
            STAGE_TABLE,
            SUSPENSIONS,
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
