"""The selections table: each stored starter and substitute pick of the manager's teams."""

from __future__ import annotations

from pathlib import Path

import pytest

import fmsave
from fmsave._checks import validate_save
from fmsave.export import column_names
from fmsave.models.tactics import Selection
from tests.fixtures.career import (
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    PLAYER_A_UID,
    PLAYER_C_UID,
    PLAYER_D_UID,
    career_fragment,
    career_routine_names,
    career_tactic_records,
)
from tests.fixtures.tactics import (
    HAS_TACTICS_VALUE,
    NO_SELECTOR,
    NO_TACTICS_VALUE,
    ROUTINE_COUNT,
    selection_part_bytes,
    set_piece_area_bytes,
    tactics_man_body,
)

MANAGER_SELECTOR = 500
# Player selectors are a player's record index plus one, so these name players A, C and D.
SELECTOR_A = 12
SELECTOR_C = 14
SELECTOR_D = 15
UNRESOLVED_SELECTOR = 9_999
STARTERS = 11


def picks(save_path: Path) -> list[tuple[int, bool, int, int | None]]:
    with fmsave.open(save_path) as save:
        return [
            (row.team_id, row.substitute, row.slot, row.player_uid) for row in save.selections()
        ]


def body_with_slots(slots: tuple[int, ...]) -> bytes:
    """The career's tactics section with the first team's selection places replaced."""
    first_block = (
        selection_part_bytes(
            team_id=NORTHBRIDGE_TEAM_A,
            label="Example XI",
            slots=slots,
            list_a=(),
            list_b=(),
            single=NO_SELECTOR,
            tactics_value=HAS_TACTICS_VALUE,
            tactic_count=2,
        )
        + b"".join(career_tactic_records())
        + set_piece_area_bytes(career_routine_names())
    )
    second_block = selection_part_bytes(
        team_id=NORTHBRIDGE_TEAM_B,
        label="",
        slots=(),
        list_a=(),
        list_b=(),
        single=NO_SELECTOR,
        tactics_value=NO_TACTICS_VALUE,
        tactic_count=0,
    ) + set_piece_area_bytes((None,) * ROUTINE_COUNT)
    return tactics_man_body(selector=MANAGER_SELECTOR, blocks=(first_block, second_block))


def test_each_stored_starter_is_one_row_keyed_on_its_tactic_slot(tmp_path: Path) -> None:
    save_path = career_fragment().write(tmp_path / "career.bin")
    with fmsave.open(save_path) as save:
        rows = save.selections()

    assert [(row.substitute, row.slot, row.player_uid) for row in rows] == [
        (False, 0, PLAYER_A_UID),
        (False, 1, PLAYER_C_UID),
        (False, 2, PLAYER_D_UID),
    ]
    assert {(row.club_uid, row.club_name, row.team_id, row.team_slot) for row in rows} == {
        (NORTHBRIDGE_UID, "Northbridge FC", NORTHBRIDGE_TEAM_A, 0)
    }
    assert all(row.player_name for row in rows)


def test_substitutes_count_from_their_own_first_place_and_empty_places_have_no_row(
    tmp_path: Path,
) -> None:
    empty = NO_SELECTOR
    slots = (SELECTOR_A, empty, SELECTOR_C) + (empty,) * 8 + (SELECTOR_D, empty, SELECTOR_A)
    save_path = career_fragment(tactics_section=body_with_slots(slots)).write(
        tmp_path / "career.bin"
    )

    assert picks(save_path) == [
        (NORTHBRIDGE_TEAM_A, False, 0, PLAYER_A_UID),
        (NORTHBRIDGE_TEAM_A, False, 2, PLAYER_C_UID),
        (NORTHBRIDGE_TEAM_A, True, 0, PLAYER_D_UID),
        (NORTHBRIDGE_TEAM_A, True, 2, PLAYER_A_UID),
    ]


def test_the_last_substitute_place_is_read(tmp_path: Path) -> None:
    slots = (NO_SELECTOR,) * 25 + (SELECTOR_C,)
    save_path = career_fragment(tactics_section=body_with_slots(slots)).write(
        tmp_path / "career.bin"
    )

    assert picks(save_path) == [(NORTHBRIDGE_TEAM_A, True, 14, PLAYER_C_UID)]


def test_a_pick_no_player_record_names_keeps_its_row_and_is_counted(tmp_path: Path) -> None:
    slots = (SELECTOR_C, UNRESOLVED_SELECTOR)
    save_path = career_fragment(tactics_section=body_with_slots(slots)).write(
        tmp_path / "career.bin"
    )
    with fmsave.open(save_path) as save:
        rows = save.selections()
        report = validate_save(save)

    assert [(row.slot, row.player_uid, row.player_name) for row in rows][1] == (1, None, None)
    (selection_report,) = [row for row in report.readers if row.reader == "selections"]
    assert selection_report.anomalies == {"unresolved_picks": 1}
    assert [gate.name for gate in selection_report.gates] == [
        "selection_picks_resolved",
        "selection_picks_at_club",
    ]


def test_validation_reports_selections_beside_the_other_tactics_readers(tmp_path: Path) -> None:
    save_path = career_fragment().write(tmp_path / "career.bin")
    with fmsave.open(save_path) as save:
        report = validate_save(save)

    names = [row.reader for row in report.readers]
    assert names[names.index("set_pieces") + 1] == "selections"
    (selection_report,) = [row for row in report.readers if row.reader == "selections"]
    assert selection_report.status == "ok"
    assert selection_report.record_count == 3


def test_with_the_manager_between_jobs_there_are_no_selections(tmp_path: Path) -> None:
    save_path = career_fragment(manager_between_jobs=True).write(tmp_path / "career.bin")
    with fmsave.open(save_path) as save:
        assert len(save.selections()) == 0


def test_the_three_tactics_tables_come_from_one_walk(tmp_path: Path) -> None:
    save_path = career_fragment().write(tmp_path / "career.bin")
    with fmsave.open(save_path) as save:
        selections = save.selections()
        assert save.selections() is selections
        assert len(save.tactics()) == 2
        assert len(save.set_pieces()) == 2 * ROUTINE_COUNT

    with pytest.raises(fmsave.SaveClosedError):
        save.selections()


def test_the_columns_the_export_writes() -> None:
    assert column_names(Selection) == (
        "club_uid",
        "club_name",
        "team_id",
        "team_slot",
        "substitute",
        "slot",
        "player_uid",
        "player_name",
    )


def test_every_field_is_unconfirmed() -> None:
    for name in column_names(Selection):
        assert fmsave.field_status(Selection, name) == "unconfirmed"


def test_the_starter_count_is_the_tactic_slot_count(tmp_path: Path) -> None:
    slots = (SELECTOR_A,) * STARTERS + (SELECTOR_C,)
    save_path = career_fragment(tactics_section=body_with_slots(slots)).write(
        tmp_path / "career.bin"
    )

    rows = picks(save_path)
    assert [row[1] for row in rows] == [False] * STARTERS + [True]
