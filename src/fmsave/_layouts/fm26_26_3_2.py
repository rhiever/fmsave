"""Layouts for FM26 build 26.3.2+2329565, the final FM26 update."""

from __future__ import annotations

import struct

from fmsave._layouts import (
    FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    FULL_SAVE_MINIMUM_INJURY_MANAGER_BYTES,
    FULL_SAVE_MINIMUM_SPAN_BYTES,
    AffiliateGroupLayout,
    ClubRecordLayout,
    ClubStatusLayout,
    CompetitionIdPairLayout,
    ContractLayout,
    FinanceChainLayout,
    FixtureCalendarLayout,
    GameInfoLayout,
    GateBounds,
    HumansLayout,
    InjuryManagerLayout,
    InjuryTypeTableLayout,
    JobCentreLayout,
    LayoutEntry,
    LeagueTableLayout,
    MatchRecordLayout,
    NamePoolLayout,
    PersonBlockLayout,
    PlayerRecordLayout,
    RulesPreambleLayout,
    SaveSummaryLayout,
    SponsorChainLayout,
    StadiumTableLayout,
    StaffLayout,
    StageResultLayout,
    StageTableLayout,
    SummaryStringsLayout,
    SuspensionLayout,
    TaggedStreamLayout,
    TeamListLayout,
    TransferWindowLayout,
)

BUILD = "26.3.2+2329565"
# The unnamed run of frames between `non_pl_hist_ls` and `humans`, which carries no schema
# number. `fmsave.readers._common.SPAN_REGION` is the name the readers use.
SPAN_REGION_NAME = "unlisted_after_non_pl_hist_ls"
# The per-match directory entries, which are not sections and carry no schema number.
# `fmsave.readers._common.MATCH_FILE_REGION` is the name the readers use.
MATCH_FILE_REGION_NAME = "match_file"

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

# Strings start right after the 8-byte section header; control characters end a candidate.
SUMMARY_STRINGS = SummaryStringsLayout(
    strings_start_offset=8,
    string_length_range=(2, 120),
    lowest_code_point=0x20,
)

HUMANS = HumansLayout(
    human_count_offset=8,
    first_selector_offset=10,
    person_uid_offset=4,
    person_uid_copy_offset=8,
)

# The injury-type name table, as it sits inside every per-match entry of a save. Its records
# are 568 bytes into the payload on almost every entry, but nothing reads that offset: the
# table is found by walking the longest chain of records the shape below accepts.
INJURY_TYPE_TABLE = InjuryTypeTableLayout(
    lead_byte=1,
    id_offset=1,
    length_offset=3,
    text_offset=7,
    trailer_bytes=5,
    length_range=(3, 64),
    text_byte_range=(0x20, 0x7E),
    flag_values=(0, 1),
    minimum_chain_entries=2,
    maximum_entries_tried=4,
    # Twice the tried limit, so four entries that are not per-match files at all still leave
    # four to try. Every save measured carries the magic on all of them, so nothing reaches it.
    maximum_entries_opened=8,
    payload_prefix=b"\x03\x01",
)

# The injury history the `injury_manager` section stores: four arrays, three lists and an
# eight-byte tail, back to back from offset 12, ending on the section's last byte. The two
# arrays of stride 14 hold date pairs no reader ships; array 2 carries one typed row per
# injured person and array 3 the log of past injuries.
INJURY_MANAGER = InjuryManagerLayout(
    arrays_offset=12,
    array_strides=(14, 14, 13, 15),
    typed_array_index=2,
    log_array_index=3,
    list_entry_bytes=(4, 4, 5),
    tail=bytes.fromhex("010000000000ffff"),
    lead_byte=1,
    date_offset=1,
    selector_offset=5,
    log_team_offset=9,
    log_cause_offset=13,
    log_severity_offset=14,
    typed_type_offset=9,
    typed_r11_offset=11,
    typed_r12_offset=12,
    typed_retention_days=7,
    recent_log_days=30,
)

# The groups of clubs the `feeder_man` section stores. Groups run from 2 to 9 members on every
# save measured; the cap is far wider so that only a count read from the wrong bytes trips it.
AFFILIATE_GROUPS = AffiliateGroupLayout(
    count_offset=12,
    groups_offset=16,
    group_size_range=(1, 64),
)

# The open vacancies the `job_centre` section stores, 25 bytes each with no trailer.
JOB_CENTRE = JobCentreLayout(
    count_offset=8,
    records_offset=12,
    record_bytes=25,
    tag=bytes.fromhex("060000"),
    team_id_offset=3,
    role_offset=7,
    advertised_offset=8,
    date_12_offset=12,
    reserved_u16_offset=16,
    competition_offset=18,
    no_competition=0xFFFF,
    u20_offset=20,
    league_position_offset=22,
    reserved_u8_offset=23,
    flag_offset=24,
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
    # At most 3 affiliated teams have been seen on one club; the cap leaves room for more.
    affiliate_count_range=(0, 8),
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
    confirmation_offset=-18,
    confirmation_zero_bytes=10,
    maximum_leading_misses=16,
)

PLAYER_RECORDS = PlayerRecordLayout(
    marker=bytes.fromhex("01006c07"),
    marker_offset=102,
    pindex_offset=-19,
    uid_offset=-15,
    uid_copy_offset=-11,
    home_reputation_offset=-6,
    current_reputation_offset=-4,
    world_reputation_offset=-2,
    current_ability_offset=0,
    current_ability_range=(1, 200),
    potential_ability_offset=2,
    potential_ability_range=(-10, 200),
    reputation_bucket_offset=8,
    reputation_bucket_range=(0, 200),
    team_id_offset=16,
    ratings_offset=24,
    ratings_count=15,
    rating_range=(1, 20),
    attributes_offset=39,
    attribute_count=54,
    attribute_range=(1, 100),
    left_foot_index=24,
    right_foot_index=25,
    transfer_value_offset=93,
    transfer_value_placeholder=300_000_000,
    club_join_date_offset=98,
    match_sharpness_offset=106,
    condition_offset=110,
    height_offset=121,
    decode_extent=122,
    position_codes=(
        "GK",
        "SW",
        "DL",
        "DC",
        "DR",
        "DM",
        "ML",
        "MC",
        "MR",
        "AML",
        "AMC",
        "AMR",
        "STC",
        "WBL",
        "WBR",
    ),
    attribute_field_order=(
        "crossing",
        "dribbling",
        "finishing",
        "heading",
        "long_shots",
        "marking",
        "off_the_ball",
        "passing",
        "penalty_taking",
        "tackling",
        "vision",
        "handling",
        "aerial_reach",
        "command_of_area",
        "communication",
        "kicking",
        "throwing",
        "anticipation",
        "decisions",
        "one_on_ones",
        "positioning",
        "reflexes",
        "first_touch",
        "technique",
        "flair",
        "corners",
        "teamwork",
        "work_rate",
        "long_throws",
        "eccentricity",
        "rushing_out",
        "punching",
        "acceleration",
        "free_kick_taking",
        "strength",
        "stamina",
        "pace",
        "jumping_reach",
        "leadership",
        "dirtiness",
        "balance",
        "bravery",
        "consistency",
        "aggression",
        "agility",
        "important_matches",
        "injury_proneness",
        "versatility",
        "natural_fitness",
        "determination",
        "composure",
        "concentration",
    ),
)

