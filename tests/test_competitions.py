from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import fmsave
import fmsave._context as context_module
from fmsave._checks import GateResult, evaluate_competitions
from fmsave._container import ContainerIndex
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import CompetitionStats
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.competitions import (
    build_competition_index,
    find_competition_id_pair_layout,
    locate_competition_database_ids,
)
from fmsave.readers.stages import StageIndex, find_stage_layout, read_stage_index
from tests.fixtures.career import (
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    NON_COMPETITION_DATABASE_ID,
    NON_COMPETITION_ENTITY_ID,
    SECOND_COMPETITION_DATABASE_ID,
    SECOND_COMPETITION_ID,
    THIRD_COMPETITION_DATABASE_ID,
    THIRD_COMPETITION_ID,
    career_competition_id_pairs,
    career_stage_rows,
)
from tests.fixtures.game_db import (
    COMPETITION_ID_PAIR_CONSTANTS,
    COMPETITION_ID_PAIR_RECORD_OFFSET,
    competition_id_pair_bytes,
    stage_table_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 300 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
COMPETITION_GATE_NAMES = (
    "competitions_minimum",
    "competition_database_ids_mapped",
    "competition_database_id_conflicts",
    "competition_names_within_database_ids",
)
# A database id no record of the example save carries, for the record that contradicts one.
CONTRADICTING_DATABASE_ID = 55_555
# One byte short of the marker the format writes, so no marker is found at all.
SHORT_MARKER = b"\xff" * 15 + b"\x01"
# The lowest entity id the layout rejects, one past the highest it accepts.
ENTITY_ID_LIMIT = 200_000

ID_PAIR_LAYOUT = find_competition_id_pair_layout(GAME_DB_SCHEMA, "")
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout


def example_stage_index() -> StageIndex:
    return read_stage_index(
        stage_table_bytes(career_stage_rows()), find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME
    )


def healthy_competition_stats() -> CompetitionStats:
    """Counts with every rate comfortably inside its bound."""
    return CompetitionStats(
        competitions=2_600,
        with_database_id=2_380,
        database_id_conflicts=0,
        with_name=0,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def test_the_locator_reads_every_id_pair_record() -> None:
    """The records pair entities of the stage id space, competitions among them.

    The fixture writes the constant bytes from its own copy of them, so the layout and the
    format have to agree on every one: a constant the layout invented, or one it dropped a
    value from, leaves these records unrecognised.
    """
    assert ID_PAIR_LAYOUT.constant_bytes == COMPETITION_ID_PAIR_CONSTANTS

    database_ids = locate_competition_database_ids(career_competition_id_pairs(), ID_PAIR_LAYOUT)

    assert database_ids == {
        FIRST_COMPETITION_ID: FIRST_COMPETITION_DATABASE_ID,
        SECOND_COMPETITION_ID: SECOND_COMPETITION_DATABASE_ID,
        THIRD_COMPETITION_ID: THIRD_COMPETITION_DATABASE_ID,
        NON_COMPETITION_ENTITY_ID: NON_COMPETITION_DATABASE_ID,
    }


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            competition_id_pair_bytes(
                entity_id=FIRST_COMPETITION_ID,
                database_id=FIRST_COMPETITION_DATABASE_ID,
                database_id_copy=FIRST_COMPETITION_DATABASE_ID + 1,
            ),
            id="database-id-not-repeated",
        ),
        pytest.param(
            competition_id_pair_bytes(entity_id=0, database_id=FIRST_COMPETITION_DATABASE_ID),
            id="entity-id-zero",
        ),
        pytest.param(
            competition_id_pair_bytes(
                entity_id=ENTITY_ID_LIMIT, database_id=FIRST_COMPETITION_DATABASE_ID
            ),
            id="entity-id-past-the-limit",
        ),
        pytest.param(
            competition_id_pair_bytes(
                entity_id=FIRST_COMPETITION_ID,
                database_id=FIRST_COMPETITION_DATABASE_ID,
                marker_bytes=SHORT_MARKER,
            ),
            id="marker-one-byte-short",
        ),
    ],
)
def test_a_record_breaking_one_recognition_test_is_not_accepted(record: bytes) -> None:
    """Each test a record is recognised by carries its own weight.

    The marker alone hits about ten times as often as a record occurs, so dropping any one of
    these tests would let bytes that are not a record pair an id with a database id.
    """
    assert locate_competition_database_ids(record, ID_PAIR_LAYOUT) == {}


