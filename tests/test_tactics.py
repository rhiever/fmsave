from __future__ import annotations

import copy
import pickle
from collections.abc import Sequence
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as strategy

import fmsave
from fmsave import _context as context_module
from fmsave._checks import (
    SET_PIECES_READER,
    TACTICS_READER,
    GateResult,
    evaluate_set_pieces,
    evaluate_tactics,
)
from fmsave._container import ContainerIndex
from fmsave._errors import FmsaveError, SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import TacticStats
from fmsave.export import column_names, record_to_dict
from fmsave.models.common import CodedValue
from fmsave.models.tactics import (
    Mentality,
    SetPieceRoutine,
    Tactic,
    TacticPosition,
    TacticSettingUnit,
)
from fmsave.readers._common import GAME_DB_SECTION, TACTICS_SECTION
from fmsave.readers.tactics import (
    build_tactic_tables,
    find_tactics_layout,
    read_tactics_header,
    walk_tactic_blocks,
)
from tests.fixtures.career import (
    FIRST_ROUTINE_NAME,
    FIRST_TACTIC_NAME,
    FOURTH_ROUTINE_NAME,
    MANAGER_SELECTOR,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    SECOND_TACTIC_NAME,
    TACTIC_STYLE_NAME,
    career_fragment,
    career_routine_names,
    career_tactic_records,
    career_tactic_slots,
    career_tactics_body,
)
from tests.fixtures.tactics import (
    HAS_TACTICS_VALUE,
    NO_SELECTOR,
    ROUTINE_COUNT,
    selection_part_bytes,
    set_piece_area_bytes,
    setting_unit_bytes,
    slot_block_bytes,
    tactic_record_bytes,
    tactics_man_body,
)

GAME_DB_SCHEMA = 4000
TACTICS_SCHEMA = 26
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 100 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_tactics_layout(TACTICS_SCHEMA, "")
FILE_NAME = "career.bin"

SELECTOR_GATE_NAME = "tactics_manager_selector_matches"
BLOCKS_GATE_NAME = "tactics_team_blocks_match_club"
SLOT_WALK_GATE_NAME = "tactic_slot_walks_complete"
INDEX_GATE_NAME = "tactic_oop_index_permutations"
RESOLVED_GATE_NAME = "tactic_selection_selectors_resolved"
AT_CLUB_GATE_NAME = "tactic_selection_selectors_at_club"
ROUTINE_GATE_NAME = "set_piece_blocks_with_twenty"

