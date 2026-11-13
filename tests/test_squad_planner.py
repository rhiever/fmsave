from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

import fmsave
from fmsave import cli
from tests.fixtures.career import (
    PLAYER_A_PINDEX,
    PLAYER_A_UID,
    PLAYER_C_PINDEX,
    PLAYER_C_UID,
    career_fragment,
    career_game_db,
)
from tests.fixtures.container import SectionFrame, packed_date, section_body
from tests.test_fm27_experimental import BUILD, UNREGISTERED_BUILD, fm27_fragment

OWNER = 71
OWNER_UID = 8_001
NO_PLAYER = 812
SLOTS = 27
EMPTY = bytes(SLOTS)
FIRST = b"\x03\x1b"
NEXT = b"\x1b"
SCOUTING = bytes.fromhex("40000002 0f2d0764")
SCOUTING_PLACEHOLDER = packed_date(1, 1900)
LEAD = (
    b"\x07\x1e"
    + packed_date(125, 2032)
    + SCOUTING_PLACEHOLDER * 2
    + SCOUTING
    + struct.pack("<II", 200, 100)
    + bytes.fromhex("00000000 0500 01 02000000 01020004")
)
FOOTER = bytes(26) + b"\x33\x00\x01" + bytes(62) + SCOUTING_PLACEHOLDER * 2 + SCOUTING
OWNER_HEADER = struct.pack("<IIIB", OWNER - 1, OWNER_UID, OWNER_UID, 9)


def slots(*selectors: int, slot: int = 1) -> bytes:
    return (
        bytes(slot - 1)
        + struct.pack(f"<B{len(selectors)}I", len(selectors), *selectors)
        + bytes(SLOTS - slot)
    )


def group(primary: bytes = EMPTY, second: bytes = EMPTY, third: bytes = EMPTY) -> bytes:
    return FIRST + primary + NEXT + second + NEXT + third


def planner_path(
    tmp_path: Path,
    data: bytes,
    *,
    count: int = 1,
    selector: int = OWNER,
    game_db: bytes = OWNER_HEADER,
    build: str = BUILD,
    schema: int = 24,
) -> Path:
    payload = struct.pack("<HI", count, selector) + bytes(8) + data
    return fm27_fragment(
        tmp_path,
        game_db=game_db,
        extra_sections=(SectionFrame("humans", section_body(".dat", schema, payload)),),
        build=build,
    )


def open_fm27(path: Path, *, strict: bool = False) -> fmsave.Save:
    with pytest.warns(fmsave.UnknownBuildWarning):
        return fmsave.open(path, strict=strict)


def test_planner_keeps_numbered_slots_and_depth_order(tmp_path: Path) -> None:
    data = (
        FIRST
        + EMPTY
        + NEXT
        + LEAD
        + group(slots(PLAYER_C_PINDEX + 1, NO_PLAYER, PLAYER_A_PINDEX + 1), slots(NO_PLAYER))
        + group(slots(PLAYER_A_PINDEX + 1, slot=27), third=slots(NO_PLAYER))
        + group()
        + group(slots(NO_PLAYER))
        + FOOTER
    )
    path = planner_path(tmp_path, data, game_db=career_game_db()[8:] + OWNER_HEADER)
    with open_fm27(path, strict=True) as save:
        rows = save.squad_planner()
        assert rows is save.squad_planner()

    assert [(row.season_offset, row.slot) for row in rows] == [
        (season, slot) for season in range(3) for slot in range(1, 28)
    ]
    assert rows[0].player_uids == (PLAYER_C_UID, None, PLAYER_A_UID)
    assert rows[53].player_uids == (PLAYER_A_UID,)
    assert all(row.player_uids == () for index, row in enumerate(rows) if index not in (0, 53))


@pytest.mark.parametrize("scouting_date", [SCOUTING_PLACEHOLDER, packed_date(251, 2031)])
def test_an_explicitly_empty_planner_needs_no_player_records(
    tmp_path: Path, scouting_date: bytes
) -> None:
    lead = LEAD.replace(SCOUTING_PLACEHOLDER, scouting_date)
    path = planner_path(tmp_path, lead + group() * 3 + group(slots(NO_PLAYER)) + FOOTER)
    with open_fm27(path) as save:
        rows = save.squad_planner()

    assert len(rows) == 81
    assert all(row.player_uids == () for row in rows)


def test_no_human_means_no_planner_rows(tmp_path: Path) -> None:
    path = planner_path(tmp_path, b"", count=0, game_db=b"")
    with open_fm27(path) as save:
        assert len(save.squad_planner()) == 0


