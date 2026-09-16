"""Private layout tables: where fields sit inside each region.

Layouts are keyed by (region, schema number) with the game build as a fallback,
because some regions carry no schema number. Modules are organised per game year
and build.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GameInfoLayout:
    """Offsets inside `game_info`.

    Offsets named `*_after_db_version` count from the end of the length-prefixed
    database version string, whose length varies.
    """

    db_version_length_offset: int
    max_db_version_bytes: int
    build_number_offsets_after_db_version: tuple[int, ...]
    game_date_offset_after_db_version: int


@dataclass(frozen=True, slots=True)
class SaveSummaryLayout:
    """How to recognise the `MAJOR.MINOR.PATCH+BUILD` version string in `save_game_summary`.

    `version_pattern` must match a whole length-prefixed string, so it carries no anchors
    or lookarounds.
    """

    version_pattern: str
    max_version_bytes: int


@dataclass(frozen=True, slots=True)
class SummaryStringsLayout:
    """How to pick the length-prefixed strings out of `save_game_summary`.

    Every offset from `strings_start_offset` is tried in order. A string is a u32 byte length
    within `string_length_range` (inclusive) followed by that many bytes of valid UTF-8 with
    no character below `lowest_code_point`. After a string the search continues at its end;
    anywhere else it moves on by one byte.
    """

    strings_start_offset: int
    string_length_range: tuple[int, int]
    lowest_code_point: int


@dataclass(frozen=True, slots=True)
class HumansLayout:
    """Where the human managers are named in `humans`, and how their person header is found.

    The u16 at `human_count_offset` is the number of human managers, and the u32 at
    `first_selector_offset` is the first human manager's person id plus 1. In `game_db`, that
    person's header is the u32 person id followed by the same uid at `person_uid_offset` and at
    `person_uid_copy_offset`, both counted from the person id; a uid of 0 or FFFFFFFF does not
    count.
    """

    human_count_offset: int
    first_selector_offset: int
    person_uid_offset: int
    person_uid_copy_offset: int


# Count checks (such as the name pool minimum) apply only to a decompressed `game_db` at
# least this large; smaller sections come from fragments that cannot meet full-save counts.
FULL_SAVE_MINIMUM_GAME_DB_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NamePoolLayout:
    """How to find and check the three name pools in `game_db`.

    `signature` sits immediately before the first pool's entry count. The pool minimum
    applies only when `game_db` is at least `minimum_applies_from_bytes` long; the other
    checks always apply.
    """

    signature: bytes
    max_name_bytes: int
    minimum_entries_per_pool: int
    minimum_applies_from_bytes: int


@dataclass(frozen=True, slots=True)
class ClubRecordLayout:
    """How to recognise club records in `game_db` and where their fields sit.

    A candidate record starts `anchor_offset` bytes before each `anchor` hit, and every other
    offset counts from that start. The league nation is stored twice, as is the uid. Ranges
    are inclusive (lowest, highest). Once a record has been accepted, the scan ends at the
    first candidate `stop_gap_bytes` or more past the last accepted record start; that point
    also ends the last record.
    """

    anchor: bytes
    anchor_offset: int
    club_index_offset: int
    uid_offset: int
    uid_copy_offset: int
    zero_byte_offset: int
    nation_offset: int
    fa_nation_offset: int
    nation_copy_offset: int
    city_offset: int
    long_name_offset: int
    nation_id_range: tuple[int, int]
    max_name_bytes: int
    stop_gap_bytes: int


@dataclass(frozen=True, slots=True)
class TeamListLayout:
    """How to find and parse the team list inside one club record.

    The list starts at the record's first `null_date_triple`. When that does not parse, each
    `float_anchor` hit at least `minimum_float_anchor_record_offset` bytes into the record is
    tried, with the list starting `float_anchor_offset` bytes before it. Offsets count from
    the list start. At `counts_offset` comes a count of `first_entry_bytes`-byte entries that
    each begin with `first_entry_lead_byte`, then a count of `second_entry_bytes`-byte entries
    that each begin with `second_entry_lead_byte`, then `filler_bytes` bytes, then the team
    count and that many u32 team ids. Right after those ids comes the affiliated-team list:
    a count within `affiliate_count_range` and that many u32 team ids, each a team another
    club record stores. Ranges are inclusive (lowest, highest).
    """

    null_date_triple: bytes
    float_anchor: bytes
    float_anchor_offset: int
    minimum_float_anchor_record_offset: int
    counts_offset: int
    first_entry_bytes: int
    first_entry_lead_byte: int
    second_entry_bytes: int
    second_entry_lead_byte: int
    filler_bytes: int
    team_count_range: tuple[int, int]
    team_id_range: tuple[int, int]
    affiliate_count_range: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ClubStatusLayout:
    """Where a club's reputation and last league position sit in the club-status table.

    Offsets count from a hit of the club's stored uid (uid minus 1) written twice, so
    `ordinal_offset` is negative. A hit counts when its ordinal is above the last accepted
    ordinal and below `ordinal_limit`, and its kind byte is `normal_kind` or `stub_kind`. Only
    normal records hold a position and a reputation. Ranges are inclusive (lowest, highest).

    Clubs are searched in club index order from a cursor that moves past each accepted hit.
    Until the first hit is accepted a search runs to the end of `game_db`, and when the first
    `maximum_leading_misses` clubs all miss, the walk stops with no status for any club. After
    that, a club's hit must start at most `search_window_bytes` past the cursor.

    A normal status record is confirmed, for the club checks only, when the u32 at
    `confirmation_offset` (from the hit, so negative) holds the club's stored index (the public
    index minus 1) and the `confirmation_zero_bytes` bytes after it are zero. The confirmation
    never decides which record is accepted.
    """

    ordinal_offset: int
    ordinal_limit: int
    kind_offset: int
    normal_kind: int
    stub_kind: int
    position_offset: int
    reputation_offset: int
    reputation_range: tuple[int, int]
    search_window_bytes: int
    confirmation_offset: int
    confirmation_zero_bytes: int
    maximum_leading_misses: int = 16


@dataclass(frozen=True, slots=True)
class PersonBlockLayout:
    """How to locate and parse a player's person block inside its record window.

    The block is found by searching the window `[record_offset + window_start_offset,
    record_window_end)` for `personality_count` consecutive bytes in `personality_range`
    (the personality profile) starting at `r`; the birth date sits at
    `birth_date_offset_from_run = r - personality_offset_from_birth`. Offsets suffixed
    `_from_birth` count from the birth date position `p`; offsets suffixed `_from_block_start`
    count from the block start `q`, found by walking backwards from `p`. `relation_pairs`
    maps a `(kind, role)` pair to the person field it fills.

    Every position inside a `relation_entry_bytes`-byte relation entry comes from this layout,
    counted from the entry start: the u32 referenced id at `relation_referenced_offset_in_entry`,
    the kind byte then the role byte at `relation_kind_role_offset_in_entry`, the qualifier byte
    at `relation_qualifier_offset_in_entry` and the sentinel byte at
    `relation_sentinel_offset_in_entry`. The person checks count second-nation entries whose
    qualifier is one of `second_nation_qualifiers` and entries whose sentinel byte equals
    `relation_sentinel_value`.
    """

    window_start_offset: int
    personality_offset_from_birth: int
    personality_count: int
    personality_range: tuple[int, int]
    date_zero_bytes_offset_from_birth: int
    date_zero_bytes_count: int
    legal_name_length_min: int
    legal_name_length_max: int
    name_id_limit: int
    first_name_id_offset_from_block_start: int
    surname_id_offset_from_block_start: int
    common_name_id_offset_from_block_start: int
    legal_name_length_offset_from_block_start: int
    legal_name_offset_from_block_start: int
    trait_bits_offset_from_block_start: int
    nation_id_offset_from_birth: int
    relation_present_offset_from_birth: int
    relation_count_offset_from_birth: int
    relation_entries_offset_from_birth: int
    relation_entry_bytes: int
    second_nation_pair: tuple[int, int]
    home_grown_nation_pair: tuple[int, int]
    home_grown_club_pair: tuple[int, int]
    relation_referenced_offset_in_entry: int
    relation_kind_role_offset_in_entry: int
    relation_qualifier_offset_in_entry: int
    relation_sentinel_offset_in_entry: int
    second_nation_qualifiers: tuple[int, ...]
    relation_sentinel_value: int


@dataclass(frozen=True, slots=True)
class PlayerRecordLayout:
    """How to recognise player records in `game_db` and where their fields sit.

    A marker candidate starts `marker_offset` bytes before each `marker` hit. A completeness
    candidate starts `ratings_offset` bytes before a match of `ratings_count` bytes in
    `rating_range` followed by `attribute_count` bytes in `attribute_range`, searched only in
    the region after the name pools. Every other offset counts from the record start. Ranges
    are inclusive (lowest, highest). `attribute_field_order` names the 52 non-foot attributes
    in the order the bytes at `attributes_offset` store them, skipping the byte at
    `left_foot_index` and at `right_foot_index` (indexes into that 54-byte span, not
    record offsets); `position_codes` names the 15 position ratings in the order stored at
    `ratings_offset`. `decode_extent` is the offset, from the record start, one past the
    last byte a full decode reads: a candidate that passes every acceptance check but whose
    record does not reach `record_offset + decode_extent` is a truncated record, not a
    rejected one.
    """

    marker: bytes
    marker_offset: int
    pindex_offset: int
    uid_offset: int
    uid_copy_offset: int
    home_reputation_offset: int
    current_reputation_offset: int
    world_reputation_offset: int
    current_ability_offset: int
    current_ability_range: tuple[int, int]
    potential_ability_offset: int
    potential_ability_range: tuple[int, int]
    reputation_bucket_offset: int
    reputation_bucket_range: tuple[int, int]
    team_id_offset: int
    ratings_offset: int
    ratings_count: int
    rating_range: tuple[int, int]
    attributes_offset: int
    attribute_count: int
    attribute_range: tuple[int, int]
    left_foot_index: int
    right_foot_index: int
    transfer_value_offset: int
    transfer_value_placeholder: int
    club_join_date_offset: int
    match_sharpness_offset: int
    condition_offset: int
    height_offset: int
    decode_extent: int
    position_codes: tuple[str, ...]
    attribute_field_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContractLayout:
    """How to locate and parse a player's contract chain in `game_db`.

    A chain record for pindex `x` at record start `record_offset` (next record start
    `next_record_offset`, or the end of `game_db` for the last record) is a hit of `tag`
    in `[record_offset + chain_window_start_offset, next_record_offset +
    chain_window_end_offset)` (the end of `game_db` for the last record's window) whose
    `u32` at `selector_offset` equals `x + 1`. Every other chain, tail, clause and head
    offset counts from the tag hit `M` (chain fields, `team_id_offset`, `wage_offset`) or
    from a tail start `E` (`tail_*`) or a clause-table base `base` (`clause_*`, `head_*`).

    The tail is found by trying `E = M - tail_base_offset - tail_step_bytes * event_count`
    for `event_count` from 0 to `tail_max_event_count`, accepted when the byte at
    `E + tail_sentinel_byte_offset` equals `tail_sentinel_byte_value` and the `u32` at
    `E + tail_sentinel_word_offset` equals `tail_sentinel_word_value` (`tail_sentinel_word_offset`
    is always `tail_sentinel_byte_offset + 1`, so the two sentinels form one contiguous
    signature) and the stored event count at `tail_event_count_offset` matches.

    A record whose tail does not parse is still preceded by a tail-shaped block, which is
    where a loan's end date and marker sit. That block is looked for the same way, without
    the sentinel checks and only up to `loan_block_max_event_count` steps back, and is
    accepted when the count byte at `tail_event_count_offset` matches the step and the end
    at `tail_end_offset` is a game date or the missing-date marker; its `tail_e24_offset`
    word marks a loan.

    A clause table holds, from `base + clause_ff_offset`: an 8-byte marker
    (`clause_ff_count` bytes), `clause_zero_count` zero bytes, the clause count byte at
    `base + clause_count_offset`, and that many entries from `base + clause_entries_offset`,
    each `clause_entry_bytes` long. After the last entry come two bonus lists and a trailer:
    a competition count (`clause_competition_count_bytes` wide) and that many
    `clause_competition_item_bytes`-byte items, each starting with
    `clause_competition_item_prefix`; an award flag (`clause_award_flag_bytes` wide) that is 0
    for no award list, or 1 followed by an award count (`clause_award_count_bytes` wide) and
    that many `clause_award_item_bytes`-byte items, each starting with
    `clause_award_item_prefix`; then `clause_trailer_bytes` zero bytes, which end at `E`. With
    both lists empty, the bytes after the entries are `-clause_entries_offset` zero bytes.

    Once a tail is found, the clause table is looked for first by trying
    `base = E - clause_step_bytes * count` for `count` from 0 to `clause_max_count`, accepted
    when the marker is `FF` x `clause_ff_count` and the zero run and the count byte equal to
    `count` follow it: the position of a table whose bonus lists are empty. When that finds
    nothing, the table is taken to be the one nearest `E` whose entries, bonus lists (up to
    `clause_competition_max_count` competition items and `clause_award_max_count` award items)
    and trailer end exactly at `E`, whose zero run and count byte check, and whose marker is
    either `FF` x `clause_ff_count` or a `clause_team_marker_id_bytes`-byte team id that is
    neither all `FF` nor all zero, followed by zero bytes. The head fields are read only when
    the `u16` at
    `base + head_gate_offset` equals `head_gate_value`.

    The fallback reader walks `FF FF FF FF` hits in `[record_offset +
    fallback_start_from_record, limit)`, where `limit` is `max(record_offset +
    fallback_start_from_record, next_record_offset - fallback_end_margin)` (`next_record_offset`
    the end of `game_db` for the last record). For a hit at `i`, `j = i + 8`; when `j +
    fallback_gate_length <= limit` and the `fallback_nonzero_length` bytes at `j +
    fallback_nonzero_offset` are not all zero, an end date sits at `j +
    fallback_end_date_offset` and a start date at `j + fallback_start_date_offset`.
    """

    tag: bytes
    chain_window_start_offset: int
    chain_window_end_offset: int
    selector_offset: int
    start_offset: int
    team_id_offset: int
    wage_offset: int

    tail_base_offset: int
    tail_step_bytes: int
    tail_max_event_count: int
    tail_sentinel_byte_offset: int
    tail_sentinel_byte_value: int
    tail_sentinel_word_offset: int
    tail_sentinel_word_value: int
    tail_e2_offset: int
    tail_e8_offset: int
    tail_e12_offset: int
    tail_e16_offset: int
    tail_e20_offset: int
    tail_e24_offset: int
    tail_end_offset: int
    tail_squad_status_offset: int
    tail_e37_offset: int
    tail_e38_offset: int
    tail_e39_offset: int
    tail_event_count_offset: int
    loan_block_max_event_count: int

    clause_step_bytes: int
    clause_max_count: int
    clause_ff_offset: int
    clause_ff_count: int
    clause_zero_offset: int
    clause_zero_count: int
    clause_count_offset: int
    clause_entries_offset: int
    clause_entry_bytes: int
    clause_value_offset: int
    clause_parameter_offset: int
    clause_kind_offset: int
    clause_team_marker_id_bytes: int
    clause_competition_count_bytes: int
    clause_competition_item_bytes: int
    clause_competition_item_prefix: bytes
    clause_competition_max_count: int
    clause_award_flag_bytes: int
    clause_award_count_bytes: int
    clause_award_item_bytes: int
    clause_award_item_prefix: bytes
    clause_award_max_count: int
    clause_trailer_bytes: int

    head_gate_offset: int
    head_gate_value: int
    head_type_offset: int
    head_money_a_offset: int
    head_money_b_offset: int
    head_money_c_offset: int

    fallback_start_from_record: int
    fallback_end_margin: int
    fallback_nonzero_offset: int
    fallback_nonzero_length: int
    fallback_end_date_offset: int
    fallback_start_date_offset: int
    fallback_gate_length: int


@dataclass(frozen=True, slots=True)
class SuspensionLayout:
    """How to find unserved suspension entries in `game_db` and where their fields sit.

    Every offset counts from an entry's start. An entry sits wherever, for each `(offset,
    value)` pair in `signature`, the byte at that offset equals `value`; the bytes between
    signature bytes may hold anything. One search runs from `owner_back_offset` bytes before
    the first player record's start to the end of `game_db`. An entry belongs to the player
    with the greatest record start `record_offset` for which `record_offset -
    owner_back_offset` is at or before the entry's start; an entry before the first player's
    window belongs to no player. An entry is kept only when the date at `issued_date_offset`
    is a valid game date and the u16 at `competition_id_offset` lies strictly between the
    (lower, upper) values of `competition_id_exclusive_range`.
    """

    signature: tuple[tuple[int, int], ...]
    unknown_e7_offset: int
    issued_date_offset: int
    unknown_e14_offset: int
    competition_id_offset: int
    owner_back_offset: int
    competition_id_exclusive_range: tuple[int, int]


# Count and distribution checks on the unnamed span apply only to a span at least this
# large; a smaller span comes from a fragment that cannot meet full-save counts.
FULL_SAVE_MINIMUM_SPAN_BYTES = 16 * 1024 * 1024

# How many bytes of the previous window each span window keeps in front of its frame, so a
# record lying across a frame boundary is whole in one window. Far above the longest record
# the span holds: a fixture is 68 bytes and the largest league-table block 1,447.
SPAN_CARRY_OVER_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class FixtureCalendarLayout:
    """How to recognise fixture calendar records in the unnamed span, and where fields sit.

    Every offset counts from the record start, which is where the home team id sits, so the
    offsets of the locator byte, the stage id and the stadium ordinal are negative. Records
    are found by a pattern built from this layout and the save's in-game date: the first
    sentinel byte, the bytes up to the second sentinel byte, then the bytes up to the low
    byte of the kick-off year, which must be one of the years from `years_before_clock`
    before the in-game year to `years_after_clock` after it, and then that shared high byte.

    A candidate is accepted when the whole record lies inside the window, the byte at
    `marker_byte_offset` equals `marker_byte_value`, every `(offset, value)` pair in
    `sentinel_offsets` holds, and both team ids lie inside the inclusive `team_id_range`.
    The stadium ordinal is stored as the ordinal plus one.

    `round_index_none_value`, `kick_off_slot_offset`, `kick_off_slot_minutes` and
    `cluster_gap_bytes` are for the fixtures reader rather than the span pass: a kick-off
    time is `(stored slot + kick_off_slot_offset) * kick_off_slot_minutes` minutes into the
    day, a round index of `round_index_none_value` means no round, and a gap of
    `cluster_gap_bytes` or more between records separates the calendar from a stray copy.
    """

    record_bytes: int
    marker_byte_offset: int
    marker_byte_value: int
    sentinel_offsets: tuple[tuple[int, int], ...]
    stage_id_offset: int
    stadium_ordinal_offset: int
    home_team_id_offset: int
    away_team_id_offset: int
    kick_off_date_offset: int
    date2_offset: int
    season_start_year_offset: int
    match_record_id_offset: int
    phase_offset: int
    leg_offset: int
    round_index_offset: int
    r39_42_offset: int
    match_rules_template_offset: int
    match_rules_template_bytes: int
    r47_54_offset: int
    played_offset: int
    team_id_range: tuple[int, int]
    years_before_clock: int
    years_after_clock: int
    round_index_none_value: int
    kick_off_slot_offset: int
    kick_off_slot_minutes: int
    cluster_gap_bytes: int


@dataclass(frozen=True, slots=True)
class LeagueTableLayout:
    """How to recognise league-table blocks in the unnamed span, and where fields sit.

    A block is found by its `aggregate_count` aggregate rows, each `row_bytes` long and each
    keyed `unplayed_key`; the first of them is the block head, and every offset counts from
    there, so `team_id_offset` and `head_bytes_offset` are negative. After the aggregates
    come the u16 at `rounds_per_venue_offset` and, at `matches_offset`, twice that many
    match rows, whose venue alternates with the slot's parity.

    Each row holds a u32 key, the played count twice, the won, drawn and lost counts, a zero
    byte, the u16 goals for, goals against and points, and a flag byte. On an aggregate row,
    and in a match slot that was never played, the key is `unplayed_key`; otherwise it is the
    opponent's first-team id.

    A candidate is accepted when the whole block lies inside the window, `rounds_per_venue`
    lies inside the inclusive `rounds_per_venue_range`, every aggregate row has both played
    counts equal and played equal to won plus drawn plus lost, the home and away rows'
    played counts add up to the total row's, so do the two half rows', and the total row has
    played at least one match. `team_id_range`, `group_gap_bytes` and `division_club_range`
    are for the league-tables reader rather than the span pass: a gap of `group_gap_bytes`
    or more between blocks separates two groups, and a group of that many clubs playing
    each other twice is a division.
    """

    row_bytes: int
    aggregate_count: int
    team_id_offset: int
    head_bytes_offset: int
    head_bytes_count: int
    rounds_per_venue_offset: int
    matches_offset: int
    rounds_per_venue_range: tuple[int, int]
    key_offset: int
    played_offset: int
    played_copy_offset: int
    won_offset: int
    drawn_offset: int
    lost_offset: int
    zero_offset: int
    goals_for_offset: int
    goals_against_offset: int
    points_offset: int
    flag_offset: int
    unplayed_key: int
    team_id_range: tuple[int, int]
    group_gap_bytes: int
    division_club_range: tuple[int, int]


@dataclass(frozen=True, slots=True)
class RulesPreambleLayout:
    """How to read a competition-rules preamble block in the unnamed span.

    A block is found by `marker`. The promotion quad sits at `promotion_quad_offset` and is
    `promotion_quad_bytes` long, written twice back to back and ending where the marker
    starts: promotion places, playoff places, an unidentified byte, relegation places. When
    the two copies differ, none of the four is read.

    The body starts `body_offset` bytes after the marker and holds, in order, a u32
    tie-break count of at most `tie_break_count_max` and that many bytes, a u32 prize count
    of at most `prize_count_max` and that many u32 prizes, and a u32 round count of at least
    one and at most `round_count_max`. The round records follow, each `round_record_bytes`
    long, anchored on the first of the `round_anchor_search_bytes` offsets after the count
    whose date decodes; the first record's `round_kind_offset` byte is the count's own high
    byte, which is always zero.

    Inside a round record the unidentified `kind` byte sits at `round_kind_offset`, the date
    at `round_date_offset`, a second unidentified byte at `round_b5_offset`, the round
    number minus one (or `round_no_number_value` for a round the save does not number) at
    `round_number_offset`, and the u32 match count, at most `round_match_count_max`, at
    `round_match_count_offset`.

    Between round records the save writes moved or reserved matches as blocks of
    `moved_match_bytes` bytes, recognised by `moved_match_sentinel_value` at
    `moved_match_sentinel_offset` and `moved_match_tail` at `moved_match_tail_offset`; up to
    `moved_match_max_per_round` of them follow one round. Stepping over them is what keeps
    the round records in step: on the corpus a plain stride reads about 65% of blocks
    correctly and this stride about 96%.
    """

    marker: bytes
    promotion_quad_offset: int
    promotion_quad_bytes: int
    body_offset: int
    tie_break_count_max: int
    prize_count_max: int
    round_count_max: int
    round_record_bytes: int
    round_anchor_search_bytes: int
    round_kind_offset: int
    round_date_offset: int
    round_b5_offset: int
    round_number_offset: int
    round_no_number_value: int
    round_match_count_offset: int
    round_match_count_max: int
    moved_match_bytes: int
    moved_match_sentinel_offset: int
    moved_match_sentinel_value: int
    moved_match_tail_offset: int
    moved_match_tail: bytes
    moved_match_max_per_round: int


@dataclass(frozen=True, slots=True)
class StageTableLayout:
    """Where the stage table sits in `game_db`, and where a stage row's fields sit.

    The table is found in the last `search_bytes` of `game_db`, at the first offset where
    `chain_rows` rows in a row all decode `row_bytes` apart; the head of that chain is then
    reached by stepping back a row at a time. A row decodes when the byte at
    `zero_byte_offset` is zero, the stage id at `stage_id_offset` is repeated at
    `stage_id_copy_offset` and lies strictly between the bounds of
    `stage_id_exclusive_range`, and the word at `previous_stage_id_offset` is either that id
    minus 1 or the missing value. Where a row does not decode, the walk scans forward at most
    `resynchronisation_bytes` for the next one that does.

    Every other offset counts from the row start. A competition id at or above
    `competition_id_limit` is a marker or a malformed row rather than a competition, and is
    read as no competition.
    """

    row_bytes: int
    previous_stage_id_offset: int
    stage_id_offset: int
    stage_id_copy_offset: int
    zero_byte_offset: int
    competition_id_offset: int
    group_id_offset: int
    round_offset: int
    unknown_s25_offset: int
    unknown_s29_offset: int
    stage_id_exclusive_range: tuple[int, int]
    competition_id_limit: int
    search_bytes: int
    chain_rows: int
    resynchronisation_bytes: int


type BoundPair = tuple[float | None, float | None]


@dataclass(frozen=True, slots=True)
class GateBounds:
    """Loose bounds for the reader checks on what the `game_db` readers decode.

    Each `BoundPair` is an inclusive `(minimum, maximum)` pair; None leaves that side open.
    Rates are shares from 0 to 1, and the other bounds are counts or medians. The checks apply
    only when `game_db` is at least `minimum_applies_from_bytes` long, because smaller sections
    come from fragments that cannot meet full-save counts; the checks on what the span pass
    reads apply only from `span_minimum_applies_from_bytes` of decompressed span, for the same
    reason.

    The readers count values inside these inclusive ranges: `height_range_cm` (heights),
    `age_range_years` (known ages), `home_reputation_window` (the largest difference between
    home and current reputation counted as near), `condition_sharpness_maximum` (the
    largest condition and match sharpness on their stored scale), `natural_goalkeeper_rating`
    (the lowest goalkeeper rating that marks a natural goalkeeper, left out of the outfield
    count) and `goalkeeper_block_low_maximum` (the highest raw handling and raw throwing counted
    as low).

    Players: `players_minimum` (records), `person_blocks` (records with a person block),
    `names_resolved` (of person blocks), `relation_sentinel` (relation entries ending in the
    sentinel byte), `second_nation_qualifier` (second-nation entries with a known qualifier),
    `handling_above_finishing` (all records), `outfield_goalkeeper_block_low` (outfield
    players whose raw handling and raw throwing are both low, of outfield players),
    `with_natural_position`, `height_in_range`,
    `height_median`, `age_median`, `aged_in_range` (of known ages),
    `condition_sharpness_in_range`, `join_date_valid`, `world_not_above_current`,
    `home_near_current`, `team_resolved` (of players with a team) and
    `home_grown_club_refs_resolved` (of home-grown club references).

    Contracts: `players_with_chain` (of players), `no_contract_in_effect` (players whose
    chain records all start after the in-game date, of players with a chain),
    `date_marked_chain_records` (chain records
    found by a date in their tag slot, of chain records), `tails_parsed` (of chain records),
    `tails_without_clause_table` (parsed tails where no clause table is found, of parsed tails),
    `clause_terminator` (clause tables whose bonus lists and zero trailer end exactly at the
    tail start, of clause tables), `contract_head` (of clause tables), `past_dated_tail_ends`
    (of parsed tails with an end date) and `chain_teams_resolved` (of chain records). Only
    tables found by the first search can fail `clause_terminator`, since the search that works
    back from the tail accepts a table only when it ends there; a table that search cannot find
    at all counts towards `tails_without_clause_table` instead, so the two together cover every
    way a clause table can go missing or stop short.

    Clubs: `clubs_minimum` (records), `team_lists_found` and `status_normal` (of clubs),
    `status_confirmation` (of normal status records), `affiliate_lists_found` (club records
    holding an affiliated-team list, of club records) and `affiliate_teams_linked` (listed
    affiliate teams that belong to one other club, of listed affiliate teams). The second is
    not applied when no club lists a team, so the first is what fails when the affiliate
    decode finds nothing at all.

    Suspensions: `suspension_share_of_players` (players with an entry, of players; not applied
    without players) and `issued_after_clock` (entries issued after the in-game date, of
    entries; not applied without entries).

    Stages: `stage_rows_minimum` (rows walked), `stage_walk_gaps` (places the walk had to
    resynchronise), `stage_ids_ascending` (steps that reached a higher stage id, of steps),
    `stage_rows_with_competition` (of rows), `stage_trailing_sentinel` (rows whose last word
    is the missing value, of rows) and `stage_table_tail_bytes` (bytes of `game_db` after the
    table, which is near its end).

    Competitions: `competitions_minimum` (distinct competitions the stage table names).
    """

    minimum_applies_from_bytes: int
    span_minimum_applies_from_bytes: int
    height_range_cm: tuple[int, int]
    age_range_years: tuple[int, int]
    home_reputation_window: int
    condition_sharpness_maximum: int
    natural_goalkeeper_rating: int
    goalkeeper_block_low_maximum: int
    players_minimum: BoundPair
    person_blocks: BoundPair
    names_resolved: BoundPair
    relation_sentinel: BoundPair
    second_nation_qualifier: BoundPair
    handling_above_finishing: BoundPair
    outfield_goalkeeper_block_low: BoundPair
    with_natural_position: BoundPair
    height_in_range: BoundPair
    height_median: BoundPair
    age_median: BoundPair
    aged_in_range: BoundPair
    condition_sharpness_in_range: BoundPair
    join_date_valid: BoundPair
    world_not_above_current: BoundPair
    home_near_current: BoundPair
    team_resolved: BoundPair
    home_grown_club_refs_resolved: BoundPair
    players_with_chain: BoundPair
    no_contract_in_effect: BoundPair
    date_marked_chain_records: BoundPair
    tails_parsed: BoundPair
    tails_without_clause_table: BoundPair
    clause_terminator: BoundPair
    contract_head: BoundPair
    past_dated_tail_ends: BoundPair
    chain_teams_resolved: BoundPair
    clubs_minimum: BoundPair
    team_lists_found: BoundPair
    status_normal: BoundPair
    status_confirmation: BoundPair
    affiliate_lists_found: BoundPair
    affiliate_teams_linked: BoundPair
    suspension_share_of_players: BoundPair
    issued_after_clock: BoundPair
    stage_rows_minimum: BoundPair
    stage_walk_gaps: BoundPair
    stage_ids_ascending: BoundPair
    stage_rows_with_competition: BoundPair
    stage_trailing_sentinel: BoundPair
    stage_table_tail_bytes: BoundPair
    competitions_minimum: BoundPair


type Layout = (
    GameInfoLayout
    | SaveSummaryLayout
    | SummaryStringsLayout
    | NamePoolLayout
    | ClubRecordLayout
    | TeamListLayout
    | ClubStatusLayout
    | PlayerRecordLayout
    | PersonBlockLayout
    | ContractLayout
    | SuspensionLayout
    | StageTableLayout
    | HumansLayout
    | FixtureCalendarLayout
    | LeagueTableLayout
    | RulesPreambleLayout
    | GateBounds
)


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    region: str
    schema: int | None
    build: str
    layout: Layout


@dataclass(frozen=True, slots=True)
class LayoutMatch[LayoutT]:
    layout: LayoutT
    exact: bool


FALLBACK_BUILD = "26.3.2+2329565"


def registered_layouts() -> tuple[LayoutEntry, ...]:
    from fmsave._layouts import fm26_26_3_2

    return fm26_26_3_2.LAYOUTS


def known_builds() -> frozenset[str]:
    return frozenset(entry.build for entry in registered_layouts())


def find_layout[LayoutT: Layout](
    layout_type: type[LayoutT], region: str, schema: int | None, build: str
) -> LayoutMatch[LayoutT]:
    candidates = [
        entry
        for entry in registered_layouts()
        if entry.region == region and isinstance(entry.layout, layout_type)
    ]
    for entry in candidates:
        if schema is not None and entry.schema == schema and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=True)
    for entry in candidates:
        if entry.build == build and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=entry.schema is None)
    for entry in candidates:
        if entry.build == FALLBACK_BUILD and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=False)
    raise LookupError(f"no {layout_type.__name__} registered for region {region!r}")
