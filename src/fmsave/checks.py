"""Reader checks, and the validation report built from them.

While a reader decodes, it counts what it sees into a stats record from `fmsave._reader_stats`
(`PlayerStats`, `ContractStats`, `ClubStats`, `SuspensionStats`, `ManagedStats`, `StageStats` or
`CompetitionStats`). The `evaluate_*` functions compare those counts with the loose `GateBounds`
registered for the save's layout and return one `GateResult` per check, and `enforce` raises
`ReaderCheckError` when an applied check failed, before the reader caches its table. The checks
apply only to a `game_db` of at least `GateBounds.minimum_applies_from_bytes`, since smaller
sections come from fragments that cannot meet full-save counts.

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
    ClubStats,
    CompetitionStats,
    ContractStats,
    ManagedStats,
    PlayerStats,
    StageStats,
    SuspensionStats,
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

# Players, contracts and suspensions are decoded in one pass, so they fail or succeed together.
_PLAYER_PASS_READERS = frozenset({PLAYERS_READER, CONTRACTS_READER, SUSPENSIONS_READER})

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
    passed.

    Attributes:
        reader: The reader: "clubs", "players", "contracts", "suspensions", "managed_clubs",
            "stages" or "competitions".
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
    competitions. A reader
    whose checks fail is reported "failed" with its checks, and one that raises another fmsave
    error is reported "error" without the error's text; the remaining readers still run. The
    report holds only structural facts, counts and rates, never names, uids or other values
    from the save.

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
    )
    validations: list[ReaderValidation] = []
    player_pass_error: FmsaveError | None = None
    for reader_name, read_table in reader_tables:
        shares_player_pass = reader_name in _PLAYER_PASS_READERS
        if shares_player_pass and player_pass_error is not None:
            # The shared pass would decode everything again only to raise the same error.
            validations.append(_unsuccessful_validation(reader_name, player_pass_error))
            continue
        try:
            table = read_table()
        except FmsaveError as error:
            if shares_player_pass:
                player_pass_error = error
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