PERSON_BLOCKS = PersonBlockLayout(
    window_start_offset=100,
    personality_offset_from_birth=21,
    personality_count=8,
    personality_range=(1, 20),
    date_zero_bytes_offset_from_birth=14,
    date_zero_bytes_count=7,
    legal_name_length_min=2,
    legal_name_length_max=80,
    name_id_limit=2**23,
    first_name_id_offset_from_block_start=0,
    surname_id_offset_from_block_start=5,
    common_name_id_offset_from_block_start=10,
    legal_name_length_offset_from_block_start=15,
    legal_name_offset_from_block_start=19,
    trait_bits_offset_from_block_start=-8,
    nation_id_offset_from_birth=13,
    relation_present_offset_from_birth=37,
    relation_count_offset_from_birth=38,
    relation_entries_offset_from_birth=39,
    relation_entry_bytes=16,
    second_nation_pair=(8, 9),
    home_grown_nation_pair=(8, 70),
    home_grown_club_pair=(1, 72),
    relation_referenced_offset_in_entry=0,
    relation_kind_role_offset_in_entry=10,
    relation_qualifier_offset_in_entry=12,
    relation_sentinel_offset_in_entry=15,
    # 100 when the player holds the second nationality, 15 when the player is eligible for it.
    second_nation_qualifiers=(15, 100),
    relation_sentinel_value=0xFF,
)

CONTRACTS = ContractLayout(
    tag=bytes.fromhex("01006c07"),
    chain_window_start_offset=-30,
    chain_window_end_offset=-30,
    selector_offset=5,
    start_offset=-19,
    team_id_offset=9,
    wage_offset=17,
    tail_base_offset=66,
    tail_step_bytes=29,
    tail_max_event_count=200,
    tail_sentinel_byte_offset=3,
    tail_sentinel_byte_value=3,
    tail_sentinel_word_offset=4,
    tail_sentinel_word_value=4,
    tail_e2_offset=2,
    tail_e8_offset=8,
    tail_e12_offset=12,
    tail_e16_offset=16,
    tail_e20_offset=20,
    tail_e24_offset=24,
    tail_end_offset=28,
    tail_printed_start_offset=32,
    tail_squad_status_offset=36,
    tail_e37_offset=37,
    tail_e38_offset=38,
    tail_e39_offset=39,
    tail_event_count_offset=42,
    # The loan blocks seen sit at most a few steps back; the cap leaves room for far more.
    loan_block_max_event_count=60,
    clause_step_bytes=8,
    clause_max_count=23,
    clause_ff_offset=-16,
    clause_ff_count=8,
    clause_zero_offset=-8,
    clause_zero_count=3,
    clause_count_offset=-5,
    clause_entries_offset=-4,
    clause_entry_bytes=8,
    clause_value_offset=0,
    clause_parameter_offset=4,
    clause_kind_offset=6,
    clause_team_marker_id_bytes=4,
    clause_competition_count_bytes=1,
    clause_competition_item_bytes=31,
    clause_competition_item_prefix=bytes.fromhex("010001006c07"),
    # At most 3 competition items and 3 award items have been seen on one contract; both caps
    # leave room for far longer lists.
    clause_competition_max_count=32,
    clause_award_flag_bytes=1,
    clause_award_count_bytes=4,
    clause_award_item_bytes=15,
    clause_award_item_prefix=bytes.fromhex("0100"),
    clause_award_max_count=32,
    clause_trailer_bytes=2,
    head_gate_offset=-35,
    head_gate_value=5,
    head_type_offset=-33,
    head_money_a_offset=-32,
    head_money_b_offset=-28,
    head_money_c_offset=-24,
    fallback_start_from_record=110,
    fallback_end_margin=90,
    fallback_nonzero_offset=8,
    fallback_nonzero_length=8,
    fallback_end_date_offset=0,
    fallback_start_date_offset=4,
    fallback_gate_length=16,
)

# A monthly finance snapshot row is 49 bytes and the row count sits in the four bytes in front
# of the first row. Every club holding a chain has a record of at least 2,347 bytes on the saves
# measured, so searching only records of 1,500 bytes or more loses no club and skips most of
# them. The balance range and the weekly ceiling are far outside anything a club holds (the
# largest weekly wage budget measured is a small fraction of 20 million) and are there to reject
# look-alike bytes rather than to bound a real value.
FINANCE_CHAINS = FinanceChainLayout(
    row_bytes=49,
    tag=0x01,
    count_offset=-4,
    count_range=(3, 1_000),
    balance_range=(-400_000_000, 2_000_000_000),
    weekly_maximum=20_000_000,
    balance_offset=1,
    transfer_allocated_offset=5,
    transfer_remaining_offset=9,
    wage_budget_offset=13,
    wage_payroll_offset=17,
    income_excluding_transfers_offset=21,
    net_transfers_offset=25,
    wage_bill_offset=29,
    net_offset=33,
    expenditure_excluding_transfers_offset=37,
    total_income_offset=41,
    total_expenditure_offset=45,
    minimum_record_bytes=1_500,
    # The last row is the month before the save's clock month. Across two saves of one career
    # ten months apart the series agree row for row at that lag on all 1,740 overlapping rows of
    # 145 clubs, and at no other lag on a single row; the lag itself is supported indirectly,
    # because the months whose balance step differs from the month's net fall in the transfer
    # windows under this lag and in February and September under a lag of zero.
    month_lag=1,
)

# A sponsor row is 25 bytes and its run is counted by the single byte in front of it. Years from
# 1991 are what the corpus holds; the ceiling on a value is far above any contract measured.
SPONSOR_CHAINS = SponsorChainLayout(
    row_bytes=25,
    tag=0x02,
    count_offset=-1,
    type_offset=1,
    start_offset=2,
    end_offset=6,
    flag10_offset=10,
    flag10_maximum=1,
    total_offset=11,
    u15_offset=15,
    b17_offset=17,
    enum18_offset=18,
    b19_offset=19,
    annual_offset=21,
    year_range=(1991, 2099),
    value_maximum=2_000_000_000,
)

# A suspension entry is 20 bytes long; its signature bytes pin 5 of them.
SUSPENSIONS = SuspensionLayout(
    signature=((4, 0xFF), (5, 0xFF), (13, 0x05), (15, 0xFF), (18, 0xFF)),
    unknown_e7_offset=7,
    issued_date_offset=9,
    unknown_e14_offset=14,
    competition_id_offset=16,
    owner_back_offset=30,
    competition_id_exclusive_range=(0, 60_000),
)