# The career fragment's two blocks hold seven selectors, of which three name the one player
# registered with the managed club.
CAREER_SELECTORS = 7
CAREER_SELECTORS_AT_CLUB = 3
CAREER_STYLE_CODE = 1_347_246_149
CAREER_TEAM_IDS = (NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B)


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def failed_gate_names(results: Sequence[GateResult]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_stats(**overrides: object) -> TacticStats:
    """Counts as the largest save measured reports them, before any override."""
    fields: dict[str, object] = {
        "managed_club_exists": True,
        "club_team_count": 5,
        "header_blocks": 5,
        "blocks_found": 5,
        "selector_matches": True,
        "selection_selectors": 1069,
        "selection_selectors_resolved": 1069,
        "selection_selectors_at_club": 1069,
        "tactic_blocks": 3,
        "tactic_blocks_count_matching": 3,
        "user_tactics": 6,
        "preset_tactics": 1,
        "slot_walks_complete": 6,
        "oop_index_permutations": 6,
        "routine_blocks": 5,
        "routine_blocks_with_twenty": 5,
        "routines": 100,
        "named_routines": 10,
    }
    return TacticStats(**(fields | overrides))  # type: ignore[arg-type]


def tactics_path(tmp_path: Path, body: bytes) -> Path:
    return career_fragment(tactics_section=body).write(tmp_path / "career.bin")


def decoded_tactics(
    save_path: Path, *, human_selector: int | None = MANAGER_SELECTOR
) -> tuple[tuple[Tactic, ...], tuple[SetPieceRoutine, ...], TacticStats]:
    """The two tables and the counts, from the reader functions the save method calls."""
    with fmsave.open(save_path) as save:
        managed_clubs = save.managed_clubs()
        save.clubs()
        players = save.players()
        context = save._context
        with context.section(TACTICS_SECTION) as section:
            header_selector, _header_blocks = read_tactics_header(section, LAYOUT, FILE_NAME)
            with context.section(GAME_DB_SECTION):
                club_index = context.club_index()
                player_records = context.player_records()
            managed_club_uid = managed_clubs[0].club_uid
            club_team_ids = [
                team.team_id for team in club_index.club_by_uid[managed_club_uid].teams
            ]
            blocks, counts = walk_tactic_blocks(section, club_team_ids, LAYOUT, FILE_NAME)
        return build_tactic_tables(
            blocks,
            club_index,
            player_records,
            players,
            managed_club_uid,
            header_selector,
            human_selector,
            counts,
        )


def test_each_stored_tactic_of_each_team_is_one_row(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        tactics = save.tactics()

    assert [(row.team_id, row.index) for row in tactics] == [
        (NORTHBRIDGE_TEAM_A, 0),
        (NORTHBRIDGE_TEAM_A, 1),
    ]
    assert [row.club_uid for row in tactics] == [NORTHBRIDGE_UID, NORTHBRIDGE_UID]
    assert [row.club_name for row in tactics] == ["Northbridge FC", "Northbridge FC"]
    assert [row.team_slot for row in tactics] == [0, 0]
    assert [row.name for row in tactics] == [FIRST_TACTIC_NAME, SECOND_TACTIC_NAME]
    assert [row.style_name for row in tactics] == [TACTIC_STYLE_NAME, TACTIC_STYLE_NAME]


def test_the_mentality_is_named_and_the_team_instructions_ship_as_raw_numbers(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        first, second = save.tactics()

    assert first.mentality.label is Mentality.ATTACKING
    assert first.mentality.raw == 6
    assert second.mentality.label is Mentality.BALANCED
    assert second.mentality.raw == 4
    assert first.unknown["team_instruction_02"] == 6
    assert first.unknown["team_instruction_11"] == 84
    assert first.unknown["team_instruction_18"] == 255
    assert first.unknown["style_code"] == CAREER_STYLE_CODE


def test_a_tactic_holds_eleven_slots_with_both_phases_of_each(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first = save.tactics()[0]

    assert [slot.number for slot in first.slots] == list(range(11))
    goalkeeper = first.slots[0]
    assert goalkeeper.in_possession_positions == (CodedValue(TacticPosition.UNKNOWN, 0),)
    assert goalkeeper.in_possession_mask == 1
    assert goalkeeper.in_possession_setting_count == 2
    assert goalkeeper.out_of_possession_setting_count == 1
    assert goalkeeper.unknown == {
        "in_possession_role_bits": 16,
        "in_possession_trail_bits": 0,
        "out_of_possession_role_bits": 8,
        "out_of_possession_trail_bits": 0,
        "out_of_possession_position_index": 0,
    }


def test_a_column_flag_is_not_a_position_and_the_index_byte_is_per_slot(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        first = save.tactics()[0]

    assert first.slots[2].in_possession_mask == 1_048_584
    assert first.slots[2].in_possession_positions == (CodedValue(TacticPosition.UNKNOWN, 3),)
    assert first.slots[10].unknown["out_of_possession_position_index"] == 10


def test_a_slots_setting_units_ship_as_their_head_byte_and_bit_words(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first = save.tactics()[0]

    assert first.slots[0].in_possession_settings == (
        TacticSettingUnit(0, 1, 0, 2, 0),
        TacticSettingUnit(10, 258, 0, 0, 64),
    )


def test_every_routine_slot_of_every_team_is_one_row(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        routines = save.set_pieces()

    assert len(routines) == 2 * ROUTINE_COUNT
    assert [row.team_id for row in routines[:ROUTINE_COUNT]] == [NORTHBRIDGE_TEAM_A] * ROUTINE_COUNT
    assert [row.team_id for row in routines[ROUTINE_COUNT:]] == [NORTHBRIDGE_TEAM_B] * ROUTINE_COUNT
    assert [row.slot for row in routines[:ROUTINE_COUNT]] == list(range(ROUTINE_COUNT))
    assert routines[0].name == FIRST_ROUTINE_NAME
    assert routines[3].name == FOURTH_ROUTINE_NAME
    assert [row.name for row in routines if row.name is not None] == [
        FIRST_ROUTINE_NAME,
        FOURTH_ROUTINE_NAME,
    ]
    assert routines[0].club_uid == NORTHBRIDGE_UID
    assert routines[0].club_name == "Northbridge FC"
    assert routines[ROUTINE_COUNT].team_slot == 1


def test_the_walk_counts_the_blocks_the_records_and_the_selectors(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.tactics()
        reader_check = save._reader_check(TACTICS_READER)
        routine_check = save._reader_check(SET_PIECES_READER)
    _tactics, _routines, stats = decoded_tactics(career_path)

    assert stats.header_blocks == 2
    assert stats.blocks_found == 2
    assert stats.club_team_count == 2
    assert stats.selector_matches is True
    assert stats.user_tactics == 2
    assert stats.slot_walks_complete == 2
    assert stats.oop_index_permutations == 2
    assert stats.routine_blocks == 2
    assert stats.routine_blocks_with_twenty == 2
    assert stats.named_routines == 2
    assert stats.selection_selectors == CAREER_SELECTORS
    assert stats.selection_selectors_resolved == CAREER_SELECTORS
    assert stats.selection_selectors_at_club == CAREER_SELECTORS_AT_CLUB
    assert reader_check is not None
    assert reader_check.record_count == 2
    assert routine_check is not None
    assert routine_check.record_count == 2 * ROUTINE_COUNT


def test_a_slot_claiming_one_unit_too_many_leaves_that_walk_incomplete(tmp_path: Path) -> None:
    slots = list(career_tactic_slots())
    _in_possession, out_of_possession = slots[4]
    slots[4] = (
        slot_block_bytes(
            mask=1,
            units=(setting_unit_bytes(head_byte=0, first_bits=1, second_bits=1),),
            role_bits=1,
            stored_unit_count=2,
        ),
        out_of_possession,
    )
    broken = tactic_record_bytes(
        name="Example 352",
        team_instructions=bytes(19),
        style_name="Example Style",
        style_code=b"EXMP",
        slots=slots,
    )
    save_path = tactics_path(
        tmp_path, career_tactics_body(first_team_records=(career_tactic_records()[0], broken))
    )

    tactics, _routines, stats = decoded_tactics(save_path)

    assert len(tactics) == 2
    assert len(tactics[0].slots) == 11
    assert len(tactics[1].slots) == 4
    assert stats.user_tactics == 2
    assert stats.slot_walks_complete == 1


def test_a_repeated_index_byte_is_not_a_permutation(tmp_path: Path) -> None:
    slots = list(career_tactic_slots())
    in_possession, _out_of_possession = slots[7]
    slots[7] = (
        in_possession,
        slot_block_bytes(
            mask=1 << 7,
            units=(setting_unit_bytes(head_byte=0, first_bits=1, second_bits=1),),
            role_bits=8,
            position_index=6,
        ),
    )
    repeated = tactic_record_bytes(
        name="Example 451",
        team_instructions=bytes(19),
        style_name="Example Style",
        style_code=b"EXMP",
        slots=slots,
    )
    save_path = tactics_path(
        tmp_path, career_tactics_body(first_team_records=(career_tactic_records()[0], repeated))
    )

    _tactics, _routines, stats = decoded_tactics(save_path)

    assert stats.slot_walks_complete == 2
    assert stats.oop_index_permutations == 1


def test_a_preset_record_is_counted_and_gives_no_row(tmp_path: Path) -> None:
    preset = tactic_record_bytes(
        name="Example Preset",
        team_instructions=bytes(19),
        style_name="Example Style",
        style_code=b"EXMP",
        slots=career_tactic_slots(),
        preset=True,
    )
    save_path = tactics_path(
        tmp_path, career_tactics_body(first_team_records=(career_tactic_records()[0], preset))
    )

    tactics, _routines, stats = decoded_tactics(save_path)

    assert [row.name for row in tactics] == [FIRST_TACTIC_NAME]
    assert stats.user_tactics == 1
    assert stats.preset_tactics == 1
    assert stats.tactic_blocks_count_matching == stats.tactic_blocks


def test_a_short_name_a_long_name_and_a_block_of_nineteen_routines(tmp_path: Path) -> None:
    names = list(career_routine_names())
    names[1] = "Ex"
    names[2] = "E" * 64
    nineteen = names[:19]
    save_path = tactics_path(
        tmp_path,
        career_tactics_body(first_team_routines=names, second_team_routines=nineteen),
    )

    _tactics, routines, stats = decoded_tactics(save_path)

    first_team = [row for row in routines if row.team_id == NORTHBRIDGE_TEAM_A]
    second_team = [row for row in routines if row.team_id == NORTHBRIDGE_TEAM_B]
    assert first_team[1].name == "Ex"
    assert first_team[2].name == "E" * 64
    assert len(second_team) == 19
    assert [row.slot for row in second_team] == list(range(19))
    assert stats.routine_blocks_with_twenty == stats.routine_blocks - 1


def test_a_team_id_the_section_stores_twice_gets_no_block(tmp_path: Path) -> None:
    repeated_block = selection_part_bytes(
        team_id=NORTHBRIDGE_TEAM_B,
        label="",
        slots=(),
        list_a=(),
        list_b=(),
        single=NO_SELECTOR,
        tactics_value=HAS_TACTICS_VALUE,
        tactic_count=0,
    )
    body = career_tactics_body()
    doubled = body[: len(body) - 64] + repeated_block + bytes(64)
    save_path = tactics_path(tmp_path, doubled)

    tactics, routines, stats = decoded_tactics(save_path)

    assert stats.blocks_found == stats.club_team_count - 1
    assert {row.team_id for row in tactics} == {NORTHBRIDGE_TEAM_A}
    assert {row.team_id for row in routines} == {NORTHBRIDGE_TEAM_A}


def test_a_header_selector_that_is_not_the_human_managers_fails_the_gate(tmp_path: Path) -> None:
    save_path = tactics_path(tmp_path, career_tactics_body(selector=MANAGER_SELECTOR + 3))

    _tactics, _routines, stats = decoded_tactics(save_path)

    assert stats.selector_matches is False
    assert failed_gate_names(
        evaluate_tactics(healthy_stats(selector_matches=False), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    ) == [SELECTOR_GATE_NAME]


def test_with_the_manager_between_jobs_both_tables_are_empty_and_nothing_is_judged(
    tmp_path: Path,
) -> None:
    save_path = career_fragment(manager_between_jobs=True).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        assert len(save.tactics()) == 0
        assert len(save.set_pieces()) == 0
        tactic_check = save._reader_check(TACTICS_READER)
        routine_check = save._reader_check(SET_PIECES_READER)

    assert tactic_check is not None
    assert routine_check is not None
    assert [result.applied for result in tactic_check.gates] == [False] * 6
    assert [result.applied for result in routine_check.gates] == [False]


def test_a_cold_tactics_read_decompresses_game_db_once(
    career_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every read of the game database sits inside one borrow, the managed club's included.

    The section is decompressed where its loan starts, so counting the reads counts the
    decompressions. Reading the managed club before the borrow opened paid for a second
    decompression of the largest section in the save.
    """
    sections_read: list[str] = []
    read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        sections_read.append(name)
        return read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)

    with fmsave.open(career_path) as save:
        assert len(save.tactics()) == 2
        assert len(save.set_pieces()) == 2 * ROUTINE_COUNT

    assert sections_read.count(GAME_DB_SECTION) == 1
    assert sections_read.count(TACTICS_SECTION) == 1


def test_a_preset_record_behind_the_last_block_is_not_a_twenty_first_routine(
    tmp_path: Path,
) -> None:
    """A preset record ending in the routine terminator sits outside the block's routines.

    The save keeps a run of preset records behind the last team block. The block's range runs
    to the end of the section, so only the next tactic signature keeps that run out of the
    block's routine slots.
    """
    trailing_preset = tactic_record_bytes(
        name="Example Preset",
        team_instructions=bytes(19),
        style_name="Example Style",
        style_code=b"EXMP",
        slots=(),
        tail=bytes(4) + bytes.fromhex("014c4c554e") + bytes(1),
        preset=True,
    )
    save_path = tactics_path(tmp_path, career_tactics_body() + trailing_preset)

    _tactics, routines, stats = decoded_tactics(save_path)

    assert stats.routine_blocks_with_twenty == stats.routine_blocks == 2
    assert len(routines) == 2 * ROUTINE_COUNT


def test_the_columns_the_export_flattens(career_path: Path) -> None:
    expected_unknown = tuple(
        f"unknown_team_instruction_{position:02d}" for position in range(19)
    ) + ("unknown_style_code",)

    assert column_names(Tactic) == (
        "club_uid",
        "club_name",
        "team_id",
        "team_slot",
        "index",
        "name",
        "style_name",
        "mentality",
        "mentality_code",
        "slots",
        *expected_unknown,
    )
    assert column_names(SetPieceRoutine) == (
        "club_uid",
        "club_name",
        "team_id",
        "team_slot",
        "slot",
        "name",
    )

    with fmsave.open(career_path) as save:
        first = save.tactics()[0]

    as_dict = record_to_dict(first, json_ready=True)
    slots = as_dict["slots"]
    assert isinstance(slots, list)
    first_slot = slots[0]
    assert first_slot["in_possession_settings"][0]["head_byte"] == 0
    assert first_slot["in_possession_positions"] == ["unknown"]
    assert first_slot["in_possession_positions_code"] == [0]


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        tactics = save.tactics()
        routines = save.set_pieces()

    # A round trip of fmsave's own records, not data from anywhere else.
    for record in (tactics[0], tactics[0].slots[0], tactics[0].slots[0].in_possession_settings[0]):
        assert pickle.loads(pickle.dumps(record)) == record
        assert copy.deepcopy(record) == record
    assert pickle.loads(pickle.dumps(routines[0])) == routines[0]
    assert copy.deepcopy(tactics) == tactics
    assert copy.deepcopy(routines) == routines


def test_the_tables_are_read_once_and_raise_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        tactics = save.tactics()
        routines = save.set_pieces()
        assert save.tactics() is tactics
        assert save.set_pieces() is routines

    with pytest.raises(SaveClosedError):
        save.tactics()
    with pytest.raises(SaveClosedError):
        save.set_pieces()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"selector_matches": False}, [SELECTOR_GATE_NAME], id="a foreign selector"),
        pytest.param({"blocks_found": 4}, [BLOCKS_GATE_NAME], id="a team with no block"),
        pytest.param({"header_blocks": 6}, [BLOCKS_GATE_NAME], id="a header count of its own"),
        pytest.param({"slot_walks_complete": 3}, [SLOT_WALK_GATE_NAME], id="half the walks"),
        pytest.param({"oop_index_permutations": 3}, [INDEX_GATE_NAME], id="half the indexes"),
        pytest.param(
            {"selection_selectors_resolved": 0, "selection_selectors_at_club": 0},
            [RESOLVED_GATE_NAME],
            id="no selector resolving",
        ),
        pytest.param(
            {"selection_selectors_at_club": 898},
            [AT_CLUB_GATE_NAME],
            id="a sixth of them elsewhere",
        ),
        pytest.param(
            {"user_tactics": 0, "slot_walks_complete": 0, "oop_index_permutations": 0},
            [SLOT_WALK_GATE_NAME, INDEX_GATE_NAME],
            id="no user tactic at all",
        ),
    ],
)
def test_each_misaligned_count_fails_its_own_gate_and_the_measured_counts_pass(
    overrides: dict[str, object], expected: list[str]
) -> None:
    failing = evaluate_tactics(healthy_stats(**overrides), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    passing = evaluate_tactics(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(failing) == expected
    assert failed_gate_names(passing) == []


def test_a_block_short_of_twenty_routines_fails_the_routine_gate() -> None:
    failing = evaluate_set_pieces(
        healthy_stats(routine_blocks_with_twenty=4), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    passing = evaluate_set_pieces(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(failing) == [ROUTINE_GATE_NAME]
    assert failed_gate_names(passing) == []


def test_no_gate_applies_on_a_small_game_db_or_without_a_managed_club() -> None:
    broken = healthy_stats(
        selector_matches=False,
        blocks_found=0,
        slot_walks_complete=0,
        oop_index_permutations=0,
        selection_selectors_resolved=0,
        selection_selectors_at_club=0,
        routine_blocks_with_twenty=0,
    )
    small_game_db = evaluate_tactics(broken, BOUNDS, SMALL_GAME_DB_BYTES)
    no_managed_club = evaluate_tactics(
        healthy_stats(managed_club_exists=False), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    no_routines = evaluate_set_pieces(
        healthy_stats(routine_blocks=0, routine_blocks_with_twenty=0),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )

    assert [result.applied for result in small_game_db] == [False] * 6
    assert [result.applied for result in no_managed_club] == [False] * 6
    assert [result.applied for result in no_routines] == [False]


@settings(max_examples=40, deadline=2_000, suppress_health_check=[HealthCheck.too_slow])
@given(
    payload=strategy.binary(min_size=0, max_size=600),
    truncate_at=strategy.integers(min_value=0, max_value=400),
)
def test_a_random_or_truncated_section_raises_only_an_fmsave_error(
    payload: bytes, truncate_at: int
) -> None:
    bodies = (
        tactics_man_body(selector=MANAGER_SELECTOR, blocks=(payload,)),
        career_tactics_body()[:truncate_at],
        payload,
    )
    for body in bodies:
        layout = find_tactics_layout(TACTICS_SCHEMA, "")
        try:
            read_tactics_header(body, layout, FILE_NAME)
            blocks, counts = walk_tactic_blocks(body, CAREER_TEAM_IDS, layout, FILE_NAME)
        except FmsaveError:
            continue
        # A walk that returns instead of raising has to have stayed inside what it was given:
        # no more blocks than teams asked for, and no more routine slots than a block holds.
        assert counts.blocks_found == len(blocks) <= len(CAREER_TEAM_IDS)
        assert all(len(block.routine_names) <= layout.routine_count for block in blocks)
        assert all(
            len(tactic.slots) <= layout.slot_count for block in blocks for tactic in block.tactics
        )


def test_a_slot_with_no_setting_unit_still_decodes(career_path: Path) -> None:
    empty_slot = slot_block_bytes(mask=1, units=(), role_bits=0)
    indexed = slot_block_bytes(mask=1, units=(), role_bits=0, position_index=0)
    record = tactic_record_bytes(
        name="Example 541",
        team_instructions=bytes(19),
        style_name="Example Style",
        style_code=b"EXMP",
        slots=tuple(
            (empty_slot, slot_block_bytes(mask=1, units=(), role_bits=0, position_index=number))
            for number in range(11)
        ),
    )
    body = tactics_man_body(
        selector=MANAGER_SELECTOR,
        blocks=(
            selection_part_bytes(
                team_id=NORTHBRIDGE_TEAM_A,
                label="",
                slots=(),
                list_a=(),
                list_b=(),
                single=NO_SELECTOR,
                tactics_value=HAS_TACTICS_VALUE,
                tactic_count=1,
            )
            + record
            + set_piece_area_bytes(career_routine_names()),
        ),
    )
    layout = find_tactics_layout(TACTICS_SCHEMA, "")
    blocks, counts = walk_tactic_blocks(body, (NORTHBRIDGE_TEAM_A,), layout, FILE_NAME)

    # The out-of-possession block is the in-possession one plus the per-position index byte,
    # which is the whole difference between the two and what the pair order rests on.
    assert len(indexed) == len(empty_slot) + 1
    assert counts.blocks_found == 1
    assert len(blocks[0].tactics) == 1
    first_tactic = blocks[0].tactics[0]
    assert first_tactic.walk_complete is True
    assert len(first_tactic.slots) == 11
    assert first_tactic.slots[0].in_possession_setting_count == 0
    assert first_tactic.slots[0].in_possession_settings == ()
    assert first_tactic.slots[0].out_of_possession_settings == ()
    assert first_tactic.slots[10].unknown["out_of_possession_position_index"] == 10