@pytest.mark.parametrize(
    "constant_offset",
    [
        pytest.param(-8, id="in-front-of-the-record"),
        pytest.param(15, id="just-past-the-three-words"),
        pytest.param(60, id="at-the-far-end-of-the-record"),
    ],
)
def test_a_record_breaking_one_constant_byte_is_not_accepted(constant_offset: int) -> None:
    """Three constants named here rather than taken from the layout, so one the layout drops
    fails this as well as the comparison above.

    The last two are of the six that reject one record per save: a record breaking six
    independent constants at once is not one the save paired, and keeping the database id read
    from it would name the wrong competition rather than leave that one unnamed.
    """
    record = bytearray(
        competition_id_pair_bytes(
            entity_id=FIRST_COMPETITION_ID, database_id=FIRST_COMPETITION_DATABASE_ID
        )
    )
    position = COMPETITION_ID_PAIR_RECORD_OFFSET + constant_offset
    record[position] = (record[position] + 1) % 256

    assert locate_competition_database_ids(bytes(record), ID_PAIR_LAYOUT) == {}


def test_an_entity_two_records_disagree_about_is_left_out() -> None:
    """Two database ids for one entity are no evidence for either, so neither is kept."""
    contradicted = career_competition_id_pairs() + competition_id_pair_bytes(
        entity_id=SECOND_COMPETITION_ID, database_id=CONTRADICTING_DATABASE_ID
    )
    repeated = career_competition_id_pairs() + competition_id_pair_bytes(
        entity_id=SECOND_COMPETITION_ID, database_id=SECOND_COMPETITION_DATABASE_ID
    )

    from_contradicted = locate_competition_database_ids(contradicted, ID_PAIR_LAYOUT)
    from_repeated = locate_competition_database_ids(repeated, ID_PAIR_LAYOUT)

    assert SECOND_COMPETITION_ID not in from_contradicted
    assert from_contradicted[FIRST_COMPETITION_ID] == FIRST_COMPETITION_DATABASE_ID
    # A second record that agrees with the first is not a disagreement.
    assert from_repeated[SECOND_COMPETITION_ID] == SECOND_COMPETITION_DATABASE_ID


def test_the_index_fills_the_database_ids_and_counts_what_the_gates_divide() -> None:
    """Only the ids the stage table calls competitions are taken out of the entity map."""
    database_ids = locate_competition_database_ids(career_competition_id_pairs(), ID_PAIR_LAYOUT)

    competition_index = build_competition_index(example_stage_index(), database_ids, {})

    assert competition_index.competition_by_id[FIRST_COMPETITION_ID].database_id == (
        FIRST_COMPETITION_DATABASE_ID
    )
    assert competition_index.database_id_by_competition_id == {
        FIRST_COMPETITION_ID: FIRST_COMPETITION_DATABASE_ID,
        SECOND_COMPETITION_ID: SECOND_COMPETITION_DATABASE_ID,
        THIRD_COMPETITION_ID: THIRD_COMPETITION_DATABASE_ID,
    }
    # The entity the stage table never calls a competition is mapped, and is not a competition.
    assert NON_COMPETITION_ENTITY_ID in database_ids
    assert NON_COMPETITION_ENTITY_ID not in competition_index.competition_by_id
    assert competition_index.stats == CompetitionStats(
        competitions=3,
        with_database_id=3,
        database_id_conflicts=0,
        with_name=0,
    )


