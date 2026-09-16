"""Corpus checks for the player, contract, suspension, club and managed-club readers.

Values read from a save never appear in an assert or a message: each check reduces to a
boolean or to a count of records that broke an invariant, and failures are reported by file
name and check name only.

Every check here is structural. Record counts and reader check values are compared with the
ranges recorded beside the corpus, so a decode that quietly starts finding fewer records, or
one whose shares drift, fails even while each individual record still looks plausible.
"""

from __future__ import annotations

import statistics
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import fmsave
import tests.conftest as corpus_conftest
from fmsave.models.contracts import ClauseKind
from tests.corpus.reporting import CorpusMismatches

pytestmark = [pytest.mark.corpus]

MINIMUM_SUMMARY_STRINGS = 10
MINIMUM_NAME_COVERAGE = 0.995
RECORD_COUNT_TOLERANCE = 0.01
GATE_VALUE_TOLERANCE = 0.05
COVERAGE_DROP_ALLOWED = 0.005
# A rating of 18 or more in goal marks a natural goalkeeper, as the reader checks use.
NATURAL_GOALKEEPER_RATING = 18
# Goalkeeping attributes separate the two groups by far more than this on the 1 to 20 scale.
GOALKEEPER_HANDLING_MARGIN = 5
BASELINES_FOLDER = "baselines"
EXPECTED_READERS = (
    "clubs",
    "players",
    "contracts",
    "suspensions",
    "managed_clubs",
    "stages",
    "competitions",
    "fixtures",
    "league_tables",
    "transfer_windows",
    "competition_rules",
    "player_match_stats",
)
# Readers whose ranges the recorded baselines do not hold yet. The baselines are written by a
# separate tool against the whole corpus, so a reader added since they were last written has no
# range to be compared with, and its own checks are what bound it until they are written again.
READERS_WITHOUT_RECORDED_RANGES = frozenset({"player_match_stats"})


def save_label(relative_name: str) -> str:
    """The save's file name, which is all a failure message may name it by."""
    return Path(relative_name).name


def baseline_for(relative_name: str) -> dict[str, Any] | None:
    """The recorded reader ranges for a save, or None when none have been recorded."""
    baseline_path = (
        corpus_conftest.corpus_root() / BASELINES_FOLDER / f"{Path(relative_name).stem}.json"
    )
    if not baseline_path.is_file():
        return None
    return corpus_conftest.load_json_object(baseline_path)


def within_tolerance(observed: float, expected: float, tolerance: float) -> bool:
    """Whether observed is within a relative tolerance of expected, treating 0 as exact."""
    if expected == 0:
        return observed == 0
    return abs(observed - expected) <= abs(expected) * tolerance


