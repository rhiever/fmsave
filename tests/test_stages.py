from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

import fmsave
from fmsave import Table
from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, GateBounds, find_layout
from fmsave._reader_stats import CompetitionStats, StageStats
from fmsave._save import COMPETITIONS_TABLE_CACHE_KEY, STAGES_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.checks import (
    GateResult,
    check_competitions,
    check_stages,
    enforce,
    evaluate_competitions,
    evaluate_stages,
)
from fmsave.export import column_names
from fmsave.models.common import CodedValue
from fmsave.models.competitions import Competition, CompetitionRound, Stage
from fmsave.readers.competitions import build_competition_index
from fmsave.readers.stages import StageIndex, find_stage_layout, read_stage_index
from tests.fixtures.career import (
    FIRST_COMPETITION_ID,
    GROUPED_STAGE_GROUP_ID,
    OUT_OF_BAND_COMPETITION_ID,
    SECOND_COMPETITION_ID,
    STAGE_ROW_COUNT,
    THIRD_COMPETITION_ID,
    career_stage_rows,
)
from tests.fixtures.game_db import (
    STAGE_MISSING_VALUE,
    STAGE_ROW_LENGTH,
    STAGE_TABLE_TRAILING_BYTES,
    stage_row_bytes,
    stage_table_bytes,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 300 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
STAGE_GATE_NAMES = (
    "stage_rows_minimum",
    "stage_walk_gaps",
    "stage_ids_ascending",
    "stage_rows_with_competition",
    "stage_trailing_sentinel",
    "stage_table_tail_bytes",
)
COMPETITION_GATE_NAMES = (
    "competitions_minimum",
    "competition_database_ids_mapped",
    "competition_database_id_conflicts",
)

# Rows of the example table that carry distinctive values.
FINAL_STAGE_ID = 1
GROUPED_STAGE_ID = 2
UNNAMED_ROUND_STAGE_ID = 3
EMPTY_STAGE_ID = 4
OUT_OF_BAND_STAGE_ID = 5
FIRST_PLAIN_STAGE_ID = 6
FINAL_ROUND_CODE = 19
SEMI_FINAL_ROUND_CODE = 17
UNNAMED_ROUND_CODE = 77
GROUPED_STAGE_S25 = 3
EMPTY_STAGE_S25 = 22

# Every round code fmsave names, and the member it names it. A code earns a name only where a
# round label the game itself displayed was matched to that exact code.
NAMED_ROUND_CODES = {
    7: CompetitionRound.THIRD_ROUND,
    8: CompetitionRound.FOURTH_ROUND,
    16: CompetitionRound.QUARTER_FINAL,
    17: CompetitionRound.SEMI_FINAL,
    19: CompetitionRound.FINAL,
}
# Codes every save uses that no such label reaches, including ones sitting either side of a
# named code and ones that run consecutively with each other.
UNNAMED_ROUND_CODES = (5, 6, 9, 18, 20, 27, 41, 42, 43, 74, 75, 76, 77, 80, 148, 149, 150)

# A row late in the example table, well past the 200 rows the locator chains to find it.
BROKEN_ROW_STAGE_ID = 210
EXAMPLE_DATABASE_ID = 4001
SECOND_EXAMPLE_DATABASE_ID = 4002


def registered_gate_bounds() -> GateBounds:
    return find_layout(GateBounds, "game_db", GAME_DB_SCHEMA, "").layout


BOUNDS = registered_gate_bounds()


def example_stage_index(rows: list[bytes] | None = None) -> StageIndex:
    table_rows = career_stage_rows() if rows is None else rows
    return read_stage_index(
        stage_table_bytes(table_rows), find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME
    )


def healthy_stage_stats() -> StageStats:
    """Counts with every rate comfortably inside its bound."""
    return StageStats(
        rows=8_000,
        gaps=0,
        ascending_steps=7_999,
        steps=7_999,
        with_competition=7_750,
        competition_id_rejected=1,
        trailing_sentinel_ok=7_900,
        bytes_after_table=650_000,
    )


def healthy_competition_stats() -> CompetitionStats:
    return CompetitionStats(
        competitions=2_600,
        with_database_id=2_380,
        database_id_conflicts=0,
        with_name=0,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def test_the_walk_reads_every_row_and_its_fields() -> None:
    stage_index = example_stage_index()

    assert len(stage_index.stages) == STAGE_ROW_COUNT
    assert stage_index.stats.rows == STAGE_ROW_COUNT
    assert stage_index.stats.gaps == 0
    grouped_stage = stage_index.stage_by_id[GROUPED_STAGE_ID]
    assert grouped_stage.group_id == GROUPED_STAGE_GROUP_ID
    assert grouped_stage.unknown["s25"] == GROUPED_STAGE_S25
    assert grouped_stage.unknown["s29"] == STAGE_MISSING_VALUE
    assert stage_index.stage_by_id[FINAL_STAGE_ID].group_id is None


def test_a_verified_round_code_is_labelled_and_an_unnamed_one_stays_unknown() -> None:
    stage_index = example_stage_index()

    final_round = stage_index.stage_by_id[FINAL_STAGE_ID].round
    assert final_round is not None
    assert final_round.raw == FINAL_ROUND_CODE
    assert final_round.label is CompetitionRound.FINAL
    semi_final_round = stage_index.stage_by_id[GROUPED_STAGE_ID].round
    assert semi_final_round is not None
    assert semi_final_round.label is CompetitionRound.SEMI_FINAL
    unnamed_round = stage_index.stage_by_id[UNNAMED_ROUND_STAGE_ID].round
    assert unnamed_round is not None
    assert unnamed_round.raw == UNNAMED_ROUND_CODE
    assert unnamed_round.label is CompetitionRound.UNKNOWN


def test_a_row_with_no_competition_and_no_round_reads_as_none() -> None:
    empty_stage = example_stage_index().stage_by_id[EMPTY_STAGE_ID]

    assert empty_stage.competition_id is None
    assert empty_stage.round is None
    assert empty_stage.group_id is None
    assert empty_stage.unknown["s25"] == EMPTY_STAGE_S25


def test_a_competition_id_at_the_limit_is_rejected_and_counted() -> None:
    stage_index = example_stage_index()

    assert stage_index.stage_by_id[OUT_OF_BAND_STAGE_ID].competition_id is None
    assert stage_index.stats.competition_id_rejected == 1
    assert OUT_OF_BAND_COMPETITION_ID not in stage_index.stage_ids_by_competition_id


def test_the_competition_joins_go_both_ways() -> None:
    stage_index = example_stage_index()

    assert stage_index.stage_ids_by_competition_id[FIRST_COMPETITION_ID] == (
        FINAL_STAGE_ID,
        GROUPED_STAGE_ID,
    )
    assert stage_index.competition_id_by_stage_id[UNNAMED_ROUND_STAGE_ID] == SECOND_COMPETITION_ID
    assert EMPTY_STAGE_ID not in stage_index.competition_id_by_stage_id
    assert stage_index.stats.with_competition == STAGE_ROW_COUNT - 2


def test_the_previous_stage_id_is_none_only_when_the_row_stores_the_missing_value() -> None:
    stage_index = example_stage_index()

    assert stage_index.stage_by_id[FINAL_STAGE_ID].previous_stage_id is None
    assert stage_index.stage_by_id[GROUPED_STAGE_ID].previous_stage_id == 1


def test_the_walk_resynchronises_over_a_block_of_junk_and_counts_one_gap() -> None:
    """The junk sits after the rows the reader chains to find the table.

    Junk before that point would leave no chain long enough to recognise, and the table would
    not be found at all, so a gap is only ever walked over once the head is known.
    """
    rows = career_stage_rows()
    rows_before_the_junk = 200
    table = (
        stage_table_bytes(rows[:rows_before_the_junk], trailing_bytes=0)
        + b"\xaa" * 40
        + stage_table_bytes(rows[rows_before_the_junk:], leading_bytes=0)
    )

    stage_index = example_stage_index()
    resynchronised = read_stage_index(table, find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME)

    assert resynchronised.stats.gaps == 1
    assert len(resynchronised.stages) == len(stage_index.stages)
    assert [stage.id for stage in resynchronised.stages] == [
        stage.id for stage in stage_index.stages
    ]


def test_a_repeated_stage_id_raises_a_reader_check_error() -> None:
    rows = career_stage_rows()
    rows.append(stage_row_bytes(stage_id=1, competition_id=None, group_id=None, round_code=None))

    with pytest.raises(fmsave.ReaderCheckError, match="appears in two stage rows"):
        read_stage_index(stage_table_bytes(rows), find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME)


def test_a_game_db_with_no_stage_table_raises_a_reader_check_error() -> None:
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        read_stage_index(bytes(4_000), find_stage_layout(GAME_DB_SCHEMA, ""), FILE_NAME)

    message = str(error_info.value)
    assert "no stage table was found" in message
    for fictional_text in ("Alex", "Northbridge", "Example League"):
        assert fictional_text not in message


def test_the_competition_index_lists_one_competition_per_distinct_id() -> None:
    competition_index = build_competition_index(example_stage_index(), {}, {})

    assert [competition.id for competition in competition_index.competitions] == [
        FIRST_COMPETITION_ID,
        SECOND_COMPETITION_ID,
        THIRD_COMPETITION_ID,
    ]
    assert competition_index.competition_by_id[FIRST_COMPETITION_ID].stage_ids == (
        FINAL_STAGE_ID,
        GROUPED_STAGE_ID,
    )
    assert competition_index.competition_by_id[SECOND_COMPETITION_ID].stage_ids == (
        UNNAMED_ROUND_STAGE_ID,
    )
    assert competition_index.competition_by_id[THIRD_COMPETITION_ID].stage_ids == tuple(
        range(FIRST_PLAIN_STAGE_ID, STAGE_ROW_COUNT + 1)
    )
    assert all(
        competition.database_id is None and competition.name is None
        for competition in competition_index.competitions
    )
    assert competition_index.database_id_by_competition_id == {}
    assert competition_index.name_for(FIRST_COMPETITION_ID) is None
    assert competition_index.name_for(None) is None
    assert competition_index.stats.competitions == 3


def test_stages_returns_one_cached_table_of_every_row(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        stages_table = career_save.stages()

        assert isinstance(stages_table, Table)
        assert stages_table.record_type is Stage
        assert career_save.stages() is stages_table
        assert STAGES_TABLE_CACHE_KEY == "table:stages"
    assert len(stages_table) == STAGE_ROW_COUNT
    assert stages_table[0].id == FINAL_STAGE_ID
    assert stages_table[0].competition_name is None


def test_competitions_returns_one_row_per_competition(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        competitions_table = career_save.competitions()

        assert competitions_table.record_type is Competition
        assert career_save.competitions() is competitions_table
        assert COMPETITIONS_TABLE_CACHE_KEY == "table:competitions"
        assert len(career_save.competitions().where(id=SECOND_COMPETITION_ID)) == 1
    assert len(competitions_table) == 3


def test_both_readers_raise_after_close_and_earlier_tables_keep_working(
    career_save_path: Path,
) -> None:
    career_save = fmsave.open(career_save_path)
    stages_table = career_save.stages()
    competitions_table = career_save.competitions()
    rows_before_close = list(stages_table)
    career_save.close()

    for reader_name in ("stages", "competitions"):
        with pytest.raises(fmsave.SaveClosedError):
            getattr(career_save, reader_name)()
    assert list(stages_table) == rows_before_close
    assert len(competitions_table) == 3


def test_records_survive_pickle_and_deepcopy(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        stages_table = career_save.stages()
        competitions_table = career_save.competitions()

    for example in (stages_table[0], stages_table, competitions_table[0], competitions_table):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_export_columns_flatten_the_round_and_the_unknown_words(career_save_path: Path) -> None:
    assert column_names(Stage) == (
        "id",
        "competition_id",
        "competition_name",
        "group_id",
        "round",
        "round_code",
        "previous_stage_id",
        "unknown_s25",
        "unknown_s29",
    )
    assert column_names(Competition) == ("id", "database_id", "name", "stage_ids")

    with fmsave.open(career_save_path) as career_save:
        stages_table = career_save.stages()
        competitions_table = career_save.competitions()

    assert_matches_json_normalize(list(stages_table), Stage)
    assert_matches_json_normalize(list(competitions_table), Competition)
    stage_columns = stages_table.to_columns()
    assert stage_columns["round"][0] == "final"
    assert stage_columns["round_code"][0] == FINAL_ROUND_CODE
    assert stage_columns["round"][UNNAMED_ROUND_STAGE_ID - 1] == "unknown"
    assert stage_columns["round_code"][UNNAMED_ROUND_STAGE_ID - 1] == UNNAMED_ROUND_CODE


def test_field_statuses_follow_the_competition_coverage() -> None:
    for verified_field in ("id", "competition_id", "group_id", "round"):
        assert field_status(Stage, verified_field) == "verified", verified_field
    for unconfirmed_field in ("competition_name", "previous_stage_id", "unknown"):
        assert field_status(Stage, unconfirmed_field) == "unconfirmed", unconfirmed_field
    assert Stage.UNKNOWN_KEYS == ("s25", "s29")
    for verified_field in ("id", "stage_ids"):
        assert field_status(Competition, verified_field) == "verified", verified_field
    for unconfirmed_field in ("database_id", "name"):
        assert field_status(Competition, unconfirmed_field) == "unconfirmed", unconfirmed_field


def test_healthy_stage_stats_pass_every_gate_and_a_small_section_applies_none() -> None:
    results = evaluate_stages(healthy_stage_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == STAGE_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("stages", results)

    small_results = evaluate_stages(healthy_stage_stats(), BOUNDS, SMALL_GAME_DB_BYTES)
    assert all(not result.applied and result.passed for result in small_results)
    broken_stats = dataclasses.replace(healthy_stage_stats(), gaps=9, bytes_after_table=3_000_000)
    assert all(
        not result.applied for result in evaluate_stages(broken_stats, BOUNDS, SMALL_GAME_DB_BYTES)
    )
    assert BOUNDS.minimum_applies_from_bytes == FULL_SAVE_MINIMUM_GAME_DB_BYTES


@pytest.mark.parametrize(
    ("stat_changes", "expected_failures"),
    [
        pytest.param({"gaps": 8}, [], id="gaps-at-edge"),
        pytest.param({"gaps": 9}, ["stage_walk_gaps"], id="gaps-above"),
        pytest.param({"with_competition": 6_400}, ["stage_rows_with_competition"], id="few-joins"),
        pytest.param(
            {"bytes_after_table": 3_000_000}, ["stage_table_tail_bytes"], id="table-too-early"
        ),
        pytest.param({"rows": 999}, ["stage_rows_minimum"], id="too-few-rows"),
        pytest.param({"ascending_steps": 7_000}, ["stage_ids_ascending"], id="ids-not-ascending"),
        pytest.param(
            {"trailing_sentinel_ok": 7_000}, ["stage_trailing_sentinel"], id="sentinel-lost"
        ),
    ],
)
def test_stage_gates_fail_one_at_a_time_with_a_message_naming_the_gate(
    stat_changes: dict[str, int], expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(healthy_stage_stats(), **stat_changes)
    results = evaluate_stages(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(results) == expected_failures
    if not expected_failures:
        enforce("stages", results)
        return
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("stages", results)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


def test_the_competition_gate_counts_the_competitions() -> None:
    results = evaluate_competitions(healthy_competition_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == COMPETITION_GATE_NAMES
    assert all(result.applied and result.passed for result in results)

    too_few = dataclasses.replace(healthy_competition_stats(), competitions=49)
    assert failed_gate_names(evaluate_competitions(too_few, BOUNDS, FULL_SIZE_GAME_DB_BYTES)) == [
        "competitions_minimum"
    ]


def test_the_reader_checks_carry_their_record_counts() -> None:
    stage_check = check_stages(healthy_stage_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert stage_check.reader == "stages"
    assert stage_check.record_count == 8_000
    assert dict(stage_check.anomalies) == {"walk_gaps": 0, "rejected_competition_ids": 1}

    competition_check = check_competitions(
        healthy_competition_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    assert competition_check.reader == "competitions"
    assert competition_check.record_count == 2_600


def test_the_example_rows_are_each_one_stride_long() -> None:
    assert all(len(row) == STAGE_ROW_LENGTH for row in career_stage_rows())
    assert len(career_stage_rows()) == STAGE_ROW_COUNT


@pytest.mark.parametrize(
    ("reader_name", "expected_gate"),
    [
        pytest.param("stages", "stage_rows_minimum", id="stages"),
        pytest.param("competitions", "competitions_minimum", id="competitions"),
    ],
)
def test_each_reader_enforces_its_checks_before_it_hands_back_a_table(
    career_save_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader_name: str,
    expected_gate: str,
) -> None:
    """A reader that evaluated its checks and never enforced them would return this table.

    The example save holds far fewer rows than a career does, so once the checks apply the
    counts are below their bounds and the reader must raise rather than return.
    """
    applied_bounds = dataclasses.replace(BOUNDS, minimum_applies_from_bytes=0)
    monkeypatch.setattr(fmsave.Save, "_gate_bounds", lambda career_save: applied_bounds)

    with (
        fmsave.open(career_save_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        getattr(career_save, reader_name)()

    message = str(error_info.value)
    assert expected_gate in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


@pytest.mark.parametrize(
    "broken_row",
    [
        pytest.param(
            stage_row_bytes(
                stage_id=BROKEN_ROW_STAGE_ID,
                competition_id=THIRD_COMPETITION_ID,
                group_id=None,
                round_code=None,
                stage_id_copy=BROKEN_ROW_STAGE_ID + 1,
            ),
            id="id-not-repeated",
        ),
        pytest.param(
            stage_row_bytes(
                stage_id=BROKEN_ROW_STAGE_ID,
                competition_id=THIRD_COMPETITION_ID,
                group_id=None,
                round_code=None,
                zero_byte=1,
            ),
            id="byte-after-the-id-not-zero",
        ),
        pytest.param(
            stage_row_bytes(
                stage_id=250_000,
                competition_id=THIRD_COMPETITION_ID,
                group_id=None,
                round_code=None,
            ),
            id="id-out-of-range",
        ),
    ],
)
def test_a_row_breaking_one_recognition_test_is_walked_over_rather_than_read(
    broken_row: bytes,
) -> None:
    """Each test a row is recognised by carries its own weight.

    The row validator is the whole basis on which the table is recognised, so dropping any one
    of its tests would let these 33 bytes read as a stage.
    """
    rows = career_stage_rows()
    rows[BROKEN_ROW_STAGE_ID - 1] = broken_row

    stage_index = example_stage_index(rows)

    assert stage_index.stats.rows == STAGE_ROW_COUNT - 1
    assert stage_index.stats.gaps == 1
    assert BROKEN_ROW_STAGE_ID not in stage_index.stage_by_id


def test_rows_before_the_search_window_are_kept_by_walking_back_to_the_head() -> None:
    """The window opens part way into the table on a real save, as it does here.

    The first offset that chains a full run of rows is then the first row inside the window,
    and every row before it is reached only by stepping back a row at a time.
    """
    layout = find_stage_layout(GAME_DB_SCHEMA, "")
    rows = career_stage_rows()
    rows_before_the_window = len(rows) - layout.chain_rows
    # Pad after the table so the last `search_bytes` of the buffer begin on the first row of
    # the chain, leaving the rows in front of it outside the window.
    trailing_bytes = layout.search_bytes - layout.chain_rows * STAGE_ROW_LENGTH
    game_db = stage_table_bytes(rows, trailing_bytes=trailing_bytes)

    stage_index = read_stage_index(game_db, layout, FILE_NAME)

    assert rows_before_the_window > 0
    assert len(stage_index.stages) == STAGE_ROW_COUNT
    assert stage_index.stages[0].id == 1


def test_the_walk_counts_exactly_what_the_gates_divide() -> None:
    """Every stage gate judges these counts, and only the walk itself produces them."""
    stage_index = example_stage_index()

    assert stage_index.stats == StageStats(
        rows=STAGE_ROW_COUNT,
        gaps=0,
        ascending_steps=STAGE_ROW_COUNT - 1,
        steps=STAGE_ROW_COUNT - 1,
        # The row with no competition, and the row whose competition id the limit rejects.
        with_competition=STAGE_ROW_COUNT - 2,
        competition_id_rejected=1,
        # One row carries a number in the last word instead of the missing value.
        trailing_sentinel_ok=STAGE_ROW_COUNT - 1,
        bytes_after_table=STAGE_TABLE_TRAILING_BYTES,
    )


def test_only_the_round_codes_an_in_game_label_confirms_are_named() -> None:
    """Which codes carry a name is the whole judgement of this reader, so it is pinned here.

    Naming a code that no label reaches, renumbering a named one, or dropping a name would
    each relabel stages on every save while every other test still passed.
    """
    named_by_code = {
        member.value: member
        for member in CompetitionRound
        if member is not CompetitionRound.UNKNOWN
    }

    assert named_by_code == NAMED_ROUND_CODES
    assert CompetitionRound.UNKNOWN.value == -1
    for round_code in UNNAMED_ROUND_CODES:
        coded_round = CodedValue.from_raw(CompetitionRound, round_code)
        assert coded_round.label is CompetitionRound.UNKNOWN, round_code
        assert coded_round.raw == round_code


def test_a_competition_is_named_through_its_database_id_once_one_is_supplied() -> None:
    """The name map is keyed on the database id, so a competition is named only through it."""
    competition_index = build_competition_index(
        example_stage_index(),
        {
            FIRST_COMPETITION_ID: EXAMPLE_DATABASE_ID,
            SECOND_COMPETITION_ID: SECOND_EXAMPLE_DATABASE_ID,
        },
        {EXAMPLE_DATABASE_ID: "Example League", SECOND_EXAMPLE_DATABASE_ID: "Example Cup"},
    )

    assert competition_index.competition_by_id[FIRST_COMPETITION_ID].database_id == (
        EXAMPLE_DATABASE_ID
    )
    assert competition_index.name_for(FIRST_COMPETITION_ID) == "Example League"
    assert competition_index.name_for(SECOND_COMPETITION_ID) == "Example Cup"
    # A competition with no database id cannot be named, however full the map is.
    assert competition_index.name_for(THIRD_COMPETITION_ID) is None
    assert competition_index.name_for(OUT_OF_BAND_COMPETITION_ID) is None
    assert competition_index.name_for(None) is None
    assert THIRD_COMPETITION_ID not in competition_index.database_id_by_competition_id
    assert competition_index.stats.with_database_id == 2
    assert competition_index.stats.with_name == 2
    assert competition_index.stats.database_id_conflicts == 0
