"""Counts the readers keep while they decode, for the reader checks in fmsave.checks.

Each record holds plain counts from one reader's existing pass; nothing here reads a save.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayerStats:
    """What one decode pass counted over the player records.

    `ages` holds every known age, for the median; `heights_median` is the low median of every
    record's height. Relation counts cover every entry of every validated person block. The
    `*_in_range` and `home_near_current` counts use the ranges in `GateBounds`.
    `outfield_players` counts records rated below `GateBounds.natural_goalkeeper_rating` in
    goal, and `outfield_goalkeeper_block_low` those of them whose raw handling and raw throwing
    are both at most `GateBounds.goalkeeper_block_low_maximum`.
    """

    records: int
    markerless: int
    with_person_block: int
    with_resolved_name: int
    relation_entries: int
    relation_sentinel_ok: int
    second_nation_entries: int
    second_nation_qualifier_ok: int
    handling_above_finishing: int
    outfield_players: int
    outfield_goalkeeper_block_low: int
    with_natural_position: int
    height_in_range: int
    condition_sharpness_in_range: int
    with_valid_join_date: int
    world_not_above_current: int
    home_near_current: int
    with_team: int
    team_resolved: int
    aged_in_range: int
    home_grown_club_refs: int
    home_grown_club_refs_resolved: int
    ages: array[int]
    heights_median: int | None


@dataclass(frozen=True, slots=True)
class ContractStats:
    """What one decode pass counted over the players' contract chain records.

    `without_contract_in_effect` counts players with chain records none of which is the
    contract in effect at the in-game date, because every one of them starts after it.
    `date_marked_chain_records` counts the chain records found by a date in their tag slot
    rather than by the tag itself. `tails_without_clause_table` counts parsed tails where no
    clause table is found, and
    `clause_tables` those where one is. `clause_tables_ending_at_tail` counts clause tables whose
    bonus lists and zero trailer end exactly at the tail start. `tail_ends` counts parsed tails
    with an end date, and `tail_ends_past` those whose end date is before the save's in-game
    date.
    """

    players: int
    contracts: int
    players_with_chain: int
    without_contract_in_effect: int
    chain_records: int
    date_marked_chain_records: int
    tails_parsed: int
    tails_without_clause_table: int
    clause_tables: int
    clause_tables_ending_at_tail: int
    head_ok: int
    tail_ends: int
    tail_ends_past: int
    chain_teams_resolved: int


@dataclass(frozen=True, slots=True)
class ClubStats:
    """What the club pass counted: records, team lists, status records and affiliate teams.

    `affiliate_lists` counts club records holding an affiliated-team list, `affiliate_refs`
    every team id those lists hold, and `affiliate_refs_linked` the ids linked to a
    controlling club, which needs an id to name a team of another club that no other club has
    already claimed. `reputation_found` counts the clubs whose status record held a
    reputation inside the layout's range, and `reputations_median` is the low median of those
    reputations.
    """

    records: int
    team_lists_found: int
    status_normal: int
    status_confirmed: int
    affiliate_lists: int
    affiliate_refs: int
    affiliate_refs_linked: int
    reputation_found: int
    reputations_median: int | None


@dataclass(frozen=True, slots=True)
class SuspensionStats:
    """What the suspension search counted over the player region."""

    players: int
    entries: int
    players_with_entries: int
    issued_after_clock: int


@dataclass(frozen=True, slots=True)
class StageStats:
    """What the stage table walk counted.

    `gaps` counts the places the walk had to resynchronise, `steps` the moves from one row to
    the next and `ascending_steps` those that reached a higher stage id.
    `competition_id_rejected` counts rows whose competition id is at or above the layout's
    limit, which is a marker rather than a competition, and `with_competition` the rows left
    holding one. `trailing_sentinel_ok` counts rows whose last word is the missing value, and
    `bytes_after_table` how much of `game_db` follows the table.
    """

    rows: int
    gaps: int
    ascending_steps: int
    steps: int
    with_competition: int
    competition_id_rejected: int
    trailing_sentinel_ok: int
    bytes_after_table: int


@dataclass(frozen=True, slots=True)
class CompetitionStats:
    """What the competition index collected from the stage table.

    `with_database_id` counts the competitions the id-pair records give an editor database id,
    of the `competitions` the stage table names. `database_id_conflicts` counts the competitions
    left without one because another competition claims the same database id. A competition the
    records themselves disagree about reaches neither count: the locator leaves an entity it
    has two database ids for out of the map it hands over.
    """

    competitions: int
    with_database_id: int
    database_id_conflicts: int
    with_name: int


@dataclass(frozen=True, slots=True)
class FixtureStats:
    """What building the fixture calendar counted.

    `span_records` counts every raw record the span pass found and `cluster_records` those in
    the run kept as the calendar, so `clusters` above one means stray copies were dropped.
    `strays_without_a_copy` counts the dropped records the calendar holds no copy of, which is
    what dropping them actually loses: most strays repeat a match the calendar already lists,
    and the rest are the template block every save carries plus, on one save measured, a few
    dozen unplayed matches that predate the calendar.
    `with_stage` counts kept records naming a stage and `stage_resolved` those whose stage the
    stage table holds. `home_team_resolved` and `away_team_resolved` count the team ids a club
    lists. `undated` counts records whose stored date does not decode and
    `bad_kick_off_slots` those whose slot names no time of day. `neutral_venue_votes` counts
    the (club, season) pairs that played enough home matches for a usual ground to be decided.
    """

    span_records: int
    cluster_records: int
    clusters: int
    strays_without_a_copy: int
    with_stage: int
    stage_resolved: int
    home_team_resolved: int
    away_team_resolved: int
    undated: int
    bad_kick_off_slots: int
    neutral_venue_votes: int


@dataclass(frozen=True, slots=True)
class ResultStats:
    """What joining the stage-keyed results onto the calendar counted.

    `candidates` counts every record the locator judged in the span and in the named sections,
    accepted or not, and `accepted` those that passed the record's own tests and fall inside the
    calendar's dates and the stage table. `joined` counts accepted records that found at least
    one fixture on their date and two team ids, so `ambiguous` and `score_for_unplayed` are both
    parts of it and `unjoined` is the rest of `accepted`.

    The same match is stored about 1.8 times over, so far more records join than there are
    fixtures to fill: a later copy carrying the score already written is ordinary and is counted
    in `joined` like any other. `score_disagreements` counts the copies that carry a *different*
    score for a fixture already filled, which is the one case arrival order must not settle;
    such a fixture keeps no score at all. No save measured has held one.

    `played_fixtures` counts the played matches in the calendar and `scored_fixtures` those that
    came out of this pass carrying a score, which is the share of a career's results the save
    still holds: about a quarter.
    """

    candidates: int
    accepted: int
    joined: int
    unjoined: int
    ambiguous: int
    score_for_unplayed: int
    score_disagreements: int
    played_fixtures: int
    scored_fixtures: int


@dataclass(frozen=True, slots=True)
class TransferWindowStats:
    """What the transfer-window pass counted over the tagged stream.

    `markers` counts the start-date sub-lists the search anchored on, of which only a small
    share open a transfer window at all; `windows` counts the records that decoded into one,
    and `incomplete` those that carried a closing time but whose two date groups were missing
    a value or held one outside its range. A decode that has moved leaves `windows` at zero,
    which fails the count check, and one that has moved only inside the date groups pushes
    records from `windows` into `incomplete`, which fails the date-group check.
    """

    markers: int
    windows: int
    incomplete: int


@dataclass(frozen=True, slots=True)
class LeagueTableStats:
    """What building the live league tables counted.

    `blocks` counts the table blocks left after repeated content was dropped, and
    `duplicate_blocks` those dropped: the span stores each block several times over, the copies
    agreeing in every decoded field and differing only in the 19 undecoded head bytes, and
    about 45% of what the span pass finds is such a copy. `block_candidates` counts every
    candidate the span pass judged, accepted or not.

    `groups` counts the tables the kept blocks fall into, split on the index each block stores
    of its own place in its table, and `groups_resolved` those the calendar vote gave a
    competition, with `blocks_in_resolved_groups` the rows they hold. `team_id_in_range` counts
    rows whose team id is inside the layout's range and `team_resolved` those whose team a club
    lists. `double_round_robin_divisions` counts the tables shaped like a division whose clubs
    all play each other twice, which is what collapses if the grouping ever starts running one
    table into the next, since a merged table holds its clubs twice over.
    """

    blocks: int
    duplicate_blocks: int
    block_candidates: int
    groups: int
    groups_resolved: int
    blocks_in_resolved_groups: int
    team_id_in_range: int
    team_resolved: int
    double_round_robin_divisions: int


@dataclass(frozen=True, slots=True)
class RulesStats:
    """What the competition-rules reader counted over the span's preamble blocks.

    `markers` counts the markers the span pass judged and `blocks` the blocks they yielded.
    Every judged marker yields a block, so the two are equal by construction: the marker count
    is the denominator for the share of blocks that parsed, never a rejection rate.

    `fully_parsed` counts the blocks whose promotion quad was written twice identically **and**
    whose tie-break list, prize list and every round record decoded. That is stricter than
    counting only the lists and the rounds, and it therefore holds on a smaller share of blocks
    than a count that ignores the quad; the check that judges it says which of the two it
    means. `quad_doubled` counts the blocks whose quad was doubled, which is the part of that
    conjunction the four promotion fields depend on. `rows` counts the rows the reader returned.
    """

    markers: int
    blocks: int
    fully_parsed: int
    quad_doubled: int
    rows: int


@dataclass(frozen=True, slots=True)
class MatchStats:
    """What the per-match player record search counted over the player region.

    `records` counts every accepted record and `with_body` those the save kept a performance
    body for, which is the denominator of everything a body carries. `players_with_records`
    counts the players at least one record belongs to, and `unowned` the records that lie before
    the first player's window and so belong to none, which the search region puts out of reach:
    it is zero on every save measured and guards against a record ever being credited to the
    wrong player.

    `competition_in_stage_space` counts records whose competition id the stage table names,
    `minutes_in_range` and `rating_in_range` the records with a body whose minutes and stored
    rating are at most the layout's maximum, and `body_valid` those whose whole body is inside
    every one of those bounds. `opponent_resolved` counts records whose opponent team id a club
    lists.
    """

    records: int
    with_body: int
    players_with_records: int
    competition_in_stage_space: int
    minutes_in_range: int
    rating_in_range: int
    body_valid: int
    opponent_resolved: int
    unowned: int


@dataclass(frozen=True, slots=True)
class FinanceStats:
    """What one pass over the club records counted for the finance and sponsorship checks.

    `records_searched` counts the club records long enough to hold a chain, which is where the
    search runs at all, and `clubs_with_series` those that held one; most clubs of a save hold
    none. `clubs_with_two_chains` counts the records where a second chain was accepted behind
    the first, which no save measured holds and which means the locator has started accepting
    bytes it should not.

    `rows` counts every month row returned. `net_identity_rows` counts the rows whose net equals
    total income less total expenditure, and `expenditure_split_rows` those whose expenditure
    excluding transfers lies between zero and the total. `balance_steps` counts consecutive row
    pairs inside one club, and `balance_continuous_steps` those where the later balance is the
    earlier one plus the later month's net.

    `clubs_with_sponsors` counts the clubs with a series that also hold a sponsor run, and
    `sponsor_rows` the rows those runs hold. `managed_club_exists` says whether the save lists a
    managed club, which is what decides whether the series floor applies at all.
    """

    records_searched: int
    clubs_with_series: int
    clubs_with_two_chains: int
    rows: int
    net_identity_rows: int
    balance_steps: int
    balance_continuous_steps: int
    expenditure_split_rows: int
    clubs_with_sponsors: int
    sponsor_rows: int
    managed_club_exists: bool


@dataclass(frozen=True, slots=True)
class ManagedStats:
    """What the managed-club reader found: human managers, resolved routes (0 or 1) and rows."""

    human_count: int
    route_one_resolved: int
    route_two_resolved: int
    rows: int


@dataclass(frozen=True, slots=True)
class InjuryTypeStats:
    """What reading the injury-type name table out of a per-match entry counted.

    `match_entries` counts the per-match entries the save lists, `entries_with_magic_tried`
    those read looking for the table and `entries_without_magic` those read that are not
    per-match files at all. `table_entries` counts the records of the table that was found,
    which is zero on a save that lists no per-match entry and on one whose entries hold no
    table.
    """

    match_entries: int
    entries_with_magic_tried: int
    entries_without_magic: int
    table_entries: int


@dataclass(frozen=True, slots=True)
class AffiliateStats:
    """What the affiliate-group walk and its club join counted.

    `groups` counts the groups the walk consumed, `members` every stored club index they hold,
    and `members_resolved` those a club record claims. A section storing no group leaves all
    three at zero, which is why the resolve share is judged only where there is a member.
    """

    groups: int
    members: int
    members_resolved: int


@dataclass(frozen=True, slots=True)
class JobVacancyStats:
    """What reading the job-centre feed counted.

    `records` counts every record the section holds. `tagged` counts those carrying the record
    tag, and `reserved_zero` those whose two reserved fields are both zero.

    `dates_ordered` counts records whose advertised date decodes and is on or before the save's
    in-game date **and** whose second date decodes and is on or after the advertised one.
    `advertised_steps` counts the moves from one record with a decodable advertised date to the
    next, and `advertised_ascending_steps` those that did not reach an earlier date: the save
    stores the feed in advertised order, so a step backwards is a decode that has moved rather
    than a quirk of the career.

    `competitions_known` counts records naming no competition or one the stage table holds, and
    `teams_resolved` those whose team id a club lists. Neither carries a gate: team ids are
    dense enough over the feed's range that the second cannot fail, and the first is 1.0 both
    read correctly and with the record start shifted four bytes. Both are reported instead.

    `with_competition` counts records that name a competition at all, `with_league_position`
    those storing a position in its table, and `flagged` those whose 0/1 flag is set.
    """

    records: int
    tagged: int
    dates_ordered: int
    advertised_steps: int
    advertised_ascending_steps: int
    reserved_zero: int
    competitions_known: int
    teams_resolved: int
    with_competition: int
    with_league_position: int
    flagged: int