def test_fm26_planner_layout_is_unsupported(tmp_path: Path) -> None:
    path = career_fragment().write(tmp_path / "example.bin")
    with fmsave.open(path) as save, pytest.raises(fmsave.UnsupportedGameError, match="planner"):
        save.squad_planner()


def test_planner_layout_lends_to_another_fm27_build(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER, build=UNREGISTERED_BUILD)
    with open_fm27(path) as save:
        assert len(save.squad_planner()) == 81


def test_planner_tries_an_unregistered_humans_schema(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER, schema=25)
    with (
        open_fm27(path) as save,
        pytest.warns(fmsave.UnknownBuildWarning, match="save schema 25"),
    ):
        assert len(save.squad_planner()) == 81


def test_borrowed_planner_does_not_treat_an_unreadable_owner_as_empty(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER, count=0, schema=25)
    with (
        open_fm27(path) as save,
        pytest.warns(fmsave.UnknownBuildWarning, match="save schema 25"),
        pytest.raises(fmsave.ReaderCheckError, match="planner owner could not be located"),
    ):
        save.squad_planner()


def test_a_cached_planner_stays_usable_after_close(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER)
    with open_fm27(path) as save:
        rows = save.squad_planner()

    assert len(rows) == 81
    with pytest.raises(fmsave.SaveClosedError):
        save.squad_planner()


def test_a_replaced_save_cannot_supply_planner_data(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER)
    replacement_folder = tmp_path / "replacement"
    replacement_folder.mkdir()
    replacement = planner_path(replacement_folder, b"", count=0, game_db=b"")
    with open_fm27(path) as save:
        os.replace(replacement, path)
        with pytest.raises(fmsave.SaveChangedError):
            save.squad_planner()


def test_planner_layout_does_not_guess_a_multi_manager_owner(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER, count=2)
    with open_fm27(path) as save:
        with pytest.raises(fmsave.UnsupportedGameError, match="planner"):
            save.squad_planner()
        assert save.info.game == "FM27"


@pytest.mark.parametrize(
    ("selector", "game_db"),
    [
        (0, OWNER_HEADER),
        (0xFFFFFFFF, OWNER_HEADER),
        (OWNER, OWNER_HEADER[:-1] + b"\x01"),
        (OWNER, struct.pack("<IIIB", OWNER - 1, OWNER_UID, OWNER_UID + 1, 9)),
        (OWNER, OWNER_HEADER * 2),
    ],
)
def test_planner_requires_a_unique_human_owner(
    tmp_path: Path, selector: int, game_db: bytes
) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER, selector=selector, game_db=game_db)
    with open_fm27(path) as save, pytest.raises(fmsave.ReaderCheckError, match="owner"):
        save.squad_planner()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        group() * 4 + FOOTER,
        (LEAD + group() * 4 + FOOTER) * 2,
        LEAD + group() * 3 + FIRST + EMPTY + b"\x00" + EMPTY + NEXT + EMPTY + FOOTER,
        LEAD + group() * 3 + group(third=EMPTY[:-1] + b"\xff"),
        LEAD + group() * 4 + FOOTER[:-1],
        LEAD + group() * 4 + bytes(len(FOOTER)),
    ],
    ids=[
        "absent",
        "unanchored",
        "ambiguous",
        "broken_extra_set",
        "truncated_extra_set",
        "truncated_footer",
        "wrong_footer",
    ],
)
def test_unreadable_planner_does_not_return_an_empty_table(tmp_path: Path, data: bytes) -> None:
    path = planner_path(tmp_path, data)
    with open_fm27(path) as save:
        with pytest.raises(fmsave.FmsaveError, match="planner"):
            save.squad_planner()
        assert save.info.game == "FM27"


@pytest.mark.parametrize("table_name", ["squad-planner", "squad_planner"])
def test_planner_cli_exports_numbered_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], table_name: str
) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER)
    assert cli.main(["export", str(path), table_name, "--all", "--format", "json"]) == 0

    rows = json.loads(capsys.readouterr().out)
    assert rows[0] == {"season_offset": 0, "slot": 1, "player_uids": []}
    assert rows[-1] == {"season_offset": 2, "slot": 27, "player_uids": []}


def test_validation_reports_fm27_planner_row_count(tmp_path: Path) -> None:
    path = planner_path(tmp_path, LEAD + group() * 4 + FOOTER)
    with open_fm27(path) as save:
        report = fmsave.validate_save(save)

    planner = next(reader for reader in report.readers if reader.reader == "squad_planner")
    assert (planner.status, planner.record_count) == ("ok", 81)
    assert report.field_statuses["SquadPlannerSlot.player_uids"] == "unconfirmed"