# A per-match player record is 15 bytes when the save keeps no performance body for the match
# and 43 bytes when it does. The search is held to matches dated from four years before the
# save's clock to one after, which is where the records a save still holds fall; how many that
# window yields moves with the career, so no check bounds the count.
MATCH_RECORDS = MatchRecordLayout(
    lead_byte_offset=0,
    lead_byte_value=0x01,
    date_offset=1,
    opponent_team_id_offset=5,
    competition_id_offset=9,
    tag_offset=13,
    body_flag_offset=14,
    position_mask_offset=17,
    role_code_offset=23,
    goals_offset=24,
    assists_offset=28,
    left_at_offset=36,
    minutes_offset=39,
    rating_offset=40,
    passes_attempted_offset=41,
    passes_completed_offset=42,
    header_bytes=15,
    record_bytes=43,
    owner_back_offset=30,
    team_id_range=(1, 2_999_999),
    competition_id_range=(1, 65_535),
    years_before_clock=4,
    years_after_clock=1,
    maximum_minutes=130,
    maximum_rating=100,
    maximum_goals=20,
    rating_scale=10,
    # The mask carries exactly one bit on all but a handful of the 47,000 records measured
    # across three saves: none at all carries two, and at most four per save carry none.
    # Fourteen of its sixteen bits are in use, so it covers a full set of positions, and one of
    # them is named.
    #
    # Bit 0 is the goalkeeper. Every record of a player the game's own screen labels "GK"
    # carries it, and all but one of the records carrying it belongs to a player the save rates
    # a natural goalkeeper: 958 of 958, 1,177 of 1,178 and 912 of 912 records on the three
    # saves, so one record out of 3,048 does not.
    #
    # No other bit is named, for want of a label that separates one bit from its neighbours.
    # The players whose displayed label the corpus can reach play several positions each, so
    # the label fits several bits at once: one such label lands on three bits together and says
    # they are the three defensive ones without saying which is which. The evidence left is how
    # often a player with a single natural position is picked in a given position, and it tops
    # out at 0.77 to 0.86 for those bits, because where a player is picked is not what he is
    # rated at. A name resting on that would be a guess wearing a label, and it would be
    # invisibly wrong; a raw mask is plainly incomplete instead, and groups records just as
    # well. The in-game check that shows one player's last five matches would settle the lot.
    position_bits=((0, "GOALKEEPER"),),
)

# The fixture calendar record is 68 bytes from the home team id, with the locator byte, the
# stage id and the stadium ordinal in the 12 bytes before it.
FIXTURE_CALENDAR = FixtureCalendarLayout(
    record_bytes=68,
    marker_byte_offset=-12,
    marker_byte_value=0x1C,
    sentinel_offsets=((4, 0xFF), (11, 0xFF)),
    stage_id_offset=-11,
    stadium_ordinal_offset=-7,
    home_team_id_offset=0,
    away_team_id_offset=7,
    kick_off_date_offset=13,
    date2_offset=17,
    season_start_year_offset=26,
    match_record_id_offset=32,
    phase_offset=36,
    leg_offset=37,
    round_index_offset=38,
    r39_42_offset=39,
    match_rules_template_offset=43,
    match_rules_template_bytes=3,
    r47_54_offset=47,
    played_offset=55,
    team_id_range=(1, 2_999_999),
    years_before_clock=7,
    years_after_clock=8,
    round_index_none_value=255,
    kick_off_slot_offset=23,
    kick_off_slot_minutes=15,
    cluster_gap_bytes=1_048_576,
    # A club plays every other club in its division at home once, so even a tiny league gives
    # far more than four home matches a season; four is low enough to still decide a cup-only
    # side's usual ground, and high enough that one rearranged tie cannot outvote it.
    neutral_venue_minimum_home_fixtures=4,
)

# A stage-keyed result record is 27 bytes carrying one match's score. The locator anchors on the
# two-byte sentinel rather than the lead byte, which gives the search a far more selective
# literal; the lead byte and the zero byte are checked after it.
#
# The zero byte at +15 holds on 100% of the records accepted on all three saves measured, so
# requiring it costs nothing and turns away look-alikes. That is the whole of its justification:
# it is a locator constraint, not a finding about what the byte holds.
#
# Acceptance is weak on its own and is not the evidence for this record. Of 671,258 candidates on
# one save, 477,702 are turned away on the date alone and only 546 by the stage table, the team
# range and the goal ceiling together. What carries the shape is the join: 43,000 to 54,000 of
# these records match a fixture the calendar found in another region under another locator, while
# the same records joined with the two sides swapped, or with the date moved one day, match
# nothing at all on any save.
STAGE_RESULTS = StageResultLayout(
    record_bytes=27,
    lead_byte_offset=0,
    lead_byte_value=0x01,
    date_offset=1,
    stage_id_offset=5,
    sentinel_offset=9,
    sentinel_value=1,
    zero_byte_offset=15,
    home_team_id_offset=11,
    away_team_id_offset=16,
    home_goals_offset=20,
    away_goals_offset=21,
    r22_offset=22,
    # The team ids share the fixture calendar's range, since they name the same teams.
    team_id_range=(1, 2_999_999),
    # Far above any score a match has ever finished on, so this turns away noise rather than
    # any real result.
    goals_maximum=40,
    regions=(
        "tc_record_man",
        "tc_extended_club_records_history_dt",
        "news",
        "extended_comp_records_dt",
    ),
)

# A league-table block opens with five aggregate rows, each keyed FF FF FF FF.
LEAGUE_TABLES = LeagueTableLayout(
    row_bytes=17,
    aggregate_count=5,
    team_id_offset=-23,
    head_bytes_offset=-19,
    head_bytes_count=19,
    rounds_per_venue_offset=85,
    matches_offset=87,
    rounds_per_venue_range=(1, 40),
    key_offset=0,
    played_offset=4,
    played_copy_offset=5,
    won_offset=6,
    drawn_offset=7,
    lost_offset=8,
    zero_offset=9,
    goals_for_offset=10,
    goals_against_offset=12,
    points_offset=14,
    flag_offset=16,
    unplayed_key=0xFFFFFFFF,
    team_id_range=(1, 2_999_999),
    # The first head byte counts the block's place in its own table, 0 to n-1, and starts
    # again at the next table. Splitting there rather than on the distance between blocks
    # leaves 0.12% / 0.26% / 0.18% of groups holding one club twice, against 15.2% / 16.8% /
    # 16.8% under a distance rule, and recovers the 20-club division the save's own manager
    # plays in, which the distance rule ran together with its neighbour into 38 rows.
    stored_index_head_byte=0,
    division_club_range=(18, 26),
    # The parity is not settled, so `venue` is None on every row. The even slots look like the
    # home ones, but only on a restricted population: played even-slot rows equal the HOME
    # aggregate's played count on 99.68% / 99.94% / 99.61% of the blocks whose played match rows
    # account for their own total aggregate, against 66.6% / 38.1% / 45.0% for odd slots -- and
    # that population is 85.1% / 88.3% / 85.5% of blocks. Over every deduplicated block the
    # even-slot share is 85.8% / 89.8% / 87.1%, well short of the 99% this project requires
    # before it names a meaning, and no check here fails if the parity is wrong, so a mistake
    # would mislabel every venue silently. It stays None until a screen reads it back.
    home_slot_parity=None,
)

