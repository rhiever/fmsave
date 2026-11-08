"""Unusual career populations must remain accessible in strict mode."""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path

import pytest

import fmsave
from fmsave import _checks
from tests.test_checks import (
    BOUNDS,
    FULL_SIZE_GAME_DB_BYTES,
    healthy_club_stats,
    healthy_contract_stats,
    healthy_player_stats,
    healthy_suspension_stats,
)
from tests.test_competitions import healthy_competition_stats
from tests.test_fm27_player_partial import fm27_player_save
from tests.test_season_stats import healthy_season_stats
from tests.test_transfer_windows import healthy_window_stats


@pytest.mark.parametrize(
    "changes",
    [
        {"height_in_range": 0},
        {"outfield_goalkeeper_block_low": 0},
        {"with_natural_position": 0},
        {"with_valid_join_date": 0},
        {"world_not_above_current": 0},
        {"home_near_current": 0},
    ],
)
def test_unusual_player_population_warns_in_strict_mode(changes: dict[str, int]) -> None:
    stats = dataclasses.replace(healthy_player_stats(), **changes)
    gates = _checks.evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning):
        assert _checks.enforce("players", gates, strict=True)
    assert not _checks.checks_fail((_checks.ReaderCheck("players", stats.records, gates, {}),))


def test_small_player_population_warns_without_rejecting_strict_read() -> None:
    stats = healthy_player_stats(100)
    gates = _checks.evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning, match="players_minimum"):
        _checks.enforce("players", gates, strict=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"players_with_chain": 100},
        {"without_contract_in_effect": 10_000},
        {"tail_ends_past": 10_000},
        {"date_marked_chain_records": 10_000},
        {"tails_parsed": 100},
        {"tails_without_clause_table": 100},
        {"head_ok": 100},
    ],
)
def test_contract_presence_and_history_warn_in_strict_mode(changes: dict[str, int]) -> None:
    stats = dataclasses.replace(healthy_contract_stats(), **changes)
    gates = _checks.evaluate_contracts(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning):
        _checks.enforce("contracts", gates, strict=True)


def test_no_suspensions_is_not_a_strict_read_failure() -> None:
    stats = dataclasses.replace(
        healthy_suspension_stats(),
        entries=0,
        players_with_entries=0,
        competition_entries=0,
        competition_issued_after_clock=0,
        nation_issued_after_clock=0,
        entries_with_known_scope=0,
    )
    gates = _checks.evaluate_suspensions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning):
        _checks.enforce("suspensions", gates, strict=True)


def test_unknown_suspension_scope_warns_without_rejecting_decoded_entries() -> None:
    stats = dataclasses.replace(healthy_suspension_stats(), entries_with_known_scope=0)
    gates = _checks.evaluate_suspensions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning, match="suspension_scopes_known"):
        _checks.enforce("suspensions", gates, strict=True)


def test_extended_match_minutes_are_not_an_encoding_failure() -> None:
    stats = dataclasses.replace(healthy_season_stats(), minutes_in_range=0)
    gates = _checks.evaluate_season_stats(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning, match="season_stats_minutes_in_range"):
        _checks.enforce("player_season_stats", gates, strict=True)


def test_second_nation_qualifier_does_not_reject_known_nationality() -> None:
    stats = dataclasses.replace(healthy_player_stats(), second_nation_qualifier_ok=0)
    gates = _checks.evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning, match="second_nation_qualifier"):
        _checks.enforce("players", gates, strict=True)


def test_strict_mode_still_rejects_invalid_record_sentinels_amid_population_warnings() -> None:
    stats = dataclasses.replace(healthy_player_stats(100), relation_sentinel_ok=0)
    gates = _checks.evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.raises(fmsave.ReaderCheckError, match="relation_sentinel") as caught:
        _checks.enforce("players", gates, strict=True)
    assert "players_minimum" not in str(caught.value)


@pytest.mark.parametrize("population", ["relations", "clauses", "normal_statuses"])
def test_absent_optional_population_has_no_integrity_comparison(population: str) -> None:
    if population == "relations":
        gates = _checks.evaluate_players(
            dataclasses.replace(healthy_player_stats(), relation_entries=0, relation_sentinel_ok=0),
            BOUNDS,
            FULL_SIZE_GAME_DB_BYTES,
        )
        gate_name = "relation_sentinel"
    elif population == "clauses":
        gates = _checks.evaluate_contracts(
            dataclasses.replace(
                healthy_contract_stats(), clause_tables=0, clause_tables_ending_at_tail=0, head_ok=0
            ),
            BOUNDS,
            FULL_SIZE_GAME_DB_BYTES,
        )
        gate_name = "clause_terminator"
    else:
        gates = _checks.evaluate_clubs(
            dataclasses.replace(healthy_club_stats(), status_normal=0, status_confirmed=0),
            BOUNDS,
            FULL_SIZE_GAME_DB_BYTES,
        )
        gate_name = "status_confirmation"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", fmsave.ReaderCheckWarning)
        _checks.enforce(population, gates, strict=True)
    (gate,) = [gate for gate in gates if gate.name == gate_name]
    assert not gate.applied
    assert gate.observed is None


def test_no_competition_mapping_does_not_invent_identity_conflicts() -> None:
    stats = dataclasses.replace(
        healthy_competition_stats(),
        competitions=0,
        with_database_id=0,
        database_id_conflicts=0,
        with_name=0,
    )
    gates = _checks.evaluate_competitions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning):
        _checks.enforce("competitions", gates, strict=True)
    assert all(not gate.applied for gate in gates if not gate.advisory)


def test_no_transfer_windows_has_no_invalid_dates() -> None:
    stats = dataclasses.replace(healthy_window_stats(), windows=0, incomplete=0)
    gates = _checks.evaluate_transfer_windows(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.warns(fmsave.ReaderCheckWarning):
        _checks.enforce("transfer_windows", gates, strict=True)
    (dates,) = [gate for gate in gates if gate.name == "transfer_window_dates"]
    assert not dates.applied


@pytest.mark.parametrize("strict", [False, True])
def test_small_fm27_career_keeps_decoded_rows_when_all_checks_are_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strict: bool
) -> None:
    original_bounds = fmsave.Save._gate_bounds

    def full_checks(save: fmsave.Save) -> _checks.GateBounds:
        return dataclasses.replace(original_bounds(save), minimum_applies_from_bytes=0)

    monkeypatch.setattr(fmsave.Save, "_gate_bounds", full_checks)
    with fm27_player_save(tmp_path, strict=strict) as save:
        with pytest.warns(fmsave.ReaderCheckWarning):
            players = save.players()
        assert len(players) == 1
        assert players[0].name == "Alex Example"
        assert players[0].age == 28
        assert save.players() is players
        assert len(save.contracts()) == 0
        assert len(save.suspensions()) == 0
