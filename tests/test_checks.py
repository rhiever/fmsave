from __future__ import annotations

import copy
import dataclasses
import json
import pickle
import re
import struct
from array import array
from pathlib import Path

import pytest

import fmsave
from fmsave import checks
from fmsave._errors import ISSUES_URL
from fmsave._layouts import (
    FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    ClubStatusLayout,
    GateBounds,
    find_layout,
)
from fmsave._reader_stats import (
    ClubStats,
    ContractStats,
    ManagedStats,
    PlayerStats,
    SuspensionStats,
)
from fmsave._save import (
    CLUBS_TABLE_CACHE_KEY,
    CONTRACTS_TABLE_CACHE_KEY,
    PLAYERS_TABLE_CACHE_KEY,
    SUSPENSIONS_TABLE_CACHE_KEY,
)
from fmsave._status import registered_statuses
from fmsave.checks import (
    GateResult,
    ReaderCheck,
    ReaderValidation,
    ValidationReport,
    check_managed,
    enforce,
    enforce_checks,
    evaluate_clubs,
    evaluate_contracts,
    evaluate_players,
    evaluate_suspensions,
    validate_save,
)
from fmsave.readers.clubs import find_club_layouts, read_club_index
from tests.fixtures.career import (
    MANAGER_SELECTOR,
    STAGE_ROW_COUNT,
    career_stage_rows,
    career_summary,
    manager_region_bytes,
)
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    section_body,
)
from tests.fixtures.game_db import (
    NORMAL_STATUS_KIND,
    club_record_bytes,
    contract_bytes,
    game_db_body,
    humans_body,
    name_pools_bytes,
    person_block_bytes,
    player_record_bytes,
    relation_entry_bytes,
    stage_table_bytes,
    status_record_bytes,
    suspension_entry_bytes,
)

MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 300 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
GAME_DB_SCHEMA = 4000
FILE_NAME = "career example.fm"

PLAYER_GATE_NAMES = (
    "players_minimum",
    "person_blocks",
    "names_resolved",
    "relation_sentinel",
    "second_nation_qualifier",
    "handling_above_finishing",
    "outfield_goalkeeper_block_low",
    "with_natural_position",
    "height_in_range",
    "height_median",
    "age_median",
    "aged_in_range",
    "condition_sharpness_in_range",
    "join_date_valid",
    "world_not_above_current",
    "home_near_current",
    "team_resolved",
    "home_grown_club_refs_resolved",
)
CONTRACT_GATE_NAMES = (
    "players_with_chain",
    "no_contract_in_effect",
    "date_marked_chain_records",
    "tails_parsed",
    "tails_without_clause_table",
    "clause_terminator",
    "contract_head",
    "past_dated_tail_ends",
    "chain_teams_resolved",
)
CLUB_GATE_NAMES = (
    "clubs_minimum",
    "team_lists_found",
    "status_normal",
    "status_confirmation",
    "affiliate_lists_found",
    "affiliate_teams_linked",
    "reputation_found",
    "reputation_median",
)
SUSPENSION_GATE_NAMES = ("suspension_share_of_players", "issued_after_clock")

REPORT_KEYS = {
    "fmsave_version",
    "python_version",
    "os",
    "game",
    "build",
    "known_build",
    "section_schemas",
    "readers",
    "field_statuses",
}
READER_KEYS = {"reader", "status", "record_count", "gates", "coverage", "anomalies"}
GATE_KEYS = {"name", "observed", "minimum", "maximum", "passed", "applied"}
READER_ORDER = (
    "clubs",
    "players",
    "contracts",
    "suspensions",
    "managed_clubs",
    "stages",
    "competitions",
    "fixtures",
)
EXAMPLE_COMPETITION_COUNT = 3


def registered_gate_bounds() -> GateBounds:
    return find_layout(GateBounds, "game_db", GAME_DB_SCHEMA, "").layout


BOUNDS = registered_gate_bounds()


def healthy_player_stats(records: int = 20_000) -> PlayerStats:
    """Stats with every rate and median comfortably inside its bound."""
    return PlayerStats(
        records=records,
        markerless=records // 50,
        with_person_block=records,
        with_resolved_name=records,
        relation_entries=records * 5,
        relation_sentinel_ok=records * 5,
        second_nation_entries=records // 4,
        second_nation_qualifier_ok=records // 4,
        handling_above_finishing=records // 4,
        outfield_players=records * 9 // 10,
        outfield_goalkeeper_block_low=records * 9 // 10,
        with_natural_position=records,
        height_in_range=records,
        condition_sharpness_in_range=records,
        with_valid_join_date=records // 2,
        world_not_above_current=records,
        home_near_current=records,
        with_team=records // 2,
        team_resolved=records // 2,
        aged_in_range=records,
        home_grown_club_refs=records // 3,
        home_grown_club_refs_resolved=records // 3,
        ages=array("i", [24] * records),
        heights_median=181,
    )


def healthy_contract_stats() -> ContractStats:
    return ContractStats(
        players=20_000,
        contracts=19_500,
        players_with_chain=19_000,
        without_contract_in_effect=100,
        chain_records=25_000,
        date_marked_chain_records=100,
        tails_parsed=24_000,
        tails_without_clause_table=5,
        clause_tables=23_995,
        clause_tables_ending_at_tail=23_995,
        head_ok=22_800,
        tail_ends=18_000,
        tail_ends_past=5,
        chain_teams_resolved=24_950,
    )


def healthy_club_stats() -> ClubStats:
    return ClubStats(
        records=50_000,
        team_lists_found=50_000,
        status_normal=49_950,
        status_confirmed=49_500,
        affiliate_lists=950,
        affiliate_refs=1_000,
        affiliate_refs_linked=1_000,
        reputation_found=49_900,
        reputations_median=1_100,
    )


def healthy_suspension_stats() -> SuspensionStats:
    return SuspensionStats(
        players=20_000, entries=110, players_with_entries=100, issued_after_clock=0
    )