def test_a_database_id_two_competitions_claim_names_neither() -> None:
    """Nothing says which of the two it belongs to, and a wrong one would name the wrong
    competition, so both are left with none and both are counted.
    """
    competition_index = build_competition_index(
        example_stage_index(),
        {
            FIRST_COMPETITION_ID: FIRST_COMPETITION_DATABASE_ID,
            SECOND_COMPETITION_ID: THIRD_COMPETITION_DATABASE_ID,
            THIRD_COMPETITION_ID: THIRD_COMPETITION_DATABASE_ID,
        },
        {
            FIRST_COMPETITION_DATABASE_ID: "Example League",
            THIRD_COMPETITION_DATABASE_ID: "Example Cup",
        },
    )

    assert competition_index.competition_by_id[SECOND_COMPETITION_ID].database_id is None
    assert competition_index.competition_by_id[THIRD_COMPETITION_ID].database_id is None
    assert competition_index.name_for(SECOND_COMPETITION_ID) is None
    assert competition_index.name_for(FIRST_COMPETITION_ID) == "Example League"
    assert competition_index.stats.with_database_id == 1
    assert competition_index.stats.with_name == 1
    assert competition_index.stats.database_id_conflicts == 2


def test_competitions_carry_their_database_ids_and_never_a_name(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        competitions_table = career_save.competitions()

    assert [competition.database_id for competition in competitions_table] == [
        FIRST_COMPETITION_DATABASE_ID,
        SECOND_COMPETITION_DATABASE_ID,
        THIRD_COMPETITION_DATABASE_ID,
    ]
    # No save stores a competition name, so every row is unnamed until a map is supplied.
    assert all(competition.name is None for competition in competitions_table)
    assert NON_COMPETITION_ENTITY_ID not in {competition.id for competition in competitions_table}


def test_a_cold_competitions_read_decompresses_game_db_once(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stage table and the id-pair records are read from one borrow of the same bytes.

    The section is decompressed where the loan starts, so counting the reads counts the
    decompressions: a reader that opened its own borrow for each of the two would pay twice.
    """
    sections_read: list[str] = []
    read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        sections_read.append(name)
        return read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)

    with fmsave.open(career_save_path) as career_save:
        competitions_table = career_save.competitions()

    assert len(competitions_table) == 3
    assert sections_read.count(GAME_DB_SECTION) == 1


def test_healthy_competition_stats_pass_every_gate() -> None:
    results = evaluate_competitions(healthy_competition_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert tuple(result.name for result in results) == COMPETITION_GATE_NAMES
    assert all(result.applied and result.passed for result in results)


@pytest.mark.parametrize(
    ("stat_changes", "expected_failures"),
    [
        pytest.param(
            {"with_database_id": 1_560}, ["competition_database_ids_mapped"], id="few-mapped"
        ),
        # Four competitions in five, which a save the records pair normally never falls to.
        pytest.param(
            {"with_database_id": 2_080},
            ["competition_database_ids_mapped"],
            id="mapped-a-little-under-the-bound",
        ),
        pytest.param({"with_database_id": 2_262}, [], id="mapped-inside-the-bound"),
        pytest.param(
            {"database_id_conflicts": 6},
            ["competition_database_id_conflicts"],
            id="too-many-conflicts",
        ),
    ],
)
def test_the_competition_gates_fail_one_at_a_time(
    stat_changes: dict[str, int], expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(healthy_competition_stats(), **stat_changes)

    results = evaluate_competitions(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(results) == expected_failures


def test_a_name_that_escaped_the_database_ids_fails_the_gate() -> None:
    """A name arrives only through a database id, so more names than database ids is a fault.

    It is what naming a competition the save left without a database id looks like from the
    counts: the id-pair records disagreed about it, or a second competition claims the same
    database id, and naming it anyway would put a different competition's name on it.
    """
    escaped_names = dataclasses.replace(
        healthy_competition_stats(), with_database_id=2_380, with_name=2_381
    )

    results = evaluate_competitions(escaped_names, BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(results) == ["competition_names_within_database_ids"]
    named_gate = results[COMPETITION_GATE_NAMES.index("competition_names_within_database_ids")]
    assert named_gate.applied
    assert named_gate.observed is not None
    assert named_gate.observed > 1.0


def test_a_small_game_db_applies_no_competition_gate() -> None:
    """A fragment cannot meet full-save counts, so the gates judge nothing."""
    broken_stats = dataclasses.replace(
        healthy_competition_stats(), with_database_id=0, database_id_conflicts=2_600
    )

    results = evaluate_competitions(broken_stats, BOUNDS, SMALL_GAME_DB_BYTES)

    assert all(not result.applied and result.passed for result in results)
