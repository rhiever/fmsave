"""Reader checks, and the validation report built from them.

While a reader decodes, it counts what it sees into a stats record from `fmsave._reader_stats`
(`PlayerStats`, `ContractStats`, `ClubStats`, `SuspensionStats`, `ManagedStats`, `StageStats`,
`CompetitionStats`, `FixtureStats`, `TransferWindowStats`, `LeagueTableStats`, `RulesStats` or `MatchStats`).
The `evaluate_*` functions compare those counts with the loose `GateBounds` registered for the
save's layout and return one `GateResult` per check, and `enforce` raises `ReaderCheckError`
when an applied check failed, before the reader caches its table. The checks apply only to a
`game_db` of at least `GateBounds.minimum_applies_from_bytes`, since smaller sections come from
fragments that cannot meet full-save counts.

`validate_save` runs every reader and returns a `ValidationReport`, which holds only structural
facts, counts and rates: never names, uids or other values from the save.

Only the names in `__all__` are public. `ReaderCheck`, `GateCheckError`, `_gates_disabled` and
the `evaluate_*`, `check_*` and `enforce*` functions are internal to fmsave.
"""

from __future__ import annotations

import platform
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from statistics import median_low
from typing import TYPE_CHECKING, Literal

from fmsave._context import closed_save_error
from fmsave._errors import ISSUES_URL, FmsaveError, ReaderCheckError
from fmsave._frozen import FrozenMapping
from fmsave._layouts import BoundPair, GateBounds
from fmsave._package import __version__
from fmsave._reader_stats import (
    AffiliateStats,
    ClubStats,
    CompetitionStats,
    ContractStats,
    FinanceStats,
    FixtureStats,
    InjuryTypeStats,
    JobVacancyStats,
    LeagueTableStats,
    ManagedStats,
    MatchStats,
    PlayerStats,
    ResultStats,
    RulesStats,
    StageStats,
    SuspensionStats,
    TransferWindowStats,
)
from fmsave._status import registered_statuses

if TYPE_CHECKING:
    from fmsave._save import Save

__all__ = ["GateResult", "ReaderValidation", "ValidationReport", "validate_save"]

# Internal switch: when False, failed checks are still evaluated and reported but never raised.
_gates_enabled = True


@contextmanager
def _gates_disabled() -> Generator[None]:
    """Evaluate and report checks without raising inside the block, then restore the switch."""
    global _gates_enabled
    previous_setting = _gates_enabled
    _gates_enabled = False
    try:
        yield
    finally:
        _gates_enabled = previous_setting


CLUBS_READER = "clubs"
PLAYERS_READER = "players"
CONTRACTS_READER = "contracts"
SUSPENSIONS_READER = "suspensions"
MANAGED_CLUBS_READER = "managed_clubs"
STAGES_READER = "stages"
COMPETITIONS_READER = "competitions"
FIXTURES_READER = "fixtures"
TRANSFER_WINDOWS_READER = "transfer_windows"
LEAGUE_TABLES_READER = "league_tables"
COMPETITION_RULES_READER = "competition_rules"
PLAYER_MATCH_STATS_READER = "player_match_stats"
INJURY_TYPES_READER = "injury_types"
FINANCES_READER = "finances"
SPONSORSHIPS_READER = "sponsorships"
AFFILIATES_READER = "affiliates"
JOB_VACANCIES_READER = "job_vacancies"

# Several readers are built from one decode. A reader whose shared decode did not finish would
# have every other reader of the same pass redo that decode only to fail the same way, so the
# first failure is carried to the rest of the pass instead of being raised again.
PLAYER_PASS = "player"
SPAN_PASS = "span"
FINANCE_PASS = "finance"
# Players, contracts and suspensions are decoded in one pass, so they fail or succeed together.
_PLAYER_PASS_READERS = frozenset({PLAYERS_READER, CONTRACTS_READER, SUSPENSIONS_READER})
# Fixtures, league tables and competition rules read one streamed pass over the unnamed span,
# which is far the most expensive read fmsave makes.
_SPAN_PASS_READERS = frozenset({FIXTURES_READER, LEAGUE_TABLES_READER, COMPETITION_RULES_READER})
# The months and the sponsors come out of one pass over the club records, so they fail or
# succeed together.
_FINANCE_PASS_READERS = frozenset({FINANCES_READER, SPONSORSHIPS_READER})
_READER_PASSES: FrozenMapping[str, str] = FrozenMapping(
    {
        **dict.fromkeys(_PLAYER_PASS_READERS, PLAYER_PASS),
        **dict.fromkeys(_SPAN_PASS_READERS, SPAN_PASS),
        **dict.fromkeys(_FINANCE_PASS_READERS, FINANCE_PASS),
    }
)

_REPORT_REQUEST = f"Please report it at {ISSUES_URL} with the output of fmsave validate."
_NO_ANOMALIES: FrozenMapping[str, int] = FrozenMapping({})
_NO_COVERAGE: FrozenMapping[str, float] = FrozenMapping({})

# The one likely cause of each check whose failure has one, added to the failure message so a
# report names something a reader can act on. The text carries no digits, so a message still
# holds nothing but rounded rates and bounds.
_LIKELY_CAUSES: FrozenMapping[str, str] = FrozenMapping(
    {
        "tails_without_clause_table": "an unrecognised bonus list shape in the contract tail",
        "suspension_share_of_players": "a suspension entry layout that has moved",
    }
)


@dataclass(frozen=True, slots=True)
class GateResult:
    """One reader check: an observed count or rate compared with its bounds.

    Attributes:
        name: The check's name.
        observed: The observed count, rate or median, or None when a rate has no denominator.
        minimum: The lowest value that passes, or None when there is no lower bound.
        maximum: The highest value that passes, or None when there is no upper bound.
        passed: Whether the check passed; a check that was not applied always passes.
        applied: Whether the check applied: False when `game_db` is too small for full-save
            counts.
    """

    name: str
    observed: float | None
    minimum: float | None
    maximum: float | None
    passed: bool
    applied: bool

    def to_json_dict(self) -> dict[str, object]:
        """The check as a JSON-ready dict."""
        return {
            "name": self.name,
            "observed": self.observed,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "passed": self.passed,
            "applied": self.applied,
        }


@dataclass(frozen=True, slots=True)
class ReaderCheck:
    """One reader's evaluated checks, its record count and its anomaly counts."""

    reader: str
    record_count: int
    gates: tuple[GateResult, ...]
    anomalies: Mapping[str, int]


