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
from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, GateBounds, find_layout
from fmsave._save import (
    CLUBS_TABLE_CACHE_KEY,
    CONTRACTS_TABLE_CACHE_KEY,
    PLAYERS_TABLE_CACHE_KEY,
    SUSPENSIONS_TABLE_CACHE_KEY,
)
from fmsave._status import registered_statuses
from fmsave.checks import (
    ClubStats,
    ContractStats,
    GateResult,
    ManagedStats,
    PlayerStats,
    ReaderValidation,
    SuspensionStats,
    ValidationReport,
    check_managed,
    enforce,
    enforce_checks,
    evaluate_clubs,
    evaluate_contracts,
    evaluate_managed,
    evaluate_players,
    evaluate_suspensions,
    validate_save,
)
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    save_summary_body,
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
    "with_natural_position",
    "height_in_150_210",
    "height_median",
    "age_median",
    "aged_14_to_45",
    "condition_sharpness_in_range",
    "join_date_valid",
    "world_not_above_current",
    "home_within_1000_of_current",
    "team_resolved",
    "home_grown_club_refs_resolved",
)
CONTRACT_GATE_NAMES = (
    "players_with_chain",
    "tails_parsed",
    "clause_terminator",
    "contract_head",
    "past_dated_tail_ends",
    "chain_teams_resolved",
)
CLUB_GATE_NAMES = ("clubs_minimum", "team_lists_found", "status_normal", "status_confirmation")
SUSPENSION_GATE_NAMES = ("suspension_share_of_players", "issued_after_clock")
MANAGED_GATE_NAMES = ("route_one_resolved", "route_two_resolved")

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
READER_ORDER = ("clubs", "players", "contracts", "suspensions", "managed_clubs")


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
        with_natural_position=records,
        height_in_150_210=records,
        condition_sharpness_in_range=records,
        with_valid_join_date=records // 2,
        world_not_above_current=records,
        home_within_1000_of_current=records,
        with_team=records // 2,
        team_resolved=records // 2,
        aged_14_to_45=records,
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
        chain_records=25_000,
        tails_parsed=24_000,
        clause_tables=24_000,
        clause_terminator_ok=24_000,
        head_ok=22_800,
        tail_ends_past=5,
        chain_teams_resolved=24_950,
    )


def healthy_club_stats() -> ClubStats:
    return ClubStats(
        records=50_000, team_lists_found=50_000, status_normal=49_950, status_confirmed_a18=49_500
    )