# The round-record offsets and the moved-match rule were measured on the corpus: the date
# and the match count agree on about 96% of blocks, and a stride that does not step over
# moved matches falls to about 65%.
RULES_PREAMBLES = RulesPreambleLayout(
    marker=bytes.fromhex("03000001000000ffff000001ffffff"),
    promotion_quad_offset=-8,
    promotion_quad_bytes=4,
    body_offset=16,
    tie_break_count_max=16,
    prize_count_max=64,
    round_count_max=80,
    round_record_bytes=15,
    round_anchor_search_bytes=8,
    round_kind_offset=0,
    round_date_offset=1,
    round_b5_offset=5,
    round_number_offset=6,
    round_no_number_value=255,
    round_match_count_offset=9,
    round_match_count_max=64,
    moved_match_bytes=10,
    moved_match_sentinel_offset=4,
    moved_match_sentinel_value=0xFF,
    moved_match_tail_offset=6,
    moved_match_tail=b"\xff\xff\xff\xff",
    moved_match_max_per_round=64,
)

# A stadium row is 181 bytes when it carries no inline name, and 185 plus the name when it
# does. The table head sits at 11.9% to 14.4% of `game_db` across the saves measured, which is
# why it is found by its own first rows rather than by a fraction of the section: twelve rows
# each storing their own ordinal, with the uid doubled and a zero byte, accepted one candidate
# per save and turned away the 41 to 52 other places the pattern alone matched.
STADIUM_TABLE = StadiumTableLayout(
    row_bytes=181,
    ordinal_offset=0,
    uid_offset=4,
    uid_copy_offset=8,
    zero_byte_offset=12,
    all_seater_offset=13,
    u17_offset=17,
    expansion_offset=21,
    u25_offset=25,
    owner_offset=29,
    b33_offset=33,
    capacity_offset=34,
    pitch_length_offset=38,
    pitch_width_offset=40,
    built_offset=50,
    rebuilt_offset=54,
    date_58_offset=58,
    pitch_min_length_offset=67,
    pitch_min_width_offset=69,
    pitch_max_length_offset=71,
    pitch_max_width_offset=73,
    flags_offset=156,
    inline_name_flag=0x10,
    name_length_offset=158,
    name_offset=162,
    named_row_extra_bytes=4,
    # Names run 6 to 43 bytes across the saves measured. The range is wide because it is only
    # a sanity bound on a length the row itself stores: a length outside it ends the walk.
    name_length_range=(1, 256),
    locator_rows=12,
    # Every row but the template the table ends with holds a pitch length in this range, and
    # every one of them is longer than it is wide.
    pitch_length_range=(900, 1300),
    home_ground_minimum_fixtures=4,
    # The template row every table ends with holds this all-seater capacity on all three saves
    # measured, and no real ground holds more than 293,376, so nothing else is mistaken for it.
    template_all_seater_capacity=16_777_216,
    table_terminator=3,
)

# A stage row is 33 bytes. The table sits in the last 0.3% of `game_db` on every save measured,
# so the last 2 MB is a wide search window; 200 rows is far longer than any run of look-alike
# bytes seen before it.
STAGE_TABLE = StageTableLayout(
    row_bytes=33,
    previous_stage_id_offset=0,
    stage_id_offset=4,
    stage_id_copy_offset=8,
    zero_byte_offset=12,
    competition_id_offset=13,
    group_id_offset=17,
    round_offset=21,
    unknown_s25_offset=25,
    unknown_s29_offset=29,
    stage_id_exclusive_range=(0, 200_000),
    # The largest competition id seen is 16,777,216 on every save, far above the roughly 2,600
    # competitions a save holds; this limit rejects it without touching a real competition.
    competition_id_limit=1_000_000,
    search_bytes=2_000_000,
    chain_rows=200,
    resynchronisation_bytes=4_096,
)

# The id-pair marker is 16 `FF` bytes and a `01`, which hits about ten times as often as a
# record occurs (roughly 72,000 hits against 7,400 records on every save measured), so the
# structural checks and the constant bytes are what recognise a record, not the marker. Either
# filter is very nearly sufficient alone: the constants by themselves reject about 64,500 of
# those marker hits and leave the same 7,400 records.
#
# `constant_bytes` holds every offset whose byte takes one value on at least 99% of records on
# all three saves measured, save two that are deliberately left out because they reject records
# the save really does pair: -3 costs 16 competitions and one of the pairs an independent
# source confirms, and +29 rejects two entities that deviate at that one offset alone. Of the
# 17 kept, six cost a single record per save, and it is the same record that fails all six:
# bytes that break six independent constants at once are far likelier a coincidence that
# survived the marker than a competition, and a database id read from them would name the
# wrong competition rather than leave it unnamed.
COMPETITION_ID_PAIRS = CompetitionIdPairLayout(
    marker=b"\xff" * 16 + b"\x01",
    record_offset_from_marker=30,
    entity_id_offset=0,
    database_id_offset=4,
    database_id_copy_offset=8,
    # The entity id shares the stage id space, so it shares its bound.
    entity_id_range=(1, 199_999),
    database_id_range=(1, 2**31 - 1),
    constant_bytes=(
        (-8, 7),
        (-6, 0),
        (-4, 7),
        (-1, 255),
        (12, 0),
        (13, 0),
        (14, 0),
        (15, 1),
        (22, 0),
        (23, 0),
        (24, 0),
        (25, 0),
        (26, 1),
        (32, 2),
        (40, 3),
        (55, 6),
        (60, 7),
    ),
)

# The tag is stored byte-reversed, so the bytes `csed` are the tag `desc`. Confirmed by walking
# every marker of both saves under each direction: read reversed the stream yields the tags the
# format names (`stdt`, `endt`, `dyom`, `mont`, `year`, `wnCT`) and read as stored it yields
# none of them.
TAGGED_STREAM = TaggedStreamLayout(
    tag_bytes=4,
    separator_value=0x01,
    u8_types=(0x11,),
    u16_types=(0x12,),
    u32_types=(0x01, 0x02, 0x03, 0x0B, 0x0F),
    string_type=0x1A,
    list_type=0x0A,
    nil_type=0x00,
    max_string_bytes=4096,
)