def failing_gate(name: str) -> GateResult:
    return GateResult(name, 0.5, 0.9, None, False, True)


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def test_gate_switch_is_on_by_default() -> None:
    assert checks._gates_enabled is True
    shifted_results = evaluate_players(
        dataclasses.replace(healthy_player_stats(), handling_above_finishing=12_200),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    with pytest.raises(fmsave.ReaderCheckError):
        enforce("players", shifted_results)


def test_disabling_gates_restores_the_switch_after_an_exception() -> None:
    shifted_results = evaluate_players(
        dataclasses.replace(healthy_player_stats(), handling_above_finishing=12_200),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    with pytest.raises(RuntimeError, match="fictional failure"), checks._gates_disabled():
        assert checks._gates_enabled is False
        enforce("players", shifted_results)
        raise RuntimeError("fictional failure")
    assert checks._gates_enabled is True


def test_gate_bounds_apply_from_the_full_save_threshold() -> None:
    assert BOUNDS.minimum_applies_from_bytes == FULL_SAVE_MINIMUM_GAME_DB_BYTES


def test_healthy_player_stats_pass_every_applied_gate() -> None:
    results = evaluate_players(healthy_player_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == PLAYER_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("players", results)


def test_player_gates_are_not_applied_to_a_small_section() -> None:
    results = evaluate_players(healthy_player_stats(), BOUNDS, SMALL_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == PLAYER_GATE_NAMES
    assert all(not result.applied and result.passed for result in results)
    shifted_results = evaluate_players(
        dataclasses.replace(
            healthy_player_stats(), handling_above_finishing=12_200, with_natural_position=17_800
        ),
        BOUNDS,
        SMALL_GAME_DB_BYTES,
    )
    assert all(not result.applied for result in shifted_results)
    enforce("players", shifted_results)


def test_a_shifted_layout_fails_with_a_message_naming_both_gates() -> None:
    shifted_stats = dataclasses.replace(
        healthy_player_stats(), handling_above_finishing=12_200, with_natural_position=17_800
    )
    results = evaluate_players(shifted_stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["handling_above_finishing", "with_natural_position"]
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("players", results)
    assert str(error_info.value) == (
        "players failed checks: handling_above_finishing=0.61 (expected 0.2..0.3); "
        "with_natural_position=0.89 (expected 0.97..). "
        f"Please report it at {ISSUES_URL} with the output of fmsave validate."
    )


def test_one_record_short_of_the_minimum_fails_only_the_players_minimum_gate() -> None:
    assert (
        failed_gate_names(
            evaluate_players(healthy_player_stats(5_000), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
        )
        == []
    )
    results = evaluate_players(healthy_player_stats(4_999), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["players_minimum"]
    assert results[0] == GateResult("players_minimum", 4_999, 5_000, None, False, True)
    with pytest.raises(
        fmsave.ReaderCheckError, match=r"players_minimum=4999 \(expected 5000\.\.\)"
    ):
        enforce("players", results)


@pytest.mark.parametrize(
    ("valid_join_dates", "expected_failures"),
    [
        pytest.param(1_000, [], id="lower-edge"),
        pytest.param(19_000, [], id="upper-edge"),
        pytest.param(990, ["join_date_valid"], id="below"),
        pytest.param(19_010, ["join_date_valid"], id="above"),
    ],
)
def test_the_join_date_share_is_checked_at_both_edges(
    valid_join_dates: int, expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(healthy_player_stats(), with_valid_join_date=valid_join_dates)
    results = evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == expected_failures


def test_player_medians_are_checked_against_their_bounds() -> None:
    low_heights = dataclasses.replace(healthy_player_stats(), heights_median=169)
    old_ages = dataclasses.replace(healthy_player_stats(), ages=array("i", [31] * 20_000))
    assert failed_gate_names(evaluate_players(low_heights, BOUNDS, FULL_SIZE_GAME_DB_BYTES)) == [
        "height_median"
    ]
    old_results = evaluate_players(old_ages, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(old_results) == ["age_median"]
    assert {result.name: result.observed for result in old_results}["age_median"] == 31


def test_a_rate_with_no_denominator_has_no_observed_value_and_fails_when_applied() -> None:
    no_relations = dataclasses.replace(
        healthy_player_stats(), relation_entries=0, relation_sentinel_ok=0
    )
    results = evaluate_players(no_relations, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    sentinel_result = results[PLAYER_GATE_NAMES.index("relation_sentinel")]
    assert sentinel_result == GateResult("relation_sentinel", None, 0.999, None, False, True)
    small_results = evaluate_players(no_relations, BOUNDS, SMALL_GAME_DB_BYTES)
    assert small_results[PLAYER_GATE_NAMES.index("relation_sentinel")] == GateResult(
        "relation_sentinel", None, 0.999, None, True, False
    )


def test_healthy_contract_stats_pass() -> None:
    results = evaluate_contracts(healthy_contract_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == CONTRACT_GATE_NAMES
    assert all(result.applied and result.passed for result in results)


@pytest.mark.parametrize(
    ("stat_changes", "expected_failures"),
    [
        pytest.param({"players_with_chain": 14_000}, [], id="chain-share-at-edge"),
        pytest.param(
            {"players_with_chain": 13_990}, ["players_with_chain"], id="chain-share-below"
        ),
        pytest.param({"tails_parsed": 17_500}, [], id="tails-at-edge"),
        pytest.param({"tails_parsed": 17_490}, ["tails_parsed"], id="tails-below"),
        pytest.param(
            {"tails_without_clause_table": 24}, [], id="tails-without-clause-table-at-edge"
        ),
        pytest.param(
            {"tails_without_clause_table": 25},
            ["tails_without_clause_table"],
            id="tails-without-clause-table-above",
        ),
        pytest.param({"clause_tables_ending_at_tail": 23_972}, [], id="clause-terminator-at-edge"),
        pytest.param(
            {"clause_tables_ending_at_tail": 23_971},
            ["clause_terminator"],
            id="clause-terminator-below",
        ),
        pytest.param({"head_ok": 15_597}, [], id="head-at-edge"),
        pytest.param({"head_ok": 15_596}, ["contract_head"], id="head-below"),
        pytest.param({"tail_ends_past": 900}, [], id="past-dated-at-edge"),
    ],
)
def test_contract_gates_are_checked_at_their_edges(
    stat_changes: dict[str, int], expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(healthy_contract_stats(), **stat_changes)
    results = evaluate_contracts(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == expected_failures


def test_past_dated_tail_ends_are_a_share_of_the_tails_with_an_end() -> None:
    stats = dataclasses.replace(healthy_contract_stats(), tail_ends_past=918)
    results = evaluate_contracts(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["past_dated_tail_ends"]
    assert results[CONTRACT_GATE_NAMES.index("past_dated_tail_ends")].observed == pytest.approx(
        0.051
    )
    with pytest.raises(
        fmsave.ReaderCheckError,
        match=re.escape("contracts failed checks: past_dated_tail_ends=0.051 (expected ..0.05)."),
    ):
        enforce("contracts", results)


def test_club_gates_pass_healthy_stats_and_fail_below_the_club_minimum() -> None:
    results = evaluate_clubs(healthy_club_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == CLUB_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    few_clubs = ClubStats(
        records=4_999,
        team_lists_found=4_999,
        status_normal=4_990,
        status_confirmed=4_950,
        affiliate_lists=95,
        affiliate_refs=100,
        affiliate_refs_linked=100,
        reputation_found=4_990,
        reputations_median=1_100,
    )
    assert failed_gate_names(evaluate_clubs(few_clubs, BOUNDS, FULL_SIZE_GAME_DB_BYTES)) == [
        "clubs_minimum"
    ]


def test_an_affiliate_decode_that_finds_nothing_fails_instead_of_switching_off() -> None:
    nothing_found = dataclasses.replace(
        healthy_club_stats(), affiliate_lists=0, affiliate_refs=0, affiliate_refs_linked=0
    )
    results = evaluate_clubs(nothing_found, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["affiliate_lists_found"]
    # The share of linked ids has lost its denominator, so the share of lists is what fails.
    linked_share = next(result for result in results if result.name == "affiliate_teams_linked")
    assert not linked_share.applied


@pytest.mark.parametrize(
    ("stat_changes", "expected_failures"),
    [
        pytest.param({"reputation_found": 45_000}, [], id="share-at-edge"),
        pytest.param({"reputation_found": 44_990}, ["reputation_found"], id="share-below"),
        pytest.param({"reputations_median": 200}, [], id="median-at-lower-edge"),
        pytest.param({"reputations_median": 199}, ["reputation_median"], id="median-below"),
        pytest.param({"reputations_median": 3_000}, [], id="median-at-upper-edge"),
        pytest.param({"reputations_median": 3_001}, ["reputation_median"], id="median-above"),
    ],
)
def test_the_club_reputation_gates_are_checked_at_their_edges(
    stat_changes: dict[str, int], expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(healthy_club_stats(), **stat_changes)
    results = evaluate_clubs(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == expected_failures


def test_a_club_status_read_that_loses_the_reputation_fails_both_reputation_gates() -> None:
    """Reading the reputation a byte out inside the status record is what these gates catch.

    Most clubs are then left with no readable reputation, and the few that keep one sit far
    above the median band; a read that finds no reputation at all fails just as loudly.
    """
    shifted_read = dataclasses.replace(
        healthy_club_stats(), reputation_found=7_000, reputations_median=4_100
    )
    shifted_results = evaluate_clubs(shifted_read, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(shifted_results) == ["reputation_found", "reputation_median"]
    with pytest.raises(fmsave.ReaderCheckError, match=r"reputation_found=0\.14"):
        enforce("clubs", shifted_results)

    nothing_read = dataclasses.replace(
        healthy_club_stats(), reputation_found=0, reputations_median=None
    )
    nothing_read_results = evaluate_clubs(nothing_read, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(nothing_read_results) == ["reputation_found", "reputation_median"]


def test_healthy_suspension_stats_pass() -> None:
    results = evaluate_suspensions(healthy_suspension_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == SUSPENSION_GATE_NAMES
    assert all(result.applied and result.passed for result in results)


@pytest.mark.parametrize(
    ("entries", "issued_after_clock", "expected_failures"),
    [
        pytest.param(1_000, 1, [], id="one-late-entry-in-a-thousand"),
        pytest.param(1_000, 10, [], id="at-edge"),
        pytest.param(1_000, 20, ["issued_after_clock"], id="two-percent-late"),
    ],
)
def test_suspensions_issued_after_the_clock_are_a_share_of_the_entries(
    entries: int, issued_after_clock: int, expected_failures: list[str]
) -> None:
    stats = SuspensionStats(
        players=20_000,
        entries=entries,
        players_with_entries=100,
        issued_after_clock=issued_after_clock,
    )
    results = evaluate_suspensions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == expected_failures
    assert results[1].observed == pytest.approx(issued_after_clock / entries)


@pytest.mark.parametrize(
    ("players_with_entries", "expected_failures"),
    [
        pytest.param(20, [], id="lower-edge"),
        pytest.param(19, ["suspension_share_of_players"], id="below"),
        pytest.param(2_000, [], id="upper-edge"),
        pytest.param(2_010, ["suspension_share_of_players"], id="above"),
    ],
)
def test_the_suspension_share_of_players_is_bounded_at_both_ends(
    players_with_entries: int, expected_failures: list[str]
) -> None:
    stats = SuspensionStats(
        players=20_000,
        entries=players_with_entries,
        players_with_entries=players_with_entries,
        issued_after_clock=0,
    )
    results = evaluate_suspensions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert results[0].minimum == 0.001
    assert results[0].maximum == 0.10
    assert failed_gate_names(results) == expected_failures


def test_a_suspension_search_that_finds_nothing_fails_both_checks() -> None:
    """An entry layout that has moved must fail, not report a save with no suspensions."""
    nothing_found = SuspensionStats(
        players=20_000, entries=0, players_with_entries=0, issued_after_clock=0
    )
    results = evaluate_suspensions(nothing_found, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == list(SUSPENSION_GATE_NAMES)
    assert results[0].observed == 0.0
    assert results[1].observed is None
    with pytest.raises(fmsave.ReaderCheckError, match=r"suspension_share_of_players=0 "):
        enforce("suspensions", results)
    small_results = evaluate_suspensions(nothing_found, BOUNDS, SMALL_GAME_DB_BYTES)
    assert all(not result.applied and result.passed for result in small_results)


def test_the_managed_club_reader_has_no_checks_and_reports_what_its_routes_found() -> None:
    """A manager between jobs has no club, so no bound here could tell that from a break.

    The reader reports what each route found as an anomaly instead of carrying checks that
    are built to pass whatever happens.
    """
    between_jobs = ManagedStats(human_count=1, route_one_resolved=0, route_two_resolved=0, rows=0)
    reader_check = check_managed(between_jobs, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert reader_check.reader == "managed_clubs"
    assert reader_check.record_count == 0
    assert reader_check.gates == ()
    assert dict(reader_check.anomalies) == {
        "humans_without_club": 1,
        "club_route_one_unresolved": 1,
        "club_route_two_unresolved": 1,
    }
    enforce_checks((reader_check,))
    with_club = ManagedStats(human_count=1, route_one_resolved=1, route_two_resolved=1, rows=1)
    assert dict(check_managed(with_club, BOUNDS, FULL_SIZE_GAME_DB_BYTES).anomalies) == {
        "humans_without_club": 0,
        "club_route_one_unresolved": 0,
        "club_route_two_unresolved": 0,
    }


def test_a_failed_check_with_a_likely_cause_names_it() -> None:
    """The check most likely to fail first on an unseen save says what usually causes it."""
    missing_tables = dataclasses.replace(healthy_contract_stats(), tails_without_clause_table=100)
    results = evaluate_contracts(missing_tables, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["tails_without_clause_table"]
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("contracts", results)
    assert "likely an unrecognised bonus list shape in the contract tail" in str(error_info.value)

    few_chains = dataclasses.replace(healthy_contract_stats(), players_with_chain=1_000)
    other_results = evaluate_contracts(few_chains, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.raises(fmsave.ReaderCheckError) as other_error_info:
        enforce("contracts", other_results)
    assert "likely" not in str(other_error_info.value)


def test_two_failing_readers_of_one_pass_share_one_joined_message() -> None:
    contract_check = ReaderCheck("contracts", 10, (failing_gate("tails_parsed"),), {})
    suspension_check = ReaderCheck("suspensions", 3, (failing_gate("issued_after_clock"),), {})
    passing_check = ReaderCheck("players", 20, (), {})
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce_checks((passing_check, contract_check, suspension_check))
    assert str(error_info.value) == (
        "contracts failed checks: tails_parsed=0.5 (expected 0.9..). "
        "suspensions failed checks: issued_after_clock=0.5 (expected 0.9..). "
        f"Please report it at {ISSUES_URL} with the output of fmsave validate."
    )
    assert isinstance(error_info.value, checks.GateCheckError)
    assert error_info.value.checks == (passing_check, contract_check, suspension_check)


def test_the_enforce_message_holds_no_digits_beyond_rates_and_bounds() -> None:
    shifted_stats = dataclasses.replace(
        healthy_player_stats(), handling_above_finishing=12_345, with_natural_position=17_800
    )
    results = evaluate_players(shifted_stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("players", results)
    message = str(error_info.value)
    remainder = message.replace(ISSUES_URL, "")
    for gate_name in ("handling_above_finishing", "with_natural_position"):
        assert gate_name in remainder
        remainder = remainder.replace(gate_name, "")
    for number_text in ("0.6172", "0.2..0.3", "0.89", "0.97"):
        assert number_text in remainder
        remainder = remainder.replace(number_text, "")
    assert re.search(r"\d", remainder) is None
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


@pytest.mark.parametrize(
    ("handling_above_finishing", "outfield_goalkeeper_block_low"),
    [
        pytest.param(3_600, 3_600, id="attribute bytes read one position late"),
        pytest.param(12_200, 6_300, id="attribute bytes read one position early"),
    ],
)
def test_a_one_byte_attribute_shift_fails_both_attribute_gates(
    handling_above_finishing: int, outfield_goalkeeper_block_low: int
) -> None:
    shifted_stats = dataclasses.replace(
        healthy_player_stats(),
        handling_above_finishing=handling_above_finishing,
        outfield_goalkeeper_block_low=outfield_goalkeeper_block_low,
    )
    results = evaluate_players(shifted_stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == [
        "handling_above_finishing",
        "outfield_goalkeeper_block_low",
    ]


@pytest.mark.parametrize(
    ("outfield_goalkeeper_block_low", "passes"),
    [
        pytest.param(18_000, True, id="every outfield player low"),
        pytest.param(16_200, True, id="exactly at the lower edge"),
        pytest.param(16_199, False, id="just below the lower edge"),
        pytest.param(0, False, id="no outfield player low"),
    ],
)
def test_the_goalkeeper_block_gate_needs_a_high_share_of_low_outfield_players(
    outfield_goalkeeper_block_low: int, passes: bool
) -> None:
    stats = dataclasses.replace(
        healthy_player_stats(), outfield_goalkeeper_block_low=outfield_goalkeeper_block_low
    )
    assert stats.outfield_players == 18_000
    assert BOUNDS.outfield_goalkeeper_block_low == (0.90, None)
    results = evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    expected_failures = [] if passes else ["outfield_goalkeeper_block_low"]
    assert failed_gate_names(results) == expected_failures


def test_the_goalkeeper_block_gate_has_no_rate_without_outfield_players() -> None:
    stats = dataclasses.replace(
        healthy_player_stats(), outfield_players=0, outfield_goalkeeper_block_low=0
    )
    results = evaluate_players(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    gate = next(result for result in results if result.name == "outfield_goalkeeper_block_low")
    assert gate.observed is None
    assert not gate.passed


# A fragment whose readers see known counts: two clubs, two players, a human manager.
NORTHBRIDGE_UID = 5001
NORTHBRIDGE_TEAM_A = 70001
NORTHBRIDGE_TEAM_B = 70002
SOUTHPORT_UID = 5002
SOUTHPORT_TEAM = 70003
UNREGISTERED_TEAM_ID = 79999
PLAYER_A_UID = 900001
PLAYER_B_UID = 900002
HANDLING_INDEX = 11
FINISHING_INDEX = 2
# The attributes next to handling and throwing, the edges of the goalkeeping block.
GOALKEEPER_BLOCK_NEIGHBOUR_INDEXES = (10, 12, 13, 14, 15, 17)
SUMMARY_SCHEMA = 29


def goalkeeper_block_bytes_between_low_edges() -> list[int]:
    """Raw attributes at 50, except one above it next to handling and throwing.

    A goalkeeper-block count that reads a neighbour of either attribute then sees 51, above the
    low maximum the counted tests use.
    """
    raw_attributes = [50] * 54
    for index in GOALKEEPER_BLOCK_NEIGHBOUR_INDEXES:
        raw_attributes[index] = 51
    return raw_attributes


def counted_clubs_region() -> bytes:
    clubs = [
        club_record_bytes(
            club_index=1,
            uid=NORTHBRIDGE_UID,
            nation_id=3,
            fa_nation_id=3,
            city_id=77,
            name="Northbridge FC",
            short_name="Northbridge",
            team_ids=(NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B),
            affiliate_team_ids=(SOUTHPORT_TEAM,),
        ),
        club_record_bytes(
            club_index=2,
            uid=SOUTHPORT_UID,
            nation_id=3,
            fa_nation_id=3,
            city_id=77,
            name="Southport Example",
            short_name="Southport",
            team_ids=(SOUTHPORT_TEAM,),
        ),
    ]
    statuses = [
        status_record_bytes(
            ordinal=51,
            club_index=1,
            uid=NORTHBRIDGE_UID,
            kind=NORMAL_STATUS_KIND,
            last_league_position=1,
            reputation=5000,
        ),
        # The index stored before this status record names another club, so it confirms nothing.
        status_record_bytes(
            ordinal=52,
            club_index=9,
            uid=SOUTHPORT_UID,
            kind=NORMAL_STATUS_KIND,
            last_league_position=2,
            reputation=4000,
        ),
    ]
    return game_db_body(clubs, statuses, gap_bytes=2000)


def player_a_relations() -> tuple[bytes, ...]:
    broken_sentinel = bytearray(relation_entry_bytes(46, 8, 9, qualifier=7))
    broken_sentinel[15] = 0
    return (
        relation_entry_bytes(45, 8, 9, qualifier=100),
        bytes(broken_sentinel),
        relation_entry_bytes(1, 1, 72),
        relation_entry_bytes(9, 1, 72),
    )


def player_a_contract_records() -> bytes:
    resolved_record, _ = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=12000,
        start=packed_date(183, 2029),
        tail={"end": packed_date(182, 2032), "status": 3},
        head={"type": 1},
        clauses=((250000, 365, 0x12),),
    )
    past_record, past_tag_offset = contract_bytes(
        selector=12,
        team_id=UNREGISTERED_TEAM_ID,
        wage=3000,
        start=packed_date(213, 2029),
        tail={"end": packed_date(181, 2030), "status": 7},
        head=None,
    )
    past_record_with_bad_terminator = bytearray(past_record)
    struct.pack_into("<I", past_record_with_bad_terminator, past_tag_offset - 70, 1)
    tailless_record, _ = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_B,
        wage=1,
        start=packed_date(1, 2029),
        tail=None,
    )
    return resolved_record + bytes(past_record_with_bad_terminator) + tailless_record


def player_a_bytes() -> bytes:
    raw_attributes = goalkeeper_block_bytes_between_low_edges()
    raw_attributes[HANDLING_INDEX] = 60
    raw_attributes[FINISHING_INDEX] = 50
    ratings = [10] * 15
    ratings[0] = 18
    suspensions = suspension_entry_bytes(
        competition_id=1234, issued=packed_date(51, 2031), e7=3, e14=1
    ) + suspension_entry_bytes(competition_id=4321, issued=packed_date(100, 2031), e7=64, e14=5)
    person_block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=(15, 12, 9, 20, 18, 7, 11, 3),
        trait_bits=0,
        relations=player_a_relations(),
    )
    return player_record_bytes(
        pindex=11,
        uid=PLAYER_A_UID,
        current_ability=120,
        potential_ability=140,
        bucket=100,
        home_reputation=5000,
        current_reputation=5200,
        world_reputation=5100,
        team_id=NORTHBRIDGE_TEAM_A,
        ratings=ratings,
        raw_attributes=raw_attributes,
        transfer_value_raw=0xFFFFFFFF,
        join_date=packed_date(60, 2029),
        sharpness=7000,
        condition=9000,
        height_cm=180,
        trailing=suspensions + person_block + player_a_contract_records(),
    )


def player_b_bytes() -> bytes:
    """A marker-less player with no person block, no contract and out-of-range values."""
    return player_record_bytes(
        pindex=12,
        uid=PLAYER_B_UID,
        current_ability=90,
        potential_ability=100,
        bucket=80,
        home_reputation=3000,
        current_reputation=5200,
        world_reputation=6000,
        team_id=UNREGISTERED_TEAM_ID,
        ratings=[10] * 15,
        raw_attributes=goalkeeper_block_bytes_between_low_edges(),
        transfer_value_raw=0xFFFFFFFF,
        join_date=packed_date(0, 2029),
        sharpness=7000,
        condition=12000,
        height_cm=140,
        marker=packed_date(10, 2030),
        trailing=bytes(300),
    )


def counted_game_db() -> bytes:
    payload = (
        name_pools_bytes(["Alex"], ["Example"], [])
        + counted_clubs_region()
        + bytes(64)
        + manager_region_bytes()
        + player_a_bytes()
        + player_b_bytes()
        # The stage table goes last, where the save keeps it, so the stage and competition
        # readers run here too and their checks are enforced like every other reader's.
        + stage_table_bytes(career_stage_rows())
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def write_counted_fragment(
    tmp_path: Path, *, humans: bytes | None = None, summary: bytes | None = None
) -> Path:
    replacements = {
        "game_db": counted_game_db(),
        "humans": humans_body(count=1, selector=MANAGER_SELECTOR) if humans is None else humans,
        "save_game_summary": career_summary(linked=True) if summary is None else summary,
    }
    sections = [
        SectionFrame(
            section.name,
            replacements.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


@pytest.fixture
def counted_fragment_path(tmp_path: Path) -> Path:
    return write_counted_fragment(tmp_path)


def reader_by_name(report: ValidationReport) -> dict[str, ReaderValidation]:
    return {reader.reader: reader for reader in report.readers}


def observed_by_gate(reader: ReaderValidation) -> dict[str, float | None]:
    return {gate.name: gate.observed for gate in reader.gates}


def test_validate_save_reports_every_reader_ok_with_gates_not_applied(
    counted_fragment_path: Path,
) -> None:
    with fmsave.open(counted_fragment_path) as career_save:
        report = validate_save(career_save)
        save_info = career_save.info
    assert tuple(reader.reader for reader in report.readers) == READER_ORDER
    assert all(reader.status == "ok" for reader in report.readers)
    assert all(
        not gate.applied and gate.passed for reader in report.readers for gate in reader.gates
    )
    readers = reader_by_name(report)
    assert tuple(gate.name for gate in readers["clubs"].gates) == CLUB_GATE_NAMES
    assert tuple(gate.name for gate in readers["players"].gates) == PLAYER_GATE_NAMES
    assert tuple(gate.name for gate in readers["contracts"].gates) == CONTRACT_GATE_NAMES
    assert tuple(gate.name for gate in readers["suspensions"].gates) == SUSPENSION_GATE_NAMES
    assert readers["managed_clubs"].gates == ()
    assert {name: reader.record_count for name, reader in readers.items()} == {
        "clubs": 2,
        "players": 2,
        "contracts": 1,
        "suspensions": 2,
        "managed_clubs": 1,
        "stages": STAGE_ROW_COUNT,
        "competitions": EXAMPLE_COMPETITION_COUNT,
        # This fragment's span carries no fixture records at all.
        "fixtures": 0,
    }
    assert report.game == save_info.game
    assert report.build == save_info.build
    assert report.known_build is save_info.known_build
    assert dict(report.section_schemas) == dict(save_info.section_schemas)
    assert report.fmsave_version == fmsave.__version__
    assert dict(report.field_statuses) == dict(registered_statuses())
    assert readers["players"].coverage["name"] == pytest.approx(0.5)
    assert readers["clubs"].coverage["name"] == 1.0


def test_reader_passes_collect_the_counts_their_gates_check(counted_fragment_path: Path) -> None:
    with fmsave.open(counted_fragment_path) as career_save:
        readers = reader_by_name(validate_save(career_save))
    assert observed_by_gate(readers["clubs"]) == {
        "clubs_minimum": 2,
        "team_lists_found": 1.0,
        "status_normal": 1.0,
        "status_confirmation": 0.5,
        "affiliate_lists_found": 0.5,
        "affiliate_teams_linked": 1.0,
        "reputation_found": 1.0,
        "reputation_median": 4_000,
    }
    assert observed_by_gate(readers["players"]) == {
        "players_minimum": 2,
        "person_blocks": 0.5,
        "names_resolved": 1.0,
        "relation_sentinel": 0.75,
        "second_nation_qualifier": 0.5,
        "handling_above_finishing": 0.5,
        "outfield_goalkeeper_block_low": 0.0,
        "with_natural_position": 0.5,
        "height_in_range": 0.5,
        "height_median": 140,
        "age_median": 27,
        "aged_in_range": 1.0,
        "condition_sharpness_in_range": 0.5,
        "join_date_valid": 0.5,
        "world_not_above_current": 0.5,
        "home_near_current": 0.5,
        "team_resolved": 0.5,
        "home_grown_club_refs_resolved": 0.5,
    }
    contract_observed = observed_by_gate(readers["contracts"])
    assert contract_observed == {
        "players_with_chain": 0.5,
        "no_contract_in_effect": 0.0,
        "date_marked_chain_records": 0.0,
        "tails_parsed": pytest.approx(2 / 3),
        "tails_without_clause_table": 0.0,
        "clause_terminator": 0.5,
        "contract_head": 0.5,
        "past_dated_tail_ends": 0.5,
        "chain_teams_resolved": pytest.approx(2 / 3),
    }
    assert observed_by_gate(readers["suspensions"]) == {
        "suspension_share_of_players": 0.5,
        "issued_after_clock": 0.5,
    }
    assert readers["managed_clubs"].gates == ()
    assert {name: dict(reader.anomalies) for name, reader in readers.items()} == {
        "clubs": {"unlinked_affiliate_teams": 0},
        "players": {"markerless_players": 1, "unresolved_teams": 1},
        "contracts": {
            "past_dated_tail_ends": 1,
            "unparsed_tails": 1,
            "tails_without_clause_table": 0,
            "date_marked_chain_records": 0,
            "players_without_contract_in_effect": 0,
        },
        "suspensions": {"suspensions_after_clock": 1},
        "managed_clubs": {
            "humans_without_club": 0,
            "club_route_one_unresolved": 0,
            "club_route_two_unresolved": 0,
        },
        "stages": {"walk_gaps": 0, "rejected_competition_ids": 1},
        "competitions": {"database_id_conflicts": 0},
        "fixtures": {
            "stray_records": 0,
            "stray_clusters": 0,
            "strays_without_a_copy": 0,
            "fixtures_without_a_stage": 0,
            "unresolved_stages": 0,
            "unresolved_teams": 0,
            "undated_fixtures": 0,
            "bad_kick_off_slots": 0,
            "neutral_venue_votes": 0,
        },
    }


def test_a_human_manager_between_jobs_reports_an_anomaly_and_stays_ok(tmp_path: Path) -> None:
    fragment_path = write_counted_fragment(
        tmp_path,
        humans=humans_body(count=1, selector=MANAGER_SELECTOR + 7),
        summary=career_summary(linked=False),
    )
    with fmsave.open(fragment_path) as career_save:
        assert len(career_save.managed_clubs()) == 0
        readers = reader_by_name(validate_save(career_save))
    managed = readers["managed_clubs"]
    assert managed.status == "ok"
    assert managed.record_count == 0
    assert managed.gates == ()
    assert dict(managed.anomalies) == {
        "humans_without_club": 1,
        "club_route_one_unresolved": 1,
        "club_route_two_unresolved": 1,
    }


def test_to_json_dict_holds_exactly_the_allowlisted_keys(counted_fragment_path: Path) -> None:
    with fmsave.open(counted_fragment_path) as career_save:
        json_dict = validate_save(career_save).to_json_dict()
    assert set(json_dict) == REPORT_KEYS
    reader_dicts = json_dict["readers"]
    assert isinstance(reader_dicts, list)
    assert len(reader_dicts) == len(READER_ORDER)
    for reader_dict in reader_dicts:
        assert isinstance(reader_dict, dict)
        assert set(reader_dict) == READER_KEYS
        for gate_dict in reader_dict["gates"]:
            assert set(gate_dict) == GATE_KEYS


def test_the_json_report_holds_no_names_or_uids(counted_fragment_path: Path) -> None:
    with fmsave.open(counted_fragment_path) as career_save:
        report_text = json.dumps(validate_save(career_save).to_json_dict())
    for private_text in (
        "Alex",
        "Northbridge",
        "Example",
        "Private Folder",
        FILE_NAME,
        str(PLAYER_A_UID),
        str(NORTHBRIDGE_UID),
    ):
        assert private_text not in report_text


def test_a_failing_reader_is_reported_failed_and_the_others_still_run(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_evaluate_clubs(
        stats: ClubStats, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        return (failing_gate("status_confirmation"),)

    monkeypatch.setattr(checks, "evaluate_clubs", failing_evaluate_clubs)
    with fmsave.open(counted_fragment_path) as career_save:
        with pytest.raises(fmsave.ReaderCheckError, match="^clubs failed checks: "):
            career_save.clubs()
        assert CLUBS_TABLE_CACHE_KEY not in career_save._context._cache
        report = validate_save(career_save)
    readers = reader_by_name(report)
    assert readers["clubs"].status == "failed"
    assert readers["clubs"].gates == (failing_gate("status_confirmation"),)
    assert readers["clubs"].record_count == 2
    assert dict(readers["clubs"].coverage) == {}
    for reader_name in (
        "players",
        "contracts",
        "suspensions",
        "managed_clubs",
        "stages",
        "competitions",
        "fixtures",
    ):
        assert readers[reader_name].status == "ok"


def test_a_failing_contract_check_fails_the_shared_player_pass_and_caches_nothing(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluations: list[int] = []

    def failing_evaluate_contracts(
        stats: ContractStats, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        evaluations.append(stats.chain_records)
        return (failing_gate("tails_parsed"),)

    monkeypatch.setattr(checks, "evaluate_contracts", failing_evaluate_contracts)
    with fmsave.open(counted_fragment_path) as career_save:
        for read_table in (career_save.players, career_save.contracts, career_save.suspensions):
            with pytest.raises(fmsave.ReaderCheckError) as error_info:
                read_table()
            assert str(error_info.value) == (
                "contracts failed checks: tails_parsed=0.5 (expected 0.9..). "
                f"Please report it at {ISSUES_URL} with the output of fmsave validate."
            )
            for cache_key in (
                PLAYERS_TABLE_CACHE_KEY,
                CONTRACTS_TABLE_CACHE_KEY,
                SUSPENSIONS_TABLE_CACHE_KEY,
            ):
                assert cache_key not in career_save._context._cache
        assert len(evaluations) == 3
        report = validate_save(career_save)
    assert len(evaluations) == 4
    readers = reader_by_name(report)
    assert {name: reader.status for name, reader in readers.items()} == {
        "clubs": "ok",
        "players": "failed",
        "contracts": "failed",
        "suspensions": "failed",
        "managed_clubs": "ok",
        "stages": "ok",
        "competitions": "ok",
        "fixtures": "ok",
    }
    assert readers["contracts"].gates == (failing_gate("tails_parsed"),)
    assert tuple(gate.name for gate in readers["players"].gates) == PLAYER_GATE_NAMES
    assert readers["players"].record_count == 2
    assert dict(readers["players"].anomalies) == {"markerless_players": 1, "unresolved_teams": 1}


def test_a_reader_error_is_reported_without_its_message(tmp_path: Path) -> None:
    truncated_humans = section_body(".dat", 21, b"")
    fragment_path = write_counted_fragment(tmp_path, humans=truncated_humans)
    with fmsave.open(fragment_path) as career_save:
        with pytest.raises(fmsave.CorruptSaveError):
            career_save.managed_clubs()
        report = validate_save(career_save)
    managed = reader_by_name(report)["managed_clubs"]
    assert managed == ReaderValidation("managed_clubs", "error", None, (), {}, {})
    assert "humans" not in json.dumps(managed.to_json_dict())


def test_validation_reports_survive_pickle_and_deepcopy(counted_fragment_path: Path) -> None:
    with fmsave.open(counted_fragment_path) as career_save:
        report = validate_save(career_save)
    assert pickle.loads(pickle.dumps(report)) == report
    assert copy.deepcopy(report) == report
    gate_result = report.readers[0].gates[0]
    assert pickle.loads(pickle.dumps(gate_result)) == gate_result


def test_validate_save_on_a_closed_save_raises_save_closed_error(
    counted_fragment_path: Path,
) -> None:
    career_save = fmsave.open(counted_fragment_path)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        validate_save(career_save)


def with_bounds(monkeypatch: pytest.MonkeyPatch, bounds: GateBounds) -> None:
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: bounds)


def test_gates_apply_at_full_size_and_fail_on_the_fragment_counts(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture gates judge the span, which has a size threshold of its own, so both are
    # lowered here; otherwise those gates would be the one set this test never applies.
    with_bounds(
        monkeypatch,
        dataclasses.replace(
            BOUNDS, minimum_applies_from_bytes=0, span_minimum_applies_from_bytes=0
        ),
    )
    with fmsave.open(counted_fragment_path) as career_save:
        readers = reader_by_name(validate_save(career_save))
    assert all(gate.applied for reader in readers.values() for gate in reader.gates)
    assert {name: reader.status for name, reader in readers.items()} == {
        "clubs": "failed",
        "players": "failed",
        "contracts": "failed",
        "suspensions": "failed",
        "managed_clubs": "ok",
        "stages": "failed",
        "competitions": "failed",
        # This fragment's span holds no fixture record at all, which has to fail once the
        # gates apply rather than report a career with no matches.
        "fixtures": "failed",
    }
    assert {name: failed_gate_names(reader.gates) for name, reader in readers.items()} == {
        "clubs": ["clubs_minimum", "status_confirmation", "reputation_median"],
        "players": [
            "players_minimum",
            "person_blocks",
            "relation_sentinel",
            "second_nation_qualifier",
            "handling_above_finishing",
            "outfield_goalkeeper_block_low",
            "with_natural_position",
            "height_in_range",
            "height_median",
            "condition_sharpness_in_range",
            "world_not_above_current",
            "home_near_current",
            "team_resolved",
            "home_grown_club_refs_resolved",
        ],
        # The fragment's parsed tails all have a clause table, no record is marked with a
        # date, and its one chain has a record in effect, so those three gates still pass.
        "contracts": [
            name
            for name in CONTRACT_GATE_NAMES
            if name
            not in {
                "tails_without_clause_table",
                "date_marked_chain_records",
                "no_contract_in_effect",
            }
        ],
        "suspensions": list(SUSPENSION_GATE_NAMES),
        "managed_clubs": [],
        # The example table is a fraction of a career's, and names three competitions.
        "stages": ["stage_rows_minimum"],
        # This fragment writes no id-pair records at all, so no competition has a database id,
        # and with none there is no share of them to name: the last gate fails for want of a
        # rate rather than because a name went astray.
        "competitions": [
            "competitions_minimum",
            "competition_database_ids_mapped",
            "competition_names_within_database_ids",
        ],
        # An empty calendar misses the record floor, holds no stray to separate from it, and
        # leaves all three shares without a denominator, so every fixture gate fails instead
        # of passing for want of a rate.
        "fixtures": [
            "fixtures_minimum",
            "fixture_cluster_share",
            "fixture_strays_minimum",
            "fixture_stage_resolved",
            "fixture_teams_resolved",
        ],
    }


def test_the_counted_ranges_come_from_the_gate_bounds(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_bounds(
        monkeypatch,
        dataclasses.replace(
            BOUNDS,
            height_range_cm=(130, 210),
            age_range_years=(28, 45),
            home_reputation_window=2_500,
            condition_sharpness_maximum=12_000,
            goalkeeper_block_low_maximum=50,
        ),
    )
    with fmsave.open(counted_fragment_path) as career_save:
        observed = observed_by_gate(reader_by_name(validate_save(career_save))["players"])
    assert observed["height_in_range"] == 1.0
    assert observed["aged_in_range"] == 0.0
    assert observed["home_near_current"] == 1.0
    assert observed["condition_sharpness_in_range"] == 1.0
    # Only the outfield player counts: both of his goalkeeper-block bytes are at the maximum.
    assert observed["outfield_goalkeeper_block_low"] == 1.0


def test_the_goalkeeper_block_gate_leaves_out_players_rated_as_natural_goalkeepers(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Player A is rated 18 in goal with raw handling above 50; raising the natural rating to 19
    # counts him as an outfield player whose goalkeeper block is not low.
    with_bounds(
        monkeypatch,
        dataclasses.replace(BOUNDS, goalkeeper_block_low_maximum=50, natural_goalkeeper_rating=19),
    )
    with fmsave.open(counted_fragment_path) as career_save:
        observed = observed_by_gate(reader_by_name(validate_save(career_save))["players"])
    assert observed["outfield_goalkeeper_block_low"] == 0.5


def test_status_confirmation_reads_its_position_from_the_status_layout() -> None:
    game_db = counted_game_db()
    layouts = find_club_layouts(GAME_DB_SCHEMA, "")
    assert read_club_index(game_db, layouts, FILE_NAME).stats.status_confirmed == 1
    shifted_statuses: ClubStatusLayout = dataclasses.replace(
        layouts.statuses, confirmation_offset=layouts.statuses.confirmation_offset + 1
    )
    shifted_layouts = dataclasses.replace(layouts, statuses=shifted_statuses)
    assert read_club_index(game_db, shifted_layouts, FILE_NAME).stats.status_confirmed == 0


def test_two_failing_readers_of_the_player_pass_are_named_in_one_error(
    counted_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_evaluate_contracts(
        stats: ContractStats, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        return (failing_gate("tails_parsed"),)

    def failing_evaluate_suspensions(
        stats: SuspensionStats, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        return (failing_gate("issued_after_clock"),)

    monkeypatch.setattr(checks, "evaluate_contracts", failing_evaluate_contracts)
    monkeypatch.setattr(checks, "evaluate_suspensions", failing_evaluate_suspensions)
    with (
        fmsave.open(counted_fragment_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.players()
    assert str(error_info.value) == (
        "contracts failed checks: tails_parsed=0.5 (expected 0.9..). "
        "suspensions failed checks: issued_after_clock=0.5 (expected 0.9..). "
        f"Please report it at {ISSUES_URL} with the output of fmsave validate."
    )