def healthy_suspension_stats() -> SuspensionStats:
    return SuspensionStats(
        players=20_000, entries=110, players_with_entries=100, issued_after_clock=0
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def test_gate_switch_is_on_by_default() -> None:
    assert checks._GATES_ENABLED is True
    shifted_results = evaluate_players(
        dataclasses.replace(healthy_player_stats(), handling_above_finishing=12_200),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    with pytest.raises(fmsave.ReaderCheckError):
        enforce("players", shifted_results)


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
        "players failed checks: handling_above_finishing=0.61 (expected 0.15..0.35); "
        "with_natural_position=0.89 (expected 0.97..). "
        f"Please report it at {ISSUES_URL} with the output of fmsave validate."
    )


def test_one_record_short_of_the_minimum_fails_only_the_players_minimum_gate() -> None:
    results = evaluate_players(healthy_player_stats(9_999), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["players_minimum"]
    minimum_result = results[0]
    assert minimum_result == GateResult("players_minimum", 9_999, 10_000, None, False, True)
    with pytest.raises(
        fmsave.ReaderCheckError, match=r"players_minimum=9999 \(expected 10000\.\.\)"
    ):
        enforce("players", results)


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


def test_too_few_parsed_tails_fail_the_contract_gates() -> None:
    stats = dataclasses.replace(
        healthy_contract_stats(),
        tails_parsed=21_000,
        clause_tables=21_000,
        clause_terminator_ok=21_000,
        head_ok=19_950,
    )
    results = evaluate_contracts(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["tails_parsed"]
    assert results[CONTRACT_GATE_NAMES.index("tails_parsed")].observed == pytest.approx(0.84)


def test_too_many_past_dated_tail_ends_fail_the_contract_gates() -> None:
    stats = dataclasses.replace(healthy_contract_stats(), tail_ends_past=264)
    results = evaluate_contracts(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["past_dated_tail_ends"]
    with pytest.raises(
        fmsave.ReaderCheckError,
        match=re.escape("contracts failed checks: past_dated_tail_ends=0.011 (expected ..0.01)."),
    ):
        enforce("contracts", results)


def test_club_gates_pass_healthy_stats_and_fail_below_the_club_minimum() -> None:
    results = evaluate_clubs(healthy_club_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == CLUB_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    few_clubs = ClubStats(
        records=4_999, team_lists_found=4_999, status_normal=4_990, status_confirmed_a18=4_950
    )
    assert failed_gate_names(evaluate_clubs(few_clubs, BOUNDS, FULL_SIZE_GAME_DB_BYTES)) == [
        "clubs_minimum"
    ]


def test_a_suspension_issued_after_the_clock_fails() -> None:
    healthy_results = evaluate_suspensions(
        healthy_suspension_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    assert tuple(result.name for result in healthy_results) == SUSPENSION_GATE_NAMES
    assert all(result.applied and result.passed for result in healthy_results)
    late_stats = dataclasses.replace(healthy_suspension_stats(), issued_after_clock=1)
    results = evaluate_suspensions(late_stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(results) == ["issued_after_clock"]
    assert results[1] == GateResult("issued_after_clock", 1, 0, 0, False, True)


def test_the_suspension_share_is_not_applied_without_players() -> None:
    no_players = SuspensionStats(players=0, entries=0, players_with_entries=0, issued_after_clock=0)
    share_result, clock_result = evaluate_suspensions(no_players, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert share_result == GateResult(
        "suspension_share_of_players", None, 0.0005, 0.03, True, False
    )
    assert clock_result.applied and clock_result.passed


def test_a_human_manager_without_a_club_is_an_anomaly_not_a_failure() -> None:
    stats = ManagedStats(human_count=1, route_one_resolved=0, route_two_resolved=0, rows=0)
    results = evaluate_managed(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert results == (
        GateResult("route_one_resolved", 0, None, None, True, True),
        GateResult("route_two_resolved", 0, None, None, True, True),
    )
    reader_check = check_managed(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert reader_check.reader == "managed_clubs"
    assert reader_check.record_count == 0
    assert dict(reader_check.anomalies) == {"humans_without_club": 1}
    enforce_checks((reader_check,))
    with_club = ManagedStats(human_count=1, route_one_resolved=1, route_two_resolved=1, rows=1)
    assert dict(check_managed(with_club, BOUNDS, FULL_SIZE_GAME_DB_BYTES).anomalies) == {
        "humans_without_club": 0
    }


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
    for number_text in ("0.6172", "0.15", "0.35", "0.89", "0.97"):
        assert number_text in remainder
        remainder = remainder.replace(number_text, "")
    assert re.search(r"\d", remainder) is None
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


# A fragment whose readers see known counts: two clubs, two players, a human manager.
NORTHBRIDGE_UID = 5001
NORTHBRIDGE_TEAM_A = 70001
NORTHBRIDGE_TEAM_B = 70002
SOUTHPORT_UID = 5002
SOUTHPORT_TEAM = 70003
UNREGISTERED_TEAM_ID = 79999
PLAYER_A_UID = 900001
PLAYER_B_UID = 900002
MANAGER_SELECTOR = 500
MANAGER_NAME = "Alex Manager"
HANDLING_INDEX = 19
FINISHING_INDEX = 2
SUMMARY_SCHEMA = 29


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


def manager_region() -> bytes:
    person_header = struct.pack("<III", MANAGER_SELECTOR - 1, 777001, 777001)
    chain_record, _tag_offset = contract_bytes(
        selector=MANAGER_SELECTOR,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=4000,
        start=packed_date(183, 2029),
        tail={"end": packed_date(182, 2032), "status": 3},
        head={"type": 1},
    )
    return person_header + bytes(64) + chain_record + bytes(64)


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
        clauses=((250000, 365, 0x11),),
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
    raw_attributes = [50] * 54
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
        raw_attributes=[50] * 54,
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
        + manager_region()
        + player_a_bytes()
        + player_b_bytes()
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def linked_summary() -> bytes:
    return save_summary_body(
        leading_strings=("Example League",),
        trailing_strings=("Example Cup", MANAGER_NAME),
        club_uid_after=("Northbridge", NORTHBRIDGE_UID),
    )


UNLINKED_SUMMARY = save_summary_body(
    leading_strings=("Example League",),
    trailing_strings=("Example Cup", MANAGER_NAME, "Northbridge"),
)


def write_counted_fragment(
    tmp_path: Path, *, humans: bytes | None = None, summary: bytes | None = None
) -> Path:
    replacements = {
        "game_db": counted_game_db(),
        "humans": humans_body(count=1, selector=MANAGER_SELECTOR) if humans is None else humans,
        "save_game_summary": linked_summary() if summary is None else summary,
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
    assert tuple(gate.name for gate in readers["managed_clubs"].gates) == MANAGED_GATE_NAMES
    assert {name: reader.record_count for name, reader in readers.items()} == {
        "clubs": 2,
        "players": 2,
        "contracts": 1,
        "suspensions": 2,
        "managed_clubs": 1,
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
    }
    assert observed_by_gate(readers["players"]) == {
        "players_minimum": 2,
        "person_blocks": 0.5,
        "names_resolved": 1.0,
        "relation_sentinel": 0.75,
        "second_nation_qualifier": 0.5,
        "handling_above_finishing": 0.5,
        "with_natural_position": 0.5,
        "height_in_150_210": 0.5,
        "height_median": 140,
        "age_median": 27,
        "aged_14_to_45": 1.0,
        "condition_sharpness_in_range": 0.5,
        "join_date_valid": 0.5,
        "world_not_above_current": 0.5,
        "home_within_1000_of_current": 0.5,
        "team_resolved": 0.5,
        "home_grown_club_refs_resolved": 0.5,
    }
    contract_observed = observed_by_gate(readers["contracts"])
    assert contract_observed == {
        "players_with_chain": 0.5,
        "tails_parsed": pytest.approx(2 / 3),
        "clause_terminator": 0.5,
        "contract_head": 0.5,
        "past_dated_tail_ends": 0.5,
        "chain_teams_resolved": pytest.approx(2 / 3),
    }
    assert observed_by_gate(readers["suspensions"]) == {
        "suspension_share_of_players": 0.5,
        "issued_after_clock": 1,
    }
    assert observed_by_gate(readers["managed_clubs"]) == {
        "route_one_resolved": 1,
        "route_two_resolved": 1,
    }
    assert {name: dict(reader.anomalies) for name, reader in readers.items()} == {
        "clubs": {},
        "players": {"markerless_players": 1, "unresolved_teams": 1},
        "contracts": {"past_dated_tail_ends": 1, "unparsed_tails": 1},
        "suspensions": {"suspensions_after_clock": 1},
        "managed_clubs": {"humans_without_club": 0},
    }


def test_a_human_manager_between_jobs_reports_an_anomaly_and_stays_ok(tmp_path: Path) -> None:
    fragment_path = write_counted_fragment(
        tmp_path,
        humans=humans_body(count=1, selector=MANAGER_SELECTOR + 7),
        summary=UNLINKED_SUMMARY,
    )
    with fmsave.open(fragment_path) as career_save:
        assert len(career_save.managed_clubs()) == 0
        readers = reader_by_name(validate_save(career_save))
    managed = readers["managed_clubs"]
    assert managed.status == "ok"
    assert managed.record_count == 0
    assert observed_by_gate(managed) == {"route_one_resolved": 0, "route_two_resolved": 0}
    assert dict(managed.anomalies) == {"humans_without_club": 1}


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


def failing_gate(name: str) -> GateResult:
    return GateResult(name, 0.5, 0.9, None, False, True)


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
    for reader_name in ("players", "contracts", "suspensions", "managed_clubs"):
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