# A window record opens with its `stdt` sub-list, so the marker is that list's stored bytes.
# Both saves measured agree exactly: 1,766 start-date sub-lists, of which 54 also carry a
# closing time and decode into a window, and none of those 54 is incomplete. The 54 windows are
# identical between the two, which is what makes them database content rather than career
# state; both saves come from one installed database, so these counts rest on a single database
# rather than on two independent ones, and the bounds below are loose for that reason.
#
# The longest record measured is 146 bytes and 16 tagged values, so the scan window is a little
# over 1.7 times the longest seen. The decoded count is identical at 160, 256, 512 and 1,024
# bytes, so nothing here depends on where the window is drawn.
TRANSFER_WINDOWS = TransferWindowLayout(
    marker=b"tdts\x01\x0a",
    start_tag="stdt",
    end_tag="endt",
    day_tag="dyom",
    month_tag="mont",
    year_tag="year",
    close_time_tag="wnCT",
    window_type_tag="wnty",
    window_scan_bytes=256,
    day_range=(1, 31),
    month_range=(1, 12),
    # 2000 is the season's own start year and 2001 the calendar year after it. The upper bound
    # leaves room for a window the save dates several seasons out.
    year_range=(2000, 2016),
    season_year_base=2000,
)

# Bounds that depend on career stage (join dates, contract chains, bans) are kept wide, since a
# failed check on the player pass stops players, contracts and suspensions together.
# A club's three staff lists and one staff person's object. The value range on a list id is a
# corruption cap far above the largest person id any save measured holds: its job is to turn
# away a count read from the wrong bytes, not to bound a real id. The 14 codes are every value
# the eight bytes after the role-like byte take on 99.95% of staff objects. The search for a
# person's header behind his own contract record is four times the largest distance measured
# (8,161 bytes on one save; 1,894 on the other two), and the two name-block windows are wider
# than the 1,534 bytes the furthest block measured sits from its contract tag.
STAFF = StaffLayout(
    kind_offset=12,
    staff_kind=1,
    human_kind=9,
    uid_offset=4,
    uid_copy_offset=8,
    entry_count_offset=13,
    entry_bytes=7,
    ability_base_offset=21,
    current_ability_offset=0,
    potential_ability_offset=2,
    ability_range=(1, 200),
    r4_offset=4,
    codes_offset=5,
    code_count=8,
    code_set=frozenset({3, 4, 7, 22, 27, 28, 29, 30, 32, 33, 35, 62, 63, 64}),
    sentinel_offset=13,
    sentinel_value=12,
    preferences_offset=14,
    preference_count=26,
    preference_range=(1, 20),
    # The 14 slots two exact editor readings pinned; every other slot ships as a raw number.
    named_preference_slots=(
        ("attacking", 0),
        ("business", 1),
        ("directness", 3),
        ("interference", 6),
        ("patience", 9),
        ("trigger_press", 10),
        ("resources", 11),
        ("buying_players", 14),
        ("mind_games", 15),
        ("flexibility", 21),
        ("hardness_of_training", 22),
        ("squad_rotation", 23),
        ("tempo", 24),
        ("width", 25),
    ),
    unnamed_preference_slots=(2, 4, 5, 7, 8, 12, 13, 16, 17, 18, 19, 20),
    # Slot 13 holds a 0..100 number rather than a 1..20 one, so it is the one slot left out.
    range_checked_preference_slots=tuple(slot for slot in range(26) if slot != 13),
    block_40_offset=40,
    block_40_count=26,
    block_40_range=(1, 100),
    list_count=3,
    list_value_range=(1, 1_000_000),
    discovery_selector_maximum=0x06FFFF,
    contract_header_search_bytes=32_768,
    person_block_offset_after_tag=60,
    person_block_search_bytes=4_096,
    list_only_block_search_bytes=20_000,
)