class GateCheckError(ReaderCheckError):
    """A ReaderCheckError from failed reader checks, carrying every check of the failed pass."""

    checks: tuple[ReaderCheck, ...]

    def __init__(self, message: str, checks: tuple[ReaderCheck, ...] = ()) -> None:
        super().__init__(message)
        self.checks = checks


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _gate(name: str, observed: float | None, bound: BoundPair, applied: bool) -> GateResult:
    minimum, maximum = bound
    if not applied:
        return GateResult(name, observed, minimum, maximum, passed=True, applied=False)
    passed = (
        observed is not None
        and (minimum is None or observed >= minimum)
        and (maximum is None or observed <= maximum)
    )
    return GateResult(name, observed, minimum, maximum, passed=passed, applied=True)


def _applies(bounds: GateBounds, game_db_bytes: int) -> bool:
    return game_db_bytes >= bounds.minimum_applies_from_bytes


def _span_applies(bounds: GateBounds, span_bytes: int) -> bool:
    """Whether checks on what the span pass read apply: the span has its own size threshold."""
    return span_bytes >= bounds.span_minimum_applies_from_bytes


def evaluate_players(
    stats: PlayerStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The player reader's checks, in a fixed order."""
    applied = _applies(bounds, game_db_bytes)
    records = stats.records
    ages = stats.ages
    age_median = median_low(ages) if ages else None
    return (
        _gate("players_minimum", records, bounds.players_minimum, applied),
        _gate(
            "person_blocks",
            _rate(stats.with_person_block, records),
            bounds.person_blocks,
            applied,
        ),
        _gate(
            "names_resolved",
            _rate(stats.with_resolved_name, stats.with_person_block),
            bounds.names_resolved,
            applied,
        ),
        _gate(
            "relation_sentinel",
            _rate(stats.relation_sentinel_ok, stats.relation_entries),
            bounds.relation_sentinel,
            applied,
        ),
        _gate(
            "second_nation_qualifier",
            _rate(stats.second_nation_qualifier_ok, stats.second_nation_entries),
            bounds.second_nation_qualifier,
            applied,
        ),
        _gate(
            "handling_above_finishing",
            _rate(stats.handling_above_finishing, records),
            bounds.handling_above_finishing,
            applied,
        ),
        _gate(
            "outfield_goalkeeper_block_low",
            _rate(stats.outfield_goalkeeper_block_low, stats.outfield_players),
            bounds.outfield_goalkeeper_block_low,
            applied,
        ),
        _gate(
            "with_natural_position",
            _rate(stats.with_natural_position, records),
            bounds.with_natural_position,
            applied,
        ),
        _gate(
            "height_in_range",
            _rate(stats.height_in_range, records),
            bounds.height_in_range,
            applied,
        ),
        _gate("height_median", stats.heights_median, bounds.height_median, applied),
        _gate("age_median", age_median, bounds.age_median, applied),
        _gate(
            "aged_in_range", _rate(stats.aged_in_range, len(ages)), bounds.aged_in_range, applied
        ),
        _gate(
            "condition_sharpness_in_range",
            _rate(stats.condition_sharpness_in_range, records),
            bounds.condition_sharpness_in_range,
            applied,
        ),
        _gate(
            "join_date_valid",
            _rate(stats.with_valid_join_date, records),
            bounds.join_date_valid,
            applied,
        ),
        _gate(
            "world_not_above_current",
            _rate(stats.world_not_above_current, records),
            bounds.world_not_above_current,
            applied,
        ),
        _gate(
            "home_near_current",
            _rate(stats.home_near_current, records),
            bounds.home_near_current,
            applied,
        ),
        _gate(
            "team_resolved",
            _rate(stats.team_resolved, stats.with_team),
            bounds.team_resolved,
            applied,
        ),
        _gate(
            "home_grown_club_refs_resolved",
            _rate(stats.home_grown_club_refs_resolved, stats.home_grown_club_refs),
            bounds.home_grown_club_refs_resolved,
            applied,
        ),
    )


def evaluate_contracts(
    stats: ContractStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The contract reader's checks, in a fixed order."""
    applied = _applies(bounds, game_db_bytes)
    return (
        _gate(
            "players_with_chain",
            _rate(stats.players_with_chain, stats.players),
            bounds.players_with_chain,
            applied,
        ),
        _gate(
            "no_contract_in_effect",
            _rate(stats.without_contract_in_effect, stats.players_with_chain),
            bounds.no_contract_in_effect,
            applied,
        ),
        _gate(
            "date_marked_chain_records",
            _rate(stats.date_marked_chain_records, stats.chain_records),
            bounds.date_marked_chain_records,
            applied,
        ),
        _gate(
            "tails_parsed",
            _rate(stats.tails_parsed, stats.chain_records),
            bounds.tails_parsed,
            applied,
        ),
        _gate(
            "tails_without_clause_table",
            _rate(stats.tails_without_clause_table, stats.tails_parsed),
            bounds.tails_without_clause_table,
            applied,
        ),
        _gate(
            "clause_terminator",
            _rate(stats.clause_tables_ending_at_tail, stats.clause_tables),
            bounds.clause_terminator,
            applied,
        ),
        _gate(
            "contract_head",
            _rate(stats.head_ok, stats.clause_tables),
            bounds.contract_head,
            applied,
        ),
        _gate(
            "past_dated_tail_ends",
            _rate(stats.tail_ends_past, stats.tail_ends),
            bounds.past_dated_tail_ends,
            applied,
        ),
        _gate(
            "chain_teams_resolved",
            _rate(stats.chain_teams_resolved, stats.chain_records),
            bounds.chain_teams_resolved,
            applied,
        ),
    )


def evaluate_clubs(
    stats: ClubStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The club reader's checks, in a fixed order."""
    applied = _applies(bounds, game_db_bytes)
    records = stats.records
    return (
        _gate("clubs_minimum", records, bounds.clubs_minimum, applied),
        _gate(
            "team_lists_found",
            _rate(stats.team_lists_found, records),
            bounds.team_lists_found,
            applied,
        ),
        _gate("status_normal", _rate(stats.status_normal, records), bounds.status_normal, applied),
        _gate(
            "status_confirmation",
            _rate(stats.status_confirmed, stats.status_normal),
            bounds.status_confirmation,
            applied,
        ),
        _gate(
            "affiliate_lists_found",
            _rate(stats.affiliate_lists, records),
            bounds.affiliate_lists_found,
            applied,
        ),
        _gate(
            "affiliate_teams_linked",
            _rate(stats.affiliate_refs_linked, stats.affiliate_refs),
            bounds.affiliate_teams_linked,
            applied and stats.affiliate_refs > 0,
        ),
        _gate(
            "reputation_found",
            _rate(stats.reputation_found, records),
            bounds.reputation_found,
            applied,
        ),
        _gate("reputation_median", stats.reputations_median, bounds.reputation_median, applied),
    )


def evaluate_suspensions(
    stats: SuspensionStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The suspension reader's checks, in a fixed order.

    Both apply whenever the section is large enough, including when the search found no entry
    at all: an empty result scores below the share's lower bound and leaves the clock check
    with no rate, so an entry layout that has moved fails here rather than reporting a save
    whose players are never banned.
    """
    applied = _applies(bounds, game_db_bytes)
    return (
        _gate(
            "suspension_share_of_players",
            _rate(stats.players_with_entries, stats.players),
            bounds.suspension_share_of_players,
            applied,
        ),
        _gate(
            "issued_after_clock",
            _rate(stats.issued_after_clock, stats.entries),
            bounds.issued_after_clock,
            applied,
        ),
    )


def evaluate_stages(
    stats: StageStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The stage reader's checks, in a fixed order."""
    applied = _applies(bounds, game_db_bytes)
    rows = stats.rows
    return (
        _gate("stage_rows_minimum", rows, bounds.stage_rows_minimum, applied),
        _gate("stage_walk_gaps", stats.gaps, bounds.stage_walk_gaps, applied),
        _gate(
            "stage_ids_ascending",
            _rate(stats.ascending_steps, stats.steps),
            bounds.stage_ids_ascending,
            applied,
        ),
        _gate(
            "stage_rows_with_competition",
            _rate(stats.with_competition, rows),
            bounds.stage_rows_with_competition,
            applied,
        ),
        _gate(
            "stage_trailing_sentinel",
            _rate(stats.trailing_sentinel_ok, rows),
            bounds.stage_trailing_sentinel,
            applied,
        ),
        _gate(
            "stage_table_tail_bytes",
            stats.bytes_after_table,
            bounds.stage_table_tail_bytes,
            applied,
        ),
    )


def evaluate_competitions(
    stats: CompetitionStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The competition reader's checks, in a fixed order.

    Nothing bounds how many competitions are named from below: no save stores a competition
    name, so that share is zero until a reader supplies a name map, and zero is not a fault.
    What is checked is that no name reached a competition the save gives no database id, since
    the map is keyed on that id alone. A competition two competitions' records claim, or whose
    database id another competition also claims, is left without one and must stay unnamed;
    naming it anyway would put a different competition's name on it.
    """
    applied = _applies(bounds, game_db_bytes)
    competitions = stats.competitions
    return (
        _gate("competitions_minimum", competitions, bounds.competitions_minimum, applied),
        _gate(
            "competition_database_ids_mapped",
            _rate(stats.with_database_id, competitions),
            bounds.competition_database_ids_mapped,
            applied,
        ),
        _gate(
            "competition_database_id_conflicts",
            _rate(stats.database_id_conflicts, competitions),
            bounds.competition_database_id_conflicts,
            applied,
        ),
        _gate(
            "competition_names_within_database_ids",
            _rate(stats.with_name, stats.with_database_id),
            bounds.competition_names_within_database_ids,
            applied,
        ),
    )


def evaluate_fixtures(
    stats: FixtureStats, bounds: GateBounds, span_bytes: int
) -> tuple[GateResult, ...]:
    """The fixture reader's checks, in a fixed order.

    These judge what one pass over the span read, not `game_db`, so they apply from the span's
    own size threshold. All five apply whenever the span is large enough, including when the
    pass found no fixture at all: an empty calendar scores below the record floor and the
    stray floor and leaves the three shares without a denominator, so a calendar locator that
    has moved fails here rather than reporting a career with no matches.

    `fixture_cluster_share` and `fixture_strays_minimum` bound the same split from opposite
    sides. The share falls when the run separating the calendar from its stray copies is too
    eager and the calendar shatters. The stray floor catches the other way that rule can
    break, a separation so slack that nothing is told apart at all: every record then counts
    as the calendar, which puts the template matches no save plays on every career, and the
    share cannot see it, because a reader keeping every stray copy scores a perfect 1.0.
    """
    applied = _span_applies(bounds, span_bytes)
    cluster_records = stats.cluster_records
    return (
        _gate("fixtures_minimum", cluster_records, bounds.fixtures_minimum, applied),
        _gate(
            "fixture_cluster_share",
            _rate(cluster_records, stats.span_records),
            bounds.fixture_cluster_share,
            applied,
        ),
        _gate(
            "fixture_strays_minimum",
            stats.span_records - cluster_records,
            bounds.fixture_strays_minimum,
            applied,
        ),
        _gate(
            "fixture_stage_resolved",
            _rate(stats.stage_resolved, stats.with_stage),
            bounds.fixture_stage_resolved,
            applied,
        ),
        _gate(
            "fixture_teams_resolved",
            _rate(stats.home_team_resolved + stats.away_team_resolved, 2 * cluster_records),
            bounds.fixture_teams_resolved,
            applied,
        ),
    )


def evaluate_results(
    stats: ResultStats, bounds: GateBounds, span_bytes: int
) -> tuple[GateResult, ...]:
    """The stage-keyed result checks, in a fixed order.

    These judge the same pass over the span the calendar's own checks do, so they apply from
    the span's size threshold. All three apply whenever the span is large enough, including
    when nothing was accepted at all: an empty result scores below the record floor and leaves
    both shares without a denominator, so a locator that has moved fails here rather than
    reporting a career whose matches were never scored.

    `results_joined` is what says the record is still being read correctly. The scores are found
    by one locator and the calendar they join by another, in a different region, so the two
    agree on a date and both team ids only if both are being decoded right; the same records
    joined on a key wrong by one day, or with the two sides swapped, joined nothing at all on
    every save measured. A decode that drifted would keep finding records and stop matching.

    `results_for_unplayed` is the tripwire for the opposite failure, a join loose enough to
    attach scores to matches the calendar says have not been played. That is wrong however many
    of them it finds, and no rate of joining can see it.
    """
    applied = _span_applies(bounds, span_bytes)
    accepted = stats.accepted
    return (
        _gate("result_records_minimum", accepted, bounds.result_records_minimum, applied),
        _gate("results_joined", _rate(stats.joined, accepted), bounds.results_joined, applied),
        _gate(
            "results_for_unplayed",
            _rate(stats.score_for_unplayed, stats.joined),
            bounds.results_for_unplayed,
            applied,
        ),
    )


def evaluate_transfer_windows(
    stats: TransferWindowStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The transfer-window reader's checks, in a fixed order.

    Both apply whenever the section is large enough, including when the walk decoded nothing:
    an empty result scores zero windows, which fails the count, and leaves the date share with
    no denominator at all, which fails for want of a rate rather than passing quietly. That is
    the point of the pair, since the tagged stream holds far more dated records than windows
    and a decode that has moved would otherwise look like a save that simply has none.
    """
    applied = _applies(bounds, game_db_bytes)
    windows = stats.windows
    return (
        _gate("transfer_windows_minimum", windows, bounds.transfer_windows_minimum, applied),
        _gate(
            "transfer_window_dates",
            _rate(windows, windows + stats.incomplete),
            bounds.transfer_window_dates,
            applied,
        ),
    )


def evaluate_league_tables(
    stats: LeagueTableStats, bounds: GateBounds, span_bytes: int
) -> tuple[GateResult, ...]:
    """The league-table reader's checks, in a fixed order.

    These judge what one pass over the span read, so they apply from the span's own size
    threshold. All five apply whenever the span is large enough, including when the pass found
    no block at all: an empty result scores below the block floor, the duplicate floor and the
    division floor, and leaves the two shares without a denominator, so a table layout that has
    moved fails here rather than reporting a career with no tables.

    Two of the five exist to catch a filter that stopped filtering, which no rate here can see.
    `table_block_duplicates_minimum` fails when the deduplication stops dropping the save's
    repeated copies of a block: the copies are sound blocks differing from the block they
    repeat only in undecoded head bytes, so they pass every other check, and left in they
    shatter the tables they sit in, turning about 800 tables into about 4,700 on the corpus.
    That floor is the only check that sees it, because every shattered piece is still shaped
    like a small table; the division count barely moves, so it is not a second tripwire for
    this failure and is not presented as one.
    `double_round_robin_divisions` guards the opposite failure, a grouping that runs tables
    together: a merged group holds clubs twice over and cannot keep a division's shape, so the
    count collapses. `table_groups_resolved` sees neither, since one enormous group scores a
    perfect 1.0 on it.

    `table_groups_resolved` observes near 1.0 on every save measured, which reads stronger than
    it is: 30% to 43% of tables hold a single block, and a one-block table meets the vote's
    half-the-members rule on a majority of one. Over the tables of two blocks or more the share
    is 0.998 to 1.000, so this gate is a floor under a near-saturated rate rather than a
    discriminating one.
    """
    applied = _span_applies(bounds, span_bytes)
    blocks = stats.blocks
    return (
        _gate("table_blocks_minimum", blocks, bounds.table_blocks_minimum, applied),
        _gate(
            "table_block_duplicates_minimum",
            stats.duplicate_blocks,
            bounds.table_block_duplicates_minimum,
            applied,
        ),
        _gate(
            "table_block_team_in_range",
            _rate(stats.team_id_in_range, blocks),
            bounds.table_block_team_in_range,
            applied,
        ),
        _gate(
            "table_groups_resolved",
            _rate(stats.groups_resolved, stats.groups),
            bounds.table_groups_resolved,
            applied,
        ),
        _gate(
            "double_round_robin_divisions",
            stats.double_round_robin_divisions,
            bounds.double_round_robin_divisions,
            applied,
        ),
    )


def evaluate_competition_rules(
    stats: RulesStats, bounds: GateBounds, span_bytes: int
) -> tuple[GateResult, ...]:
    """The competition-rules reader's checks, in a fixed order.

    These judge what one pass over the span read, so they apply from the span's own size
    threshold. Both apply whenever the span is large enough, including when the pass found no
    block at all: an empty result scores no markers, which fails the count, and leaves the
    parsed share with no denominator, which fails for want of a rate rather than passing
    quietly. That is what a marker that has moved looks like from the counts, and it is why the
    share is not allowed to stand alone.

    `rules_fully_parsed` counts the strict sense of a parsed block: the promotion quad written
    twice identically **and** the tie-break list, the prize list and every round record
    decoded. A share measured without the quad sits about ten points higher, so this gate's
    bound is not comparable with one.
    """
    applied = _span_applies(bounds, span_bytes)
    return (
        _gate("rules_markers_minimum", stats.markers, bounds.rules_markers_minimum, applied),
        _gate(
            "rules_fully_parsed",
            _rate(stats.fully_parsed, stats.blocks),
            bounds.rules_fully_parsed,
            applied,
        ),
    )


def check_players(stats: PlayerStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The player reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        PLAYERS_READER,
        stats.records,
        evaluate_players(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "markerless_players": stats.markerless,
                "unresolved_teams": stats.with_team - stats.team_resolved,
            }
        ),
    )


def check_contracts(stats: ContractStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The contract reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        CONTRACTS_READER,
        stats.contracts,
        evaluate_contracts(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "past_dated_tail_ends": stats.tail_ends_past,
                "unparsed_tails": stats.chain_records - stats.tails_parsed,
                "tails_without_clause_table": stats.tails_without_clause_table,
                "date_marked_chain_records": stats.date_marked_chain_records,
                "players_without_contract_in_effect": stats.without_contract_in_effect,
            }
        ),
    )


def check_clubs(stats: ClubStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The club reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        CLUBS_READER,
        stats.records,
        evaluate_clubs(stats, bounds, game_db_bytes),
        FrozenMapping(
            {"unlinked_affiliate_teams": stats.affiliate_refs - stats.affiliate_refs_linked}
        ),
    )


def check_suspensions(
    stats: SuspensionStats, bounds: GateBounds, game_db_bytes: int
) -> ReaderCheck:
    """The suspension reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        SUSPENSIONS_READER,
        stats.entries,
        evaluate_suspensions(stats, bounds, game_db_bytes),
        FrozenMapping({"suspensions_after_clock": stats.issued_after_clock}),
    )


def check_managed(stats: ManagedStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The managed-club reader's record count and anomaly counts.

    This reader has no checks. A manager between jobs legitimately has no club, so no count
    or share it produces can carry a bound that a save between jobs would not fail as well,
    and a check that can never fail is worse than none at all. What guards it sits in the
    reader instead: it raises when its two routes to the club disagree. A route that resolved
    nothing is reported here as an anomaly.
    """
    humans_without_club = 1 if stats.human_count >= 1 and stats.rows == 0 else 0
    return ReaderCheck(
        MANAGED_CLUBS_READER,
        stats.rows,
        (),
        FrozenMapping(
            {
                "humans_without_club": humans_without_club,
                "club_route_one_unresolved": 1 - stats.route_one_resolved,
                "club_route_two_unresolved": 1 - stats.route_two_resolved,
            }
        ),
    )


def check_stages(stats: StageStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The stage reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        STAGES_READER,
        stats.rows,
        evaluate_stages(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "walk_gaps": stats.gaps,
                "rejected_competition_ids": stats.competition_id_rejected,
            }
        ),
    )


def check_competitions(
    stats: CompetitionStats, bounds: GateBounds, game_db_bytes: int
) -> ReaderCheck:
    """The competition reader's checks, record count and anomaly counts."""
    return ReaderCheck(
        COMPETITIONS_READER,
        stats.competitions,
        evaluate_competitions(stats, bounds, game_db_bytes),
        FrozenMapping({"database_id_conflicts": stats.database_id_conflicts}),
    )


def check_fixtures(
    stats: FixtureStats, result_stats: ResultStats, bounds: GateBounds, span_bytes: int
) -> ReaderCheck:
    """The fixture reader's checks, record count and anomaly counts.

    The scores are fields of a fixture rather than a table of their own, so the result checks
    are reported here beside the calendar's, and the two sets of counts are kept apart: the
    calendar's own gates never see a result count, and the result gates never see a fixture
    count.

    `stray_records` and `stray_clusters` count what the span held outside the calendar, which
    every save carries some of, and `strays_without_a_copy` those of them the calendar holds
    no copy of, which is the only part of the drop that loses anything. The rest count kept
    fixtures a join or a decode left incomplete. `neutral_venue_votes` counts the clubs and
    seasons whose usual ground was decided: none of them on a full-size span means the venue
    vote never ran at all.

    `unjoined_results` counts the score records that named no match in this calendar, which is
    most of what a save holds: several seasons of history whose fixtures are long gone.
    `ambiguous_results` counts those naming more than one fixture at once, which fill none of
    them. `score_disagreements` counts matches two records gave two different scores, which no
    save measured has held, and `scored_fixtures` the played matches that ended up carrying a
    score, about a quarter of them.
    """
    cluster_records = stats.cluster_records
    return ReaderCheck(
        FIXTURES_READER,
        cluster_records,
        evaluate_fixtures(stats, bounds, span_bytes)
        + evaluate_results(result_stats, bounds, span_bytes),
        FrozenMapping(
            {
                "stray_records": stats.span_records - cluster_records,
                "stray_clusters": max(stats.clusters - 1, 0),
                "strays_without_a_copy": stats.strays_without_a_copy,
                "fixtures_without_a_stage": cluster_records - stats.with_stage,
                "unresolved_stages": stats.with_stage - stats.stage_resolved,
                "unresolved_teams": (
                    2 * cluster_records - stats.home_team_resolved - stats.away_team_resolved
                ),
                "undated_fixtures": stats.undated,
                "bad_kick_off_slots": stats.bad_kick_off_slots,
                "neutral_venue_votes": stats.neutral_venue_votes,
                "unjoined_results": result_stats.unjoined,
                "ambiguous_results": result_stats.ambiguous,
                "score_disagreements": result_stats.score_disagreements,
                "scored_fixtures": result_stats.scored_fixtures,
            }
        ),
    )


def check_transfer_windows(
    stats: TransferWindowStats, bounds: GateBounds, game_db_bytes: int
) -> ReaderCheck:
    """The transfer-window reader's checks, record count and anomaly counts.

    The anomaly is the candidates the walk looked at and rejected for carrying no closing
    time, which is most of them: the date tags a window uses are shared by many records of the
    tagged stream, and only the closing time marks one as a window.
    """
    return ReaderCheck(
        TRANSFER_WINDOWS_READER,
        stats.windows,
        evaluate_transfer_windows(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "dated_records_without_a_closing_time": (
                    stats.markers - stats.windows - stats.incomplete
                ),
                "windows_with_unreadable_dates": stats.incomplete,
            }
        ),
    )


def check_league_tables(
    stats: LeagueTableStats, bounds: GateBounds, span_bytes: int
) -> ReaderCheck:
    """The league-table reader's checks, record count and anomaly counts.

    `duplicate_blocks` counts the repeated copies the span holds of a block already kept, which
    is about 45% of everything the span pass finds and is the reader's largest single
    correction. `rejected_block_candidates` counts the candidates the span pass judged and
    turned down. The rest count what the grouping and the joins left incomplete:
    `unresolved_groups` groups the calendar vote could not name, `blocks_outside_resolved_groups`
    the rows those groups hold, and the two team counts the rows whose team id is out of range
    or belongs to no club the save lists.
    """
    return ReaderCheck(
        LEAGUE_TABLES_READER,
        stats.groups,
        evaluate_league_tables(stats, bounds, span_bytes),
        FrozenMapping(
            {
                "duplicate_blocks": stats.duplicate_blocks,
                "rejected_block_candidates": (
                    stats.block_candidates - stats.blocks - stats.duplicate_blocks
                ),
                "unresolved_groups": stats.groups - stats.groups_resolved,
                "blocks_outside_resolved_groups": stats.blocks - stats.blocks_in_resolved_groups,
                "team_ids_out_of_range": stats.blocks - stats.team_id_in_range,
                "unresolved_teams": stats.blocks - stats.team_resolved,
            }
        ),
    )


def check_competition_rules(stats: RulesStats, bounds: GateBounds, span_bytes: int) -> ReaderCheck:
    """The competition-rules reader's checks, record count and anomaly counts.

    The anomalies count the two ways a block falls short of a full decode, which are reported
    rather than dropped: a block whose quad was not doubled still ships its lists and its
    calendar with the four quad fields empty, and a block whose lists or rounds did not decode
    still ships whatever did.
    """
    return ReaderCheck(
        COMPETITION_RULES_READER,
        stats.rows,
        evaluate_competition_rules(stats, bounds, span_bytes),
        FrozenMapping(
            {
                "blocks_not_fully_parsed": stats.blocks - stats.fully_parsed,
                "blocks_without_a_doubled_quad": stats.blocks - stats.quad_doubled,
            }
        ),
    )


def evaluate_player_match_stats(
    stats: MatchStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The per-match player stats reader's checks, in a fixed order.

    There is deliberately no count check. The search is held to a window of years around the
    save's own clock, so how many records it finds moves with that window and with how long the
    career has run; no bound on it could tell a record layout that has moved from a career that
    has simply played fewer matches. Each record's shape is checked instead, which does tell
    them apart: a record read from the wrong offset carries a competition id the stage table
    never names, and minutes and a rating that can land anywhere at all.

    All three apply whenever the section is large enough, including when the search found
    nothing: an empty result leaves every one of them without a denominator, which fails rather
    than passes, so a layout that has moved fails here rather than reporting a career whose
    players have played no matches.
    """
    applied = _applies(bounds, game_db_bytes)
    with_body = stats.with_body
    return (
        _gate(
            "per_match_competition_in_stage_space",
            _rate(stats.competition_in_stage_space, stats.records),
            bounds.per_match_competition_in_stage_space,
            applied,
        ),
        _gate(
            "per_match_minutes_in_range",
            _rate(stats.minutes_in_range, with_body),
            bounds.per_match_minutes_in_range,
            applied,
        ),
        _gate(
            "per_match_rating_in_range",
            _rate(stats.rating_in_range, with_body),
            bounds.per_match_rating_in_range,
            applied,
        ),
    )


def check_player_match_stats(
    stats: MatchStats, bounds: GateBounds, game_db_bytes: int
) -> ReaderCheck:
    """The per-match player stats reader's checks, record count and anomaly counts.

    `records_without_a_body` counts the matches the save keeps no performance body for, which is
    about two records in five on every save and is ordinary rather than a fault. The rest count
    what a join or a bound left unsatisfied: opponents no club lists, competition ids the stage
    table does not name, bodies holding a number no match can reach, and records lying before
    the first player's window, which belong to no player and build no row.
    """
    records = stats.records
    return ReaderCheck(
        PLAYER_MATCH_STATS_READER,
        records,
        evaluate_player_match_stats(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "records_without_a_body": records - stats.with_body,
                "unresolved_opponents": records - stats.opponent_resolved,
                "competitions_outside_the_stage_table": (
                    records - stats.competition_in_stage_space
                ),
                "bodies_outside_their_ranges": stats.with_body - stats.body_valid,
                "records_without_an_owner": stats.unowned,
            }
        ),
    )


def evaluate_injury_types(
    stats: InjuryTypeStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The injury-type reader's one check.

    It applies on a full-size save that lists at least one per-match entry. A save that lists
    none holds these names nowhere at all, so its empty table is a fact about the save rather
    than a layout that has moved, and the check is reported as not applied instead of failing.
    """
    applied = _applies(bounds, game_db_bytes) and stats.match_entries >= 1
    return (
        _gate(
            "injury_type_entries_minimum",
            stats.table_entries,
            bounds.injury_type_entries_minimum,
            applied,
        ),
    )


def check_injury_types(
    stats: InjuryTypeStats, bounds: GateBounds, game_db_bytes: int
) -> ReaderCheck:
    """The injury-type reader's check, record count and anomaly counts.

    The anomalies say how much of the save was reached: how many per-match entries it lists at
    all, how many of those read are not per-match files, and how many were read looking for the
    table. A save listing none reports zero entries, which is how an empty table is told from a
    table that failed to decode.
    """
    return ReaderCheck(
        INJURY_TYPES_READER,
        stats.table_entries,
        evaluate_injury_types(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "match_entries": stats.match_entries,
                "entries_without_magic": stats.entries_without_magic,
                "entries_tried": stats.entries_with_magic_tried,
            }
        ),
    )


def evaluate_finances(
    stats: FinanceStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The finance reader's checks, in a fixed order.

    The three shares judge the rows that were decoded, so each applies only where it has a
    denominator: a save whose clubs keep no series at all is a save with nothing to judge, not a
    broken decode. Only the clubs of the one or two league nations a save tracks keep a series,
    and which nations those are changes during a career, so an empty result has to be allowed.

    The series floor is what catches a locator that has stopped finding chains, and it applies
    only where the save lists a managed club, whose own club held a series on every save
    measured. That leaves one hole, deliberately: on a save with no human manager a locator
    finding nothing returns an empty table and raises nothing. No count of club records could
    close it without failing a save that legitimately tracks no league nation the manager is in,
    and `clubs_with_series` and `records_searched` are reported as anomalies either way.
    """
    applied = _applies(bounds, game_db_bytes)
    rows = stats.rows
    return (
        _gate(
            "finance_net_identity",
            _rate(stats.net_identity_rows, rows),
            bounds.finance_net_identity,
            applied and rows > 0,
        ),
        _gate(
            "finance_balance_continuity",
            _rate(stats.balance_continuous_steps, stats.balance_steps),
            bounds.finance_balance_continuity,
            applied and stats.balance_steps > 0,
        ),
        _gate(
            "finance_expenditure_split",
            _rate(stats.expenditure_split_rows, rows),
            bounds.finance_expenditure_split,
            applied and rows > 0,
        ),
        _gate(
            "finance_clubs_with_two_chains",
            stats.clubs_with_two_chains,
            bounds.finance_clubs_with_two_chains,
            applied,
        ),
        _gate(
            "finance_series_minimum",
            stats.clubs_with_series,
            bounds.finance_series_minimum,
            applied and stats.managed_club_exists,
        ),
    )


def evaluate_sponsorships(
    stats: FinanceStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The sponsorship reader's one check.

    It judges the clubs that have a series, so it applies only where there is one of those to
    judge: a save whose clubs keep no series has no sponsor run to miss. Where clubs do have a
    series, every one of them had a sponsor run on each save measured, so a sponsor search that
    has moved fails here.
    """
    applied = _applies(bounds, game_db_bytes)
    return (
        _gate(
            "finance_clubs_with_sponsors",
            _rate(stats.clubs_with_sponsors, stats.clubs_with_series),
            bounds.finance_clubs_with_sponsors,
            applied and stats.clubs_with_series > 0,
        ),
    )


def evaluate_affiliates(
    stats: AffiliateStats, bounds: GateBounds, game_db_bytes: int
) -> tuple[GateResult, ...]:
    """The affiliate-group reader's one check.

    It applies on a full-size save whose section stores at least one group member. A section
    storing no group has no member to resolve, and an empty population is a fact about the save
    rather than a layout that has moved, so the check is reported as not applied instead of
    failing for want of a rate. What the walk itself cannot do is end quietly on the wrong
    bytes: it has to consume exactly the groups the header claims and stop on the section's last
    byte, and it raises when it does not.

    What this check judges is the index space rather than the walk. The stored values are club
    indexes exactly as they are, and reading them one higher still resolves most of them,
    because the index is dense: the share falls only to about 0.86, which is below both the
    floor and the 0.91 a random index of this range would reach by chance.
    """
    applied = _applies(bounds, game_db_bytes) and stats.members > 0
    return (
        _gate(
            "affiliate_members_resolved",
            _rate(stats.members_resolved, stats.members),
            bounds.affiliate_members_resolved,
            applied,
        ),
    )


def check_affiliates(stats: AffiliateStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The affiliate-group reader's check, record count and anomaly counts.

    The anomaly counts the members whose stored club index no club record claims, which every
    save measured carries a handful of: those indexes fall in gaps of the index rather than
    naming another club.
    """
    return ReaderCheck(
        AFFILIATES_READER,
        stats.groups,
        evaluate_affiliates(stats, bounds, game_db_bytes),
        FrozenMapping({"unresolved_members": stats.members - stats.members_resolved}),
    )


def evaluate_job_vacancies(stats: JobVacancyStats, bounds: GateBounds) -> tuple[GateResult, ...]:
    """The job-vacancy reader's checks, in a fixed order.

    They judge a section of a few kilobytes rather than `game_db`, so they apply from a record
    count instead of a section size: a feed of fewer than
    `GateBounds.job_vacancy_minimum_applies_from_records` records, an empty one included, is a
    fact about a career rather than a layout that has moved. The feed is career state, it keeps
    vacancies years old, and a manager between jobs may see very little of it, so **no floor is
    put under its size at all** and no share is judged on a handful of rows.

    That leaves a hole a share cannot close: a locator reading the wrong section would return an
    empty table and apply nothing. What closes it is structural rather than statistical, and it
    sits in the reader: the section's size has to be its header plus its record size times the
    stored count, exactly, and nothing else about the feed can satisfy that. It is also the one
    test a start shifted by a whole record fails, since every share below then passes on the
    next record's bytes.

    `job_vacancy_advertised_ascending` is judged on the steps between records whose advertised
    date decodes, not on the records, and it is deliberately **not** excused when there are no
    such steps. A feed of twenty records or more from which not one date decodes is what a
    decode read one byte out looks like, so it fails there for want of a rate.

    Two counted shares carry no gate. Team ids resolve on 0.93 to 0.98 of records, but ids are
    about 92% dense over the range the feed uses, so no floor could separate a sound decode from
    a wrong one. Competition ids the stage table names are 1.0 of records read correctly and
    also 1.0 with the record start shifted four bytes on all three saves measured, so that share
    cannot fail either. Both are reported as counts instead.
    """
    records = stats.records
    applied = records >= bounds.job_vacancy_minimum_applies_from_records
    return (
        _gate("job_vacancy_tag", _rate(stats.tagged, records), bounds.job_vacancy_tag, applied),
        _gate(
            "job_vacancy_dates_ordered",
            _rate(stats.dates_ordered, records),
            bounds.job_vacancy_dates_ordered,
            applied,
        ),
        _gate(
            "job_vacancy_advertised_ascending",
            _rate(stats.advertised_ascending_steps, stats.advertised_steps),
            bounds.job_vacancy_advertised_ascending,
            applied,
        ),
        _gate(
            "job_vacancy_reserved_zero",
            _rate(stats.reserved_zero, records),
            bounds.job_vacancy_reserved_zero,
            applied,
        ),
    )


def check_finances(stats: FinanceStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The finance reader's checks, record count and anomaly counts.

    `clubs_with_series` is reported as an anomaly because it is career state rather than a
    fault: a save tracks one or two league nations, and only their clubs keep a series at all.
    `balance_breaks` counts the consecutive months whose balance step differs from the month's
    net, which every save holds some of, clustered in the transfer-window months.
    """
    return ReaderCheck(
        FINANCES_READER,
        stats.rows,
        evaluate_finances(stats, bounds, game_db_bytes),
        FrozenMapping(
            {
                "clubs_with_series": stats.clubs_with_series,
                "balance_breaks": stats.balance_steps - stats.balance_continuous_steps,
            }
        ),
    )


def check_job_vacancies(stats: JobVacancyStats, bounds: GateBounds) -> ReaderCheck:
    """The job-vacancy reader's checks, record count and anomaly counts.

    `unresolved_teams` counts the vacancies whose team id no club lists, a handful on every
    save. `competitions_outside_the_competition_table` counts those naming a competition the
    stage table does not, which carries no gate and is reported here instead.
    `without_competition` and `without_league_position` count the rows the save simply stores
    nothing in those fields for, about a quarter of them for the position, and `flagged` the
    rows whose unnamed 0/1 flag is set.
    """
    records = stats.records
    return ReaderCheck(
        JOB_VACANCIES_READER,
        records,
        evaluate_job_vacancies(stats, bounds),
        FrozenMapping(
            {
                "unresolved_teams": records - stats.teams_resolved,
                "competitions_outside_the_competition_table": records - stats.competitions_known,
                "without_competition": records - stats.with_competition,
                "without_league_position": records - stats.with_league_position,
                "flagged": stats.flagged,
            }
        ),
    )


def check_sponsorships(stats: FinanceStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    """The sponsorship reader's check, record count and anomaly count."""
    return ReaderCheck(
        SPONSORSHIPS_READER,
        stats.sponsor_rows,
        evaluate_sponsorships(stats, bounds, game_db_bytes),
        FrozenMapping(
            {"clubs_without_sponsors": stats.clubs_with_series - stats.clubs_with_sponsors}
        ),
    )


def _format_number(value: float | None) -> str:
    if value is None:
        return "none"
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return repr(rounded)


def _format_bound(value: float | None) -> str:
    return "" if value is None else _format_number(value)


def _likely_cause(gate_name: str) -> str:
    """ "; likely <cause>" for a check whose failure has one likely cause, else ""."""
    cause = _LIKELY_CAUSES.get(gate_name)
    return "" if cause is None else f"; likely {cause}"


def _failure_summary(reader_name: str, results: Sequence[GateResult]) -> str | None:
    """ "<reader> failed checks: <gate>=<observed> (expected <min>..<max>); ...", or None."""
    failures = [
        f"{result.name}={_format_number(result.observed)} "
        f"(expected {_format_bound(result.minimum)}..{_format_bound(result.maximum)}"
        f"{_likely_cause(result.name)})"
        for result in results
        if result.applied and not result.passed
    ]
    if not failures:
        return None
    return f"{reader_name} failed checks: {'; '.join(failures)}"


def enforce(reader_name: str, results: Sequence[GateResult]) -> None:
    """Raise when any applied check failed. The message holds only rounded rates and bounds.

    Raises:
        ReaderCheckError: An applied check failed.
    """
    summary = _failure_summary(reader_name, results)
    if summary is not None and _gates_enabled:
        raise GateCheckError(f"{summary}. {_REPORT_REQUEST}")


def enforce_checks(reader_checks: Sequence[ReaderCheck]) -> None:
    """Raise when any applied check of any of these readers failed, naming each failed reader.

    The error carries every one of the readers' checks, so a report can show them.

    Raises:
        ReaderCheckError: An applied check failed.
    """
    summaries = [
        summary
        for reader_check in reader_checks
        if (summary := _failure_summary(reader_check.reader, reader_check.gates)) is not None
    ]
    if summaries and _gates_enabled:
        raise GateCheckError(f"{'. '.join(summaries)}. {_REPORT_REQUEST}", tuple(reader_checks))


type ReaderStatus = Literal["ok", "failed", "error"]


@dataclass(frozen=True, slots=True)
class ReaderValidation:
    """How one reader fared in `validate_save`.

    Players, contracts and suspensions are decoded in one pass. When a check of any of the three
    fails, all three are reported "failed" and none of their tables is read, and each of them
    still lists its own gates: a reader can be "failed" while every one of its own gates
    passed. Fixtures, league tables and competition rules share the one streamed pass over the
    span the same way, and are reported together when that pass itself is what failed.

    Attributes:
        reader: The reader: "clubs", "players", "contracts", "suspensions", "managed_clubs",
            "stages", "competitions", "fixtures", "league_tables", "transfer_windows",
            "competition_rules" or "player_match_stats".
        status: "ok" when the reader returned its table, "failed" when checks stopped it, and
            "error" when it raised another fmsave error.
        record_count: How many records the reader decoded, or None when it did not get far
            enough to count them.
        gates: The reader's checks, in a fixed order; empty when the reader has no checks of
            its own, as the managed-club reader does not, or when it did not get far enough.
        coverage: The table's coverage (the share of non-None values per column); empty
            unless the status is "ok".
        anomalies: Counts of records the reader decoded but flags, such as unresolved teams.
    """

    reader: str
    status: ReaderStatus
    record_count: int | None
    gates: tuple[GateResult, ...]
    coverage: Mapping[str, float]
    anomalies: Mapping[str, int]

    def to_json_dict(self) -> dict[str, object]:
        """The reader's outcome as a JSON-ready dict."""
        return {
            "reader": self.reader,
            "status": self.status,
            "record_count": self.record_count,
            "gates": [gate.to_json_dict() for gate in self.gates],
            "coverage": dict(self.coverage),
            "anomalies": dict(self.anomalies),
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """What `validate_save` found, holding no names, uids or other values from the save.

    Attributes:
        fmsave_version: The fmsave version.
        python_version: The Python version.
        os: The operating system name, for example "Linux".
        game: Game edition, for example "FM26".
        build: Version and build that last wrote the save.
        known_build: Whether fmsave has layout tables for this build.
        section_schemas: Schema number of every named section.
        readers: Each reader's outcome, in the order they ran.
        field_statuses: Whether each public field's meaning is "verified" or "unconfirmed".
    """

    fmsave_version: str
    python_version: str
    os: str
    game: str
    build: str
    known_build: bool
    section_schemas: Mapping[str, int]
    readers: tuple[ReaderValidation, ...]
    field_statuses: Mapping[str, str]

    def to_json_dict(self) -> dict[str, object]:
        """The report as a JSON-ready dict."""
        return {
            "fmsave_version": self.fmsave_version,
            "python_version": self.python_version,
            "os": self.os,
            "game": self.game,
            "build": self.build,
            "known_build": self.known_build,
            "section_schemas": dict(self.section_schemas),
            "readers": [reader.to_json_dict() for reader in self.readers],
            "field_statuses": dict(self.field_statuses),
        }


def _unsuccessful_validation(reader_name: str, error: FmsaveError) -> ReaderValidation:
    if not isinstance(error, ReaderCheckError):
        return ReaderValidation(reader_name, "error", None, (), _NO_COVERAGE, _NO_ANOMALIES)
    carried_checks = error.checks if isinstance(error, GateCheckError) else ()
    for reader_check in carried_checks:
        if reader_check.reader == reader_name:
            return ReaderValidation(
                reader_name,
                "failed",
                reader_check.record_count,
                reader_check.gates,
                _NO_COVERAGE,
                reader_check.anomalies,
            )
    return ReaderValidation(reader_name, "failed", None, (), _NO_COVERAGE, _NO_ANOMALIES)


def validate_save(career_save: Save) -> ValidationReport:
    """Run every reader on a save and report how each fared.

    Readers run in the order clubs, players, contracts, suspensions, managed clubs, stages,
    competitions, fixtures, league tables, transfer windows, competition rules, per-match
    player stats. A reader whose checks fail is reported "failed" with its checks, and one
    that raises another fmsave error
    is reported "error" without the error's text; the remaining readers still run. The report
    holds only structural facts, counts and rates, never names, uids or other values from the
    save.

    Some readers share one decode: the players, contracts and suspensions of the player pass,
    and the fixtures, league tables and competition rules built from the one streamed pass over
    the span. When that shared decode is what failed, its error is reported for every reader of
    the pass and the decode is not attempted again, so the span is streamed once however many of
    its readers report it. A reader that failed after its pass had been decoded failed on its
    own, and the others still run.

    Raises:
        SaveClosedError: The save is closed.
    """
    if career_save.closed:
        raise closed_save_error()
    save_info = career_save.info
    reader_tables = (
        (CLUBS_READER, career_save.clubs),
        (PLAYERS_READER, career_save.players),
        (CONTRACTS_READER, career_save.contracts),
        (SUSPENSIONS_READER, career_save.suspensions),
        (MANAGED_CLUBS_READER, career_save.managed_clubs),
        (STAGES_READER, career_save.stages),
        (COMPETITIONS_READER, career_save.competitions),
        (FIXTURES_READER, career_save.fixtures),
        (LEAGUE_TABLES_READER, career_save.league_tables),
        (TRANSFER_WINDOWS_READER, career_save.transfer_windows),
        (COMPETITION_RULES_READER, career_save.competition_rules),
        (PLAYER_MATCH_STATS_READER, career_save.player_match_stats),
    )
    validations: list[ReaderValidation] = []
    failed_passes: dict[str, FmsaveError] = {}
    for reader_name, read_table in reader_tables:
        shared_pass = _READER_PASSES.get(reader_name)
        carried_error = None if shared_pass is None else failed_passes.get(shared_pass)
        if carried_error is not None:
            # The shared decode would run again only to raise the same error.
            validations.append(_unsuccessful_validation(reader_name, carried_error))
            continue
        try:
            table = read_table()
        except FmsaveError as error:
            # Only a failure of the shared decode itself is carried to the rest of its pass.
            # A reader that raised after that decode was kept failed on its own account: the
            # decode is cached, so the readers after it repeat none of it, and reporting them
            # failed would call a table unreadable that reads perfectly well. This is narrow on
            # purpose, and widening it to carry every failure of any reader of a pass would not
            # be the safe direction: it would report the competition rules unreadable because
            # the league tables missed a gate, which is a different wrong answer rather than a
            # cautious one. The span is still streamed once, because the case that costs a
            # second streaming is the one where nothing was cached, which is the case carried.
            if shared_pass is not None and not career_save._shared_pass_cached(shared_pass):  # pyright: ignore[reportPrivateUsage]
                failed_passes[shared_pass] = error
            validations.append(_unsuccessful_validation(reader_name, error))
            continue
        reader_check = career_save._reader_check(reader_name)  # pyright: ignore[reportPrivateUsage]
        validations.append(
            ReaderValidation(
                reader_name,
                "ok",
                len(table),
                () if reader_check is None else reader_check.gates,
                table.coverage,
                _NO_ANOMALIES if reader_check is None else reader_check.anomalies,
            )
        )
    return ValidationReport(
        fmsave_version=__version__,
        python_version=platform.python_version(),
        os=platform.system(),
        game=save_info.game,
        build=save_info.build,
        known_build=save_info.known_build,
        section_schemas=FrozenMapping(save_info.section_schemas),
        readers=tuple(validations),
        field_statuses=registered_statuses(),
    )