@pytest.mark.corpus_full
def test_validation_reports_every_reader_ok(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Every reader returns its table, and every check that applies passes."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        report = fmsave.validate_save(career_save)
        reported_readers = tuple(reader.reader for reader in report.readers)
        mismatches.check(label, "reader list", reported_readers == EXPECTED_READERS)
        for reader in report.readers:
            mismatches.check(label, f"{reader.reader} status ok", reader.status == "ok")
            for gate in reader.gates:
                mismatches.check(label, f"{reader.reader} gate {gate.name} applied", gate.applied)
                mismatches.check(label, f"{reader.reader} gate {gate.name} passed", gate.passed)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_reader_counts_and_checks_stay_in_their_recorded_ranges(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Record counts, check values and coverage stay where they were last recorded.

    A save whose recorded ranges are missing is left alone; the checks themselves still
    bound every reader.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        baseline = baseline_for(relative_name)
        if baseline is None:
            continue
        recorded_readers = baseline.get("readers")
        if not isinstance(recorded_readers, dict):
            mismatches.note(f"{label}: recorded ranges hold no readers")
            continue
        report = fmsave.validate_save(career_save)
        for reader in report.readers:
            recorded_reader: Any = recorded_readers.get(reader.reader)
            if not isinstance(recorded_reader, dict):
                if reader.reader not in READERS_WITHOUT_RECORDED_RANGES:
                    mismatches.note(f"{label}: {reader.reader} has no recorded range")
                continue
            recorded_count = recorded_reader.get("record_count")
            if isinstance(recorded_count, int) and reader.record_count is not None:
                counts_match = within_tolerance(
                    reader.record_count, recorded_count, RECORD_COUNT_TOLERANCE
                )
                mismatches.check(label, f"{reader.reader} record count", counts_match)
            recorded_gates: Any = recorded_reader.get("gates")
            if isinstance(recorded_gates, dict):
                for gate in reader.gates:
                    recorded_gate: Any = recorded_gates.get(gate.name)
                    if not isinstance(recorded_gate, dict):
                        continue
                    recorded_value = recorded_gate.get("observed")
                    if not isinstance(recorded_value, (int, float)) or gate.observed is None:
                        continue
                    value_matches = within_tolerance(
                        gate.observed, recorded_value, GATE_VALUE_TOLERANCE
                    )
                    mismatches.check(label, f"{reader.reader} check {gate.name}", value_matches)
            recorded_coverage: Any = recorded_reader.get("coverage")
            if isinstance(recorded_coverage, dict):
                for column_name, recorded_rate in recorded_coverage.items():
                    if not isinstance(recorded_rate, (int, float)):
                        continue
                    observed_rate = reader.coverage.get(str(column_name))
                    if observed_rate is None:
                        mismatches.note(f"{label}: {reader.reader} lost column {column_name}")
                        continue
                    kept_up = observed_rate >= recorded_rate - COVERAGE_DROP_ALLOWED
                    mismatches.check(label, f"{reader.reader} coverage {column_name}", kept_up)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_uids_and_team_ids_are_unique(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Players and clubs have unique uids, and one club stores each team."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        players = career_save.players()
        clubs = career_save.clubs()
        player_uids = {player.uid for player in players}
        mismatches.check(label, "player uids unique", len(player_uids) == len(players))
        club_uids = {club.uid for club in clubs}
        mismatches.check(label, "club uids unique", len(club_uids) == len(clubs))
        storing_club_by_team: dict[int, int] = {}
        teams_stored_twice = 0
        for club in clubs:
            for team in club.teams:
                if team.affiliate:
                    continue
                if team.team_id in storing_club_by_team:
                    teams_stored_twice += 1
                storing_club_by_team[team.team_id] = club.uid
        mismatches.check(label, "each team stored by one club", teams_stored_twice == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_records_reference_each_other(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Every uid one reader hands to another resolves in that other reader's table."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        players = career_save.players()
        clubs = career_save.clubs()
        contracts = career_save.contracts()
        suspensions = career_save.suspensions()
        managed_clubs = career_save.managed_clubs()
        club_uids = {club.uid for club in clubs}
        player_uids = {player.uid for player in players}

        unresolved_player_clubs = sum(
            1
            for player in players
            if player.club_uid is not None and player.club_uid not in club_uids
        )
        mismatches.check(label, "player club uids resolve", unresolved_player_clubs == 0)
        unresolved_registrations = sum(
            1
            for player in players
            if player.team_club_uid is not None and player.team_club_uid not in club_uids
        )
        mismatches.check(label, "registration club uids resolve", unresolved_registrations == 0)
        unresolved_loan_parents = sum(
            1
            for player in players
            if player.loan_parent_club_uid is not None
            and player.loan_parent_club_uid not in club_uids
        )
        mismatches.check(label, "loan parent club uids resolve", unresolved_loan_parents == 0)
        unresolved_parents = sum(
            1
            for club in clubs
            if club.parent_club_uid is not None and club.parent_club_uid not in club_uids
        )
        mismatches.check(label, "parent club uids resolve", unresolved_parents == 0)
        unresolved_contracts = sum(
            1 for contract in contracts if contract.player_uid not in player_uids
        )
        mismatches.check(label, "contract player uids resolve", unresolved_contracts == 0)
        unresolved_suspensions = sum(
            1 for suspension in suspensions if suspension.player_uid not in player_uids
        )
        mismatches.check(label, "suspension player uids resolve", unresolved_suspensions == 0)
        unresolved_managed = sum(
            1 for managed_club in managed_clubs if managed_club.club_uid not in club_uids
        )
        mismatches.check(label, "managed club uids resolve", unresolved_managed == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_managed_club_and_summary_are_present(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Each corpus save has a managed club and a readable save summary."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        managed_clubs = career_save.managed_clubs()
        mismatches.check(label, "managed club rows", len(managed_clubs) >= 1)
        named_clubs = all(
            managed_club.club_name and managed_club.club_short_name
            for managed_club in managed_clubs
        )
        mismatches.check(label, "managed clubs named", named_clubs)
        summary_strings = career_save.info.summary_strings
        mismatches.check(label, "summary strings", len(summary_strings) >= MINIMUM_SUMMARY_STRINGS)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_player_names_resolve_from_the_name_pools(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Almost every player is named, so a pool read that loses its last entry fails."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        name_coverage = career_save.players().coverage["name"]
        mismatches.check(label, "name coverage", name_coverage >= MINIMUM_NAME_COVERAGE)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_marker_less_player_records_are_read(corpus_saves: dict[str, fmsave.Save]) -> None:
    """The pass that finds records without the usual marker still finds some."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        report = fmsave.validate_save(career_save)
        for reader in report.readers:
            if reader.reader != "players":
                continue
            marker_less = reader.anomalies.get("markerless_players", 0)
            mismatches.check(label, "marker-less player records read", marker_less > 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_each_player_contract_matches_the_contract_table(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """A player's embedded contract is the same record the contract table lists for him."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        players = career_save.players()
        contracts = career_save.contracts()
        contract_by_player: dict[int, Any] = {}
        repeated_rows = 0
        for contract in contracts:
            if contract.player_uid in contract_by_player:
                repeated_rows += 1
            contract_by_player[contract.player_uid] = contract
        mismatches.check(label, "one contract row per player", repeated_rows == 0)
        players_with_contract = 0
        differing_contracts = 0
        for player in players:
            if player.contract is None:
                continue
            players_with_contract += 1
            if contract_by_player.get(player.uid) != player.contract:
                differing_contracts += 1
        mismatches.check(label, "embedded contracts match rows", differing_contracts == 0)
        mismatches.check(
            label, "contract row count", players_with_contract == len(contract_by_player)
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_the_contract_in_effect_comes_from_one_chain_record(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """No contract mixes fields from several chain records, or takes an agreed future move.

    Only contracts a chain record filled are checked. A player with no chain record can still
    have dates from the fallback reader inside his own record, and those are not a choice
    between records, so the in-effect rule does not reach them.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        game_date = career_save.info.game_date
        if game_date is None:
            mismatches.note(f"{label}: no in-game date")
            continue
        contracts = career_save.contracts()
        future_starts = 0
        mixed_records = 0
        for contract in contracts:
            if not contract.chain or contract.start is None:
                continue
            if contract.start > game_date:
                future_starts += 1
            from_one_record = any(
                chain_entry.club_uid == contract.club_uid
                and chain_entry.team_id == contract.team_id
                and chain_entry.wage == contract.wage
                and chain_entry.start == contract.start
                for chain_entry in contract.chain
            )
            if not from_one_record:
                mixed_records += 1
        mismatches.check(
            label, "no chain contract starts after the in-game date", future_starts == 0
        )
        mismatches.check(label, "contract fields come from one record", mixed_records == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_goalkeeping_attributes_sit_where_the_reader_expects(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Goalkeepers rate far higher than outfield players on the goalkeeping attributes.

    An attribute block read from the wrong position moves these two groups together.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        goalkeeper_handling: list[int] = []
        outfield_handling: list[int] = []
        for player in career_save.players():
            if player.positions.gk >= NATURAL_GOALKEEPER_RATING:
                goalkeeper_handling.append(player.attributes.handling)
            else:
                outfield_handling.append(player.attributes.handling)
        if not goalkeeper_handling or not outfield_handling:
            mismatches.note(f"{label}: no goalkeepers or no outfield players")
            continue
        separated = (
            statistics.median(goalkeeper_handling) - statistics.median(outfield_handling)
            >= GOALKEEPER_HANDLING_MARGIN
        )
        mismatches.check(label, "goalkeeper handling stands apart", separated)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_parsed_contract_tails_carry_their_clauses(corpus_saves: dict[str, fmsave.Save]) -> None:
    """Every parsed tail yields a clause table, and every clause keeps its raw kind."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        report = fmsave.validate_save(career_save)
        for reader in report.readers:
            if reader.reader != "contracts":
                continue
            missing_tables = reader.anomalies.get("tails_without_clause_table", 0)
            mismatches.check(label, "tails without a clause table", missing_tables == 0)
        contracts = career_save.contracts()
        clauses_seen = 0
        unnamed_without_raw = 0
        for contract in contracts:
            for clause in contract.clauses:
                clauses_seen += 1
                if clause.kind.label is ClauseKind.UNKNOWN and clause.kind.raw < 0:
                    unnamed_without_raw += 1
        mismatches.check(label, "clauses decoded", clauses_seen > 0)
        mismatches.check(label, "unnamed clauses keep a raw kind", unnamed_without_raw == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_affiliate_registrations_are_not_loans(corpus_saves: dict[str, fmsave.Save]) -> None:
    """A player at a team his own club controls belongs to that club and is not on loan."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        clubs = career_save.clubs()
        players = career_save.players()
        affiliate_team_parent: dict[int, int] = {}
        for club in clubs:
            for team in club.teams:
                if team.affiliate:
                    affiliate_team_parent[team.team_id] = club.uid
        mismatches.check(label, "affiliate teams listed", len(affiliate_team_parent) > 0)

        affiliate_registrations = 0
        registrations_marked_on_loan = 0
        registrations_at_the_wrong_club = 0
        loans_without_a_parent = 0
        loans_at_an_affiliate_team = 0
        for player in players:
            if player.team_club_uid is not None:
                affiliate_registrations += 1
                if player.on_loan:
                    registrations_marked_on_loan += 1
                if (
                    player.team_id is not None
                    and affiliate_team_parent.get(player.team_id) != player.club_uid
                ):
                    registrations_at_the_wrong_club += 1
            if player.on_loan:
                if player.loan_parent_club_uid is None:
                    loans_without_a_parent += 1
                if player.team_id is not None and player.team_id in affiliate_team_parent:
                    loans_at_an_affiliate_team += 1
        mismatches.check(label, "affiliate registrations read", affiliate_registrations > 0)
        mismatches.check(
            label, "affiliate registrations not on loan", registrations_marked_on_loan == 0
        )
        mismatches.check(
            label,
            "affiliate registrations at the parent club",
            registrations_at_the_wrong_club == 0,
        )
        mismatches.check(label, "loans name a parent club", loans_without_a_parent == 0)
        mismatches.check(label, "loans are away from affiliates", loans_at_an_affiliate_team == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_loans_carry_their_dates_and_other_players_carry_none(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every loan the save holds runs from a date to a later one on or after the in-game
    date, and only loans have loan dates at all.

    A loan whose stored start does not decode keeps its loan and carries no start, so the
    count of loans without a start is the tripwire for that case: no save has held one yet.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        game_date = career_save.info.game_date
        if game_date is None:
            mismatches.note(f"{label}: no in-game date")
            continue
        loans = 0
        loans_without_an_end = 0
        loans_without_a_start = 0
        ends_before_the_game_date = 0
        starts_after_the_game_date = 0
        starts_after_their_own_end = 0
        dates_without_a_loan = 0
        for player in career_save.players():
            if player.on_loan:
                loans += 1
                if player.loan_end is None:
                    loans_without_an_end += 1
                elif player.loan_end < game_date:
                    ends_before_the_game_date += 1
                if player.loan_start is None:
                    loans_without_a_start += 1
                elif player.loan_start > game_date:
                    starts_after_the_game_date += 1
                if (
                    player.loan_start is not None
                    and player.loan_end is not None
                    and player.loan_start > player.loan_end
                ):
                    starts_after_their_own_end += 1
            elif player.loan_start is not None or player.loan_end is not None:
                dates_without_a_loan += 1
        mismatches.check(label, "loans read", loans > 0)
        mismatches.check(label, "loans carry an end date", loans_without_an_end == 0)
        mismatches.check(label, "loans carry a start date", loans_without_a_start == 0)
        mismatches.check(label, "loan ends are not past", ends_before_the_game_date == 0)
        mismatches.check(label, "loan starts have arrived", starts_after_the_game_date == 0)
        mismatches.check(label, "loan starts precede their end", starts_after_their_own_end == 0)
        mismatches.check(label, "only loans carry loan dates", dates_without_a_loan == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_suspension_rows_match_the_players_they_belong_to(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Each suspension row repeats one of its player's own unserved bans, with his club."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        players = career_save.players()
        suspensions = career_save.suspensions()
        bans_by_player: dict[int, list[tuple[int, date]]] = {}
        listed_bans = 0
        for player in players:
            if not player.suspensions:
                continue
            listed_bans += len(player.suspensions)
            bans_by_player[player.uid] = [
                (ban.suspension_competition_id, ban.issued_date) for ban in player.suspensions
            ]
        club_by_player = {player.uid: player.club_uid for player in players}
        mismatches.check(label, "suspension row count", len(suspensions) == listed_bans)
        rows_not_listed = 0
        rows_at_another_club = 0
        for suspension in suspensions:
            player_bans = bans_by_player.get(suspension.player_uid, [])
            if (suspension.suspension_competition_id, suspension.issued_date) not in player_bans:
                rows_not_listed += 1
            if club_by_player.get(suspension.player_uid) != suspension.club_uid:
                rows_at_another_club += 1
        mismatches.check(label, "suspension rows listed on their player", rows_not_listed == 0)
        mismatches.check(
            label, "suspension rows carry the player's club", rows_at_another_club == 0
        )
    mismatches.fail_if_any()