GATE_BOUNDS = GateBounds(
    minimum_applies_from_bytes=FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    span_minimum_applies_from_bytes=FULL_SAVE_MINIMUM_SPAN_BYTES,
    height_range_cm=(150, 210),
    age_range_years=(14, 45),
    home_reputation_window=1_000,
    condition_sharpness_maximum=10_000,
    natural_goalkeeper_rating=18,
    goalkeeper_block_low_maximum=30,
    players_minimum=(5_000, None),
    person_blocks=(0.99, None),
    names_resolved=(0.995, None),
    relation_sentinel=(0.999, None),
    second_nation_qualifier=(0.995, None),
    # Reading the attribute bytes one position late moves this share below the bound, and one
    # position early moves it above, so the bound stays narrow.
    handling_above_finishing=(0.20, 0.30),
    # Handling and throwing are the first and last of six adjacent goalkeeping attributes, which
    # outfield players rate low. Reading the attribute bytes one position early or late puts an
    # outfield attribute in one of the two, so this share falls far below the bound.
    outfield_goalkeeper_block_low=(0.90, None),
    with_natural_position=(0.97, None),
    height_in_range=(0.999, None),
    height_median=(170, 190),
    age_median=(20, 30),
    aged_in_range=(0.995, None),
    condition_sharpness_in_range=(0.999, None),
    join_date_valid=(0.05, 0.95),
    world_not_above_current=(0.95, None),
    home_near_current=(0.95, None),
    team_resolved=(0.98, None),
    home_grown_club_refs_resolved=(0.98, None),
    players_with_chain=(0.70, None),
    no_contract_in_effect=(None, 0.05),
    date_marked_chain_records=(None, 0.05),
    tails_parsed=(0.70, None),
    tails_without_clause_table=(None, 0.001),
    clause_terminator=(0.999, None),
    contract_head=(0.65, None),
    past_dated_tail_ends=(None, 0.05),
    chain_teams_resolved=(0.98, None),
    clubs_minimum=(5_000, None),
    team_lists_found=(0.999, None),
    status_normal=(0.98, None),
    status_confirmation=(0.95, None),
    affiliate_lists_found=(0.005, None),
    affiliate_teams_linked=(0.99, None),
    # Nearly every club carries a readable reputation, and their median sits around a
    # thousand. Reading the reputation one byte out inside the status record leaves fewer
    # than a sixth of clubs with a readable one and lifts the median of those above three
    # thousand, so either bound catches that shift on its own.
    reputation_found=(0.90, None),
    reputation_median=(200, 3_000),
    # About one player in two hundred holds an unserved ban on the saves measured. The floor
    # sits five times below that, so a search that finds no entry at all fails here instead of
    # reporting a save whose players are never banned.
    suspension_share_of_players=(0.001, 0.10),
    issued_after_clock=(None, 0.01),
    # Around 8,000 rows and no gaps at all on every save measured; both bounds leave room for a
    # much shorter table and for a save whose table needs resynchronising a few times.
    stage_rows_minimum=(1_000, None),
    stage_walk_gaps=(None, 8),
    stage_ids_ascending=(0.99, None),
    stage_rows_with_competition=(0.90, None),
    # The last word is the missing value on about 98.4% of rows and carries a small number on
    # the rest, so this is a shape check rather than a sentinel.
    stage_trailing_sentinel=(0.95, None),
    stage_table_tail_bytes=(None, 2 * 1024 * 1024),
    competitions_minimum=(50, None),
    # The id-pair records name 91.47% to 91.52% of the stage table's competitions across two
    # careers and a live save, and no save leaves a single competition in conflict. The share
    # is a property of the save's own records, so the bound leaves a career that pairs fewer of
    # them well clear; it is still close enough to catch a constant that decayed from holding
    # on 99.9% of records to holding on 90%, which would drop the share to about 0.82.
    competition_database_ids_mapped=(0.85, None),
    competition_database_id_conflicts=(None, 0.001),
    # A name arrives only through a database id, so the named competitions can never be more
    # than the ones that have one. Without a name map the share is 0.0 on every save, and with
    # one it is however much of the save the reader's map covers, so only the ceiling can be
    # bounded. Passing it means a name reached a competition the save gives no database id,
    # such as one whose database id another competition also claims, which would put a
    # different competition's name on it.
    competition_names_within_database_ids=(None, 1.0),
    # Around 99,000 to 137,000 records in the calendar on every save measured, holding 98.7%
    # to 99.3% of the fixture records in the span. The floor sits far below the smallest, so a
    # young career whose calendar is a fraction of these clears it, while a locator that broke
    # and now finds a handful of look-alikes does not.
    fixtures_minimum=(5_000, None),
    fixture_cluster_share=(0.90, None),
    # Every save measured leaves 998 to 1,308 fixture records outside the calendar, at least
    # 150 of which are a fixed block of template matches dated years off the clock that no
    # calendar keeps. Something is always separated out, so a run that swallows the whole span
    # means the gap above stopped splitting anything. The share alone cannot say so: a reader
    # that kept every stray copy scores a perfect 1.0 on it and passes. The floor sits an
    # order of magnitude below the smallest count measured, so a career carrying far fewer
    # copies still clears it.
    fixture_strays_minimum=(100, None),
    # Every stage the calendar names is in the stage table on every save measured: the share
    # is 1.0 over the strays as much as the kept records. That is what a dense, gapless id
    # space gives, the table running from 1 to its row count and covering the whole range the
    # calendar uses, so this is an interval test and not evidence that the join behind it is
    # right. It is kept for the one thing it does catch: a calendar read one field out points
    # at stage ids that are noise, which drops the share to near zero.
    fixture_stage_resolved=(0.95, None),
    # 92.43%, 93.87% and 92.68% of the two team ids per record are listed by a club across the
    # three saves measured: a calendar also holds matches between sides no club record covers,
    # such as teams of nations the career never loaded. The bound is the lowest of the three
    # less 0.05, floored to two decimals, so a career carrying more of those stays well clear
    # while a team id read from the wrong offset, which resolves almost nothing, still fails.
    fixture_teams_resolved=(0.87, None),
    # 0.99937 / 0.99953 / 0.99954 of the kept records that store a ground name one the stadium
    # table holds; the rest store the value 1, and no ground has ordinal 0. The floor sits
    # deliberately above 0.99429 / 0.99502 / 0.99445, which is what the same join scores
    # against a table that lost its 220 named rows: at 0.99 that control would pass and this
    # check could not fail. It applies only when some record stores a ground at all.
    fixture_stadiums_resolved=(0.998, None),
    # 44,351 / 55,414 / 42,608 records accepted on the three saves measured, counted under the
    # rule this reader applies: inside the calendar's own dates. A wider window accepts several
    # times that, so a count quoted here has to say which window produced it. The floor sits
    # more than four hundred times below the smallest of these, which leaves a young career
    # holding a fraction of them well clear while still failing a locator that has stopped
    # finding records at all.
    result_records_minimum=(100, None),
    # 0.9707 / 0.9717 / 0.9689 of accepted records join a fixture. This is the gate that says
    # the record is still being read correctly, because the calendar it joins is found by
    # another locator in another region: the same records joined with the sides swapped, or
    # with the date moved one day, joined 0 times on every save. The remaining 3% are in range
    # and still do not join, so the floor leaves room for a career carrying more of them.
    results_joined=(0.90, None),
    # 0.000023 / 0.000056 / 0.000121 of joined records name a fixture the calendar does not mark
    # played, which is 1, 3 and 5 records. A ceiling nearly two orders of magnitude above the
    # worst of those still fails a join that has started attaching scores to matches not yet
    # played.
    results_for_unplayed=(None, 0.01),
    # 54 windows on both saves measured. The floor sits over five times below that, which
    # leaves a database carrying far fewer windows well clear while still failing a decode that
    # finds none. Both saves come from one installed database, so this is a looser bound than
    # its margin suggests.
    transfer_windows_minimum=(10, None),
    # Every record that carried a closing time decoded both date groups cleanly on both saves,
    # so the share is 1.0 there. A date decode that moved would push records out of the count
    # and into `incomplete`; one that found nothing at all leaves no rate at all, which fails
    # the check rather than skipping it.
    transfer_window_dates=(0.90, None),
    # 4,817 / 3,846 / 5,073 blocks survive deduplication on the three saves measured, and
    # 4,385 / 3,385 / 4,108 are dropped as repeats of one already kept. Both floors sit an
    # order of magnitude below the smallest of those, so a young career holding a handful of
    # tables still clears them. The duplicate floor is the one that fails when the
    # deduplication stops running: the copies are sound blocks that every other check accepts,
    # and keeping them puts one club in a table several times over.
    table_blocks_minimum=(200, None),
    table_block_duplicates_minimum=(100, None),
    # 0.99959 / 0.99974 / 0.99961 of the blocks kept carry a team id inside the layout's range.
    table_block_team_in_range=(0.99, None),
    # 0.9988 / 1.0000 / 1.0000 of tables are voted a competition on the three saves measured,
    # which overshoots spec 6.2's "about 85%". Read that headline beside the shape of the
    # tables: 30.3% / 41.9% / 43.4% of them hold a single block, and a one-block table meets the
    # vote's "at least half the members" rule on a majority of one, so it resolves trivially.
    # Over the tables of two blocks or more the share is 0.9983 / 1.0000 / 1.0000, which is the
    # figure that says the vote is sound rather than merely permissive. The floor stays well
    # below both, because the share rests on how much of the calendar a career has played
    # rather than on the layout.
    table_groups_resolved=(0.70, None),
    # 60 / 50 / 58 groups are shaped like a division whose clubs all play each other twice.
    # This is what fails when the grouping stops telling one table from the next: the blocks
    # then arrive in runs of dozens, and no run has a division's shape.
    double_round_robin_divisions=(5, None),
    # 672 and 521 rules preamble blocks on the two saves measured. The floor sits more than an
    # order of magnitude below the smaller of those, which leaves a career carrying far fewer
    # divisions well clear while still failing a marker that finds nothing at all.
    rules_markers_minimum=(20, None),
    # 0.8438 and 0.8580 of blocks parse in the strict sense this share counts: the promotion
    # quad written twice identically AND the tie-break list, the prize list and every round
    # record decoded. Counting only the lists and the rounds, as the format research did, gives
    # 0.9345 and 0.9309 instead, so this floor must not be read against that figure. The lower
    # of the two observed values clears the floor by 22% of the bound's width, which is thin:
    # a third save measured under the strict definition may warrant lowering it.
    rules_fully_parsed=(0.80, None),
    # Every per-match record the search accepts carries a competition id the stage table names
    # on two of the three saves measured and 0.9988 of them on the third, and every record with
    # a body has minutes and a rating inside the layout's bounds on all three. The floors sit
    # far below those, because the shares rest on how much of a career the save still holds
    # records for rather than on the layout; what they catch is a record read from the wrong
    # offset, whose competition id then falls outside the stage table and whose minutes and
    # rating fall anywhere at all. Nothing bounds the count: the search is held to a window of
    # years around the save's clock, so the number of records moves with that window.
    per_match_competition_in_stage_space=(0.95, None),
    per_match_minutes_in_range=(0.99, None),
    per_match_rating_in_range=(0.99, None),
    # Every save measured decodes 93 records of the name table, in every per-match entry read,
    # so this floor is never near a healthy save. Reading the type id one byte late decodes 4
    # records before the chain breaks and reading the lead byte four bytes late decodes none at
    # all, so either misalignment fails it. The floor stays loose because the table is database
    # content: an installed database with fewer injuries legitimately carries fewer records.
    injury_type_entries_minimum=(50, None),
    injury_manager_minimum_applies_from_bytes=FULL_SAVE_MINIMUM_INJURY_MANAGER_BYTES,
    # The three saves measured hold 128,866 / 91,474 / 138,330 log rows in a section of 1.4 to
    # 2.3 MB, so the floor is an order of magnitude below the smallest and cannot trouble a
    # career of any length that fills a section this size.
    injury_log_minimum=(10_000, None),
    # Every log row on every save carries the lead byte and a date that decodes and is on or
    # before the in-game date. Read one byte late the first falls to 0.0047 / 0.0060 / 0.0060
    # and the second to zero on all three, and four bytes late both are zero.
    injury_log_lead_byte=(0.999, None),
    injury_log_dates=(0.999, None),
    # The log is stored oldest first: every one of the 128,865 / 91,473 / 138,329 steps between
    # adjacent dated rows reaches a date no earlier than the one before it. Read one byte late
    # only a few hundred rows still carry a date and 0.81 / 0.75 / 0.82 of the steps between
    # them ascend, which is what this floor separates.
    injury_log_ascending=(0.99, None),
    # 0.9983 / 0.9976 / 0.9984 of log rows name a team some club lists; the rest name teams the
    # save no longer keeps. Read one byte late the share falls to 0.196 / 0.180 / 0.207 and
    # four bytes late to 0.0027 / 0.0024 / 0.0023.
    injury_log_teams_resolved=(0.95, None),
    # Of the log rows from the last month whose player resolves and has a team, 0.9868 / 0.9952
    # / 0.9923 store exactly that team. This is the one check that joins the section to the
    # player records, and putting a random player in place of the stored one scores 0.0 /
    # 0.00027 / 0.00016. The floor leaves room for the transfers a month of a career brings.
    injury_log_recent_team_matches=(0.90, None),
    # Every typed row carries the lead byte, and 0.9883 / 0.9884 / 0.9929 carry a date that is
    # inside the window the game keeps a typed row for; the rest store the null date word. Read
    # one byte late the lead byte falls to 0.0117 / 0.0116 / 0.0071 and the dated-and-in-window
    # share to 0.0058 / 0.0018 / 0.0040, and four bytes late both are zero. The share is taken
    # over every typed row on purpose: over the dated rows alone it is 1.0 read one byte late
    # too, because the few dates that still decode all land inside the window.
    injury_typed_lead_byte=(0.999, None),
    injury_typed_retention=(0.95, None),
    # 0.9157 / 0.9445 / 0.9387 of typed rows carry an injury type the name table holds; the
    # rest carry one of a dozen codes the table has no entry for at all, so the floor sits well
    # below them. Read one or four bytes late the share is zero on all three saves.
    injury_typed_types_resolved=(0.80, None),
    # Every one of the 11,399 / 3,081 / 3,460 finance rows on the three saves measured has a net
    # equal to its total income less its total expenditure, and an expenditure excluding
    # transfers between zero and its total. Both are what fail when the row is read from the
    # wrong offset: one field late leaves 0.11% / 0.26% / 0.12% of rows on the net identity and
    # 0.9% on the split, and one field early leaves 0.0.
    finance_net_identity=(0.99, None),
    finance_expenditure_split=(0.99, None),
    # 91.4% / 92.5% / 97.6% of consecutive row pairs have the later balance equal to the earlier
    # one plus the later month's net; the rest cluster in the transfer-window months. The floor
    # is below the lowest of those by 57% of the bound's width. Reading the rows one field out
    # leaves at most 0.3% here, except one field early, which leaves 82.5% / 78.6% / 91.7% and
    # is what the net identity catches instead.
    finance_balance_continuity=(0.80, None),
    # No club on any save measured holds a second snapshot chain, and a second one would mean
    # the locator is accepting bytes inside or behind the chain it already found.
    finance_clubs_with_two_chains=(None, 0),
    # 335 / 57 / 172 clubs keep a series: those of the one or two league nations the save
    # tracks, not every club, and which nations those are changes during a career. So there is
    # no count to bound from below beyond one, and only where a managed club exists, whose club
    # held a series on every save measured.
    finance_series_minimum=(1, None),
    # Every club with a series has a sponsor run on all three saves. The floor leaves room for a
    # career where a few clubs hold none while still failing a sponsor search that has moved,
    # which finds nothing at all.
    finance_clubs_with_sponsors=(0.95, None),
    # 419 of 426, 417 of 424 and 419 of 426 group members are club indexes a club record
    # claims; the seven that are not fall in gaps of the index. Reading the index one higher
    # drops the share to 0.859, 0.870 and 0.859, below the 0.91 a random index of this range
    # would hit by chance, so the floor sits between the two.
    affiliate_members_resolved=(0.95, None),
    # 134, 44 and 122 records on the saves measured. The threshold is not a bound on the feed's
    # size: it is how small a feed the shares below stop being judged on, because a short feed
    # is a fact about a quiet job market and the smallest feed measured holds 44.
    job_vacancy_minimum_applies_from_records=20,
    # Every record of every save carries the tag. A record start shifted one byte either way,
    # or four bytes back, carries it on none; shifted four bytes on, on 0.015, 0.070 and 0.008.
    job_vacancy_tag=(1.0, None),
    # 1.0, 1.0 and 0.9918 of records have an advertised date on or before the in-game date and
    # a second date on or after it. Every shift measured drops it to zero, since neither date
    # decodes at all from the wrong offset.
    job_vacancy_dates_ordered=(0.95, None),
    # The feed is stored in ascending advertised date, so every step forward on every save
    # measured reaches a date no earlier than the one before. Shifted four bytes on, 0.849,
    # 0.976 and 0.850 of steps do; shifted the other three ways no date decodes, which leaves
    # the share without a denominator and fails on that.
    job_vacancy_advertised_ascending=(0.99, None),
    # Both reserved fields are zero on every record of every save measured, and on at most
    # 0.008 of records under any of the four shifts.
    job_vacancy_reserved_zero=(0.99, None),
    # 47,748 / 47,248 / 47,748 rows walked on the three saves measured. The floor sits nearly
    # five times below that, which leaves an installed database carrying far fewer grounds well
    # clear; walking from one byte, four bytes or a byte short of the head reads no row at all,
    # so a head that moved fails here.
    stadium_rows_minimum=(10_000, None),
    # Every row but the template has a pitch inside the layout's length range and inside its
    # own stored minimum and maximum, on all three saves. Reading the pitch fields one byte,
    # four bytes or a byte short of their offsets drops the share to 0.0, so this is the check
    # that says the row's middle is still being read where it sits.
    stadium_pitch_within_limits=(0.99, None),
    # 0.98354 / 0.98244 / 0.98354 of the rows naming an owning club name one the save lists;
    # the rest name a club of a nation the career never loaded. Reading the owner one byte out
    # scores 0.0007 / 0.0002, a byte short 0.0031 / 0.0030 and four bytes out 0.838, so the
    # floor catches every one of those while leaving a career that loaded fewer nations clear.
    stadium_owners_resolved=(0.95, None),
    # 0.99971 / 0.99972 / 0.99971 of rows hold a capacity no larger than their all-seater
    # capacity, which is 0 on about four rows in five. The misaligned reads score 0.376, 0.827
    # and 0.0.
    stadium_capacity_within_all_seater=(0.99, None),
    # 0.708 / 0.716 / 0.700 of the clubs that own a ground and have a calendar home ground
    # play at a ground they own themselves; the rest ground-share or play at a ground the save
    # gives no owner. Shifting the ordinal a fixture stores by one either way scores 0.0008 to
    # 0.0016, so the floor sits far below the observed share and far above the control.
    stadium_home_grounds_owned=(0.50, None),
    # Every club record of every save measured holds its affiliated-team list and exactly three
    # staff lists inside the record. Reading the lists one byte late leaves 0.729 of records
    # fitting and four bytes late 0.271, so nothing but an exact bound would catch either.
    staff_lists_fit=(1.0, None),
    # 14,989 of 14,990, 2,866 of 2,867 and 13,532 of 13,533 listed people have a staff object
    # with a name block; the one that does not has two headers to choose between. Reading the
    # list start one byte early drops it to 0.934 and one byte late to 0.378.
    staff_list_ids_are_staff=(0.99, None),
    # Every staff object a row was built from carries an ability signature, preference slots all
    # in range and the block of 1..100 bytes. Reading the entry count one byte late leaves
    # 0.725 on the first two, and reading the ability block one byte either way or four bytes
    # late leaves at most 0.027 on either.
    staff_ability_signature=(0.99, None),
    staff_preference_slots=(0.99, None),
    # Six staff objects of 18,238 and two of 4,108 carry a code outside the 14-value set, so the
    # floor sits below 0.9995. One byte early leaves 0.019 and every other shift 0.
    staff_codes_in_set=(0.98, None),
    # 1.0 on all three saves, and 0.075 with the ability block one byte late and 0 four bytes
    # late. One byte early leaves it at 1.0, which the three shares above catch instead.
    staff_block_40_in_range=(0.99, None),
    # Every person a row was built from has a name block the player decoder validates. A window
    # that starts past where the block sits leaves 0.121.
    staff_person_blocks=(0.99, None),
    # 18,239 / 4,109 / 16,473 people on the saves measured. The floor is far below the smallest
    # of those: what it catches is a list read or a discovery pass that finds next to nothing.
    staff_minimum=(1_000, None),
    # 0.916 / 0.689 / 0.911 of listed pairs have a contract at the listing club or at its
    # parent. The floor clears the lowest of those by 22% of its width, which is thin, and it
    # was kept because the list start read one byte late leaves 0.230, far below it.
    staff_listed_contracted_here=(0.60, None),
    # Every contract record with a tail has its person's header in front of it on all three
    # saves. With the kind byte read one byte out, no header is accepted and 13,504 records are
    # left unowned.
    staff_unowned_tailed_contracts=(None, 0),
)

LAYOUTS: tuple[LayoutEntry, ...] = (
    LayoutEntry(region="game_info", schema=46, build=BUILD, layout=GAME_INFO),
    LayoutEntry(region="save_game_summary", schema=29, build=BUILD, layout=SAVE_SUMMARY),
    LayoutEntry(region="save_game_summary", schema=29, build=BUILD, layout=SUMMARY_STRINGS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=NAME_POOLS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=CLUB_RECORDS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=TEAM_LISTS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=CLUB_STATUSES),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=PLAYER_RECORDS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=PERSON_BLOCKS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=CONTRACTS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=FINANCE_CHAINS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=SPONSOR_CHAINS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=SUSPENSIONS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=MATCH_RECORDS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=STADIUM_TABLE),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=STAGE_TABLE),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=COMPETITION_ID_PAIRS),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=TAGGED_STREAM),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=TRANSFER_WINDOWS),
    LayoutEntry(region="humans", schema=21, build=BUILD, layout=HUMANS),
    LayoutEntry(region="feeder_man", schema=5, build=BUILD, layout=AFFILIATE_GROUPS),
    LayoutEntry(region="injury_manager", schema=8, build=BUILD, layout=INJURY_MANAGER),
    LayoutEntry(region="job_centre", schema=1, build=BUILD, layout=JOB_CENTRE),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=STAFF),
    LayoutEntry(region=MATCH_FILE_REGION_NAME, schema=None, build=BUILD, layout=INJURY_TYPE_TABLE),
    LayoutEntry(region=SPAN_REGION_NAME, schema=None, build=BUILD, layout=FIXTURE_CALENDAR),
    LayoutEntry(region=SPAN_REGION_NAME, schema=None, build=BUILD, layout=STAGE_RESULTS),
    LayoutEntry(region=SPAN_REGION_NAME, schema=None, build=BUILD, layout=LEAGUE_TABLES),
    LayoutEntry(region=SPAN_REGION_NAME, schema=None, build=BUILD, layout=RULES_PREAMBLES),
    LayoutEntry(region="game_db", schema=4000, build=BUILD, layout=GATE_BOUNDS),
)
