"""Tests for the web app's save reader, docs/app/reader.py, run against the example career.

The app runs reader.py in Pyodide; here it runs in CPython against the same public API.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import re
import sys
from array import array
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import fmsave
from fmsave.export import column_names
from fmsave.models.players import Attributes, Personality, Positions
from tests.fixtures.career import NORTHBRIDGE_TEAM_B, PLAYER_A_UID, PLAYER_B_UID, SOUTHPORT_TEAM

APP_FOLDER = Path(__file__).resolve().parents[1] / "docs" / "app"


def load_reader() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fmsave_web_reader", APP_FOLDER / "reader.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fmsave_web_reader"] = module
    spec.loader.exec_module(module)
    return module


reader: Any = load_reader()


@pytest.fixture
def opened(career_save_path: Path) -> Iterator[dict[str, Any]]:
    meta = reader.open_save(str(career_save_path))
    players = reader.read_players()
    yield {"meta": meta, "players": players}
    reader.close_save()
    reader._state.clear()


def unpack(buffer: bytes, code: str = "f") -> list[float]:
    values = array(code)
    values.frombytes(buffer)
    return list(values)


def test_the_reader_sends_every_attribute_position_and_personality_field() -> None:
    assert set(reader.ATTRIBUTES) == {field.name for field in dataclasses.fields(Attributes)}
    assert set(reader.POSITIONS) == {field.name for field in dataclasses.fields(Positions)}
    assert set(reader.PERSONALITY) == {field.name for field in dataclasses.fields(Personality)}


def test_the_page_knows_every_attribute_the_reader_sends() -> None:
    catalog = (APP_FOLDER / "catalog.js").read_text(encoding="utf-8")
    for name in (*reader.ATTRIBUTES, *reader.POSITIONS, *reader.PERSONALITY):
        assert f'["{name}",' in catalog, name


def test_the_page_lists_the_per_90_columns_fmsave_has() -> None:
    catalog = (APP_FOLDER / "catalog.js").read_text(encoding="utf-8")
    listed = re.search(r"const PER_90 = \[(.*?)\];", catalog, re.DOTALL)
    assert listed is not None
    page = set(re.findall(r'"([a-z_]+)"', listed.group(1)))
    fmsave_rates = {n.removesuffix("_per_90") for n in reader.stat_names() if n.endswith("_per_90")}
    assert page == fmsave_rates - {"headers_lost"}


def test_stat_names_are_the_numeric_season_stats_columns() -> None:
    names = reader.stat_names()
    assert names == [
        name
        for name in column_names(fmsave.PlayerSeasonStats)
        if name not in reader.STAT_SKIP and name != "team_slot"
    ]
    assert {"minutes", "expected_goals", "expected_goals_per_90"} <= set(names)


def test_players_cross_as_one_packed_column_per_field(opened: dict[str, Any]) -> None:
    players = opened["players"]
    count = players["count"]
    assert count > 0
    numbers = players["numbers"]
    assert len(numbers["uid"]) == 8 * count
    assert len(numbers["ability_current"]) == 4 * count
    for name in reader.ATTRIBUTES:
        assert len(numbers[f"attributes_{name}"]) == 4 * count
    assert len(players["text"]["name"]) == count
    assert all(players["text"]["name"])
    uids = unpack(numbers["uid"], "d")
    assert PLAYER_A_UID in uids
    assert opened["meta"]["fmsave"] == fmsave.__version__


def test_the_packed_values_match_the_records(
    opened: dict[str, Any], career_save_path: Path
) -> None:
    numbers = opened["players"]["numbers"]
    uids = unpack(numbers["uid"], "d")
    with fmsave.open(career_save_path) as career_save:
        player = career_save.players().by_uid(PLAYER_A_UID)
    index = uids.index(PLAYER_A_UID)
    assert unpack(numbers["ability_current"])[index] == player.ability.current
    assert unpack(numbers["attributes_finishing"])[index] == player.attributes.finishing
    assert unpack(numbers["positions_stc"])[index] == player.positions.stc
    end = unpack(numbers["contract_end"])[index]
    if player.contract is None or player.contract.end is None:
        assert math.isnan(end)
    else:
        assert end == (player.contract.end - reader._EPOCH).days


def test_overall_stats_line_up_with_the_players(opened: dict[str, Any]) -> None:
    del opened
    stats = reader.read_stats()
    uids = unpack(_uids(), "d")
    minutes = unpack(stats["numbers"]["minutes"])
    assert minutes[uids.index(PLAYER_A_UID)] == 1080
    assert math.isnan(minutes[uids.index(PLAYER_B_UID)])


def test_a_player_with_two_teams_gets_their_rows_added_up(opened: dict[str, Any]) -> None:
    del opened
    reader.read_stats()
    uids = unpack(_uids(), "d")
    league = reader.stats_columns("league")
    minutes = unpack(league["minutes"])
    assert minutes[uids.index(PLAYER_A_UID)] == 1080 + 90
    rows = [
        row
        for row in reader._state["stats"]
        if row.player_uid == PLAYER_A_UID and row.kind == "league"
    ]
    assert {row.team_id for row in rows} == {SOUTHPORT_TEAM, NORTHBRIDGE_TEAM_B}


def _uids() -> bytes:
    return array("d", (player.uid for player in reader._state["players"])).tobytes()


def test_player_detail_holds_the_record_and_its_stats(opened: dict[str, Any]) -> None:
    del opened
    reader.read_stats()
    detail = reader.player_detail(PLAYER_A_UID)
    assert detail["player"]["uid"] == PLAYER_A_UID
    assert len(detail["stats"]) == 3
    missing = reader.call("player_detail", 1)
    assert missing == {"error": "That player is not in this save."}


@pytest.mark.parametrize("name", ["players", "squad", "season-stats"])
def test_each_download_writes_a_csv(opened: dict[str, Any], tmp_path: Path, name: str) -> None:
    del opened
    reader.read_stats()
    path = tmp_path / f"{name}.csv"
    rows = reader.write_csv(name, str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == rows + 1
    if name == "players":
        assert lines[0].split(",") == list(column_names(fmsave.Player))


def test_an_unknown_request_is_refused_with_a_safe_message(opened: dict[str, Any]) -> None:
    del opened
    reader.read_stats()
    assert reader.call("stats_columns", "friendlies") == {"error": "Unknown competition."}
    assert reader.call("write_csv", "everything", "/tmp/x.csv") == {"error": "Unknown download."}


def test_a_file_that_is_not_a_save_gives_a_message_without_its_content(tmp_path: Path) -> None:
    path = tmp_path / "Alex Example notes.fm"
    path.write_bytes(b"Northbridge FC secret plans " * 100)
    result = reader.call("open_save", str(path))
    assert set(result) == {"error"}
    assert "not a Football Manager save" in result["error"]
    assert "Northbridge" not in result["error"] and "Alex" not in result["error"]


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (fmsave.UnsupportedGameError("Alex Example"), "cannot read yet"),
        (fmsave.CorruptSaveError("Alex Example"), "damaged"),
        (fmsave.SaveChangedError("Alex Example"), "changed while"),
        (fmsave.ReaderCheckError("Alex Example"), "ReaderCheckError"),
        (MemoryError(), "out of memory"),
        (ValueError("Alex Example"), "ValueError"),
    ],
)
def test_errors_map_to_messages_that_never_echo_their_text(error: Exception, words: str) -> None:
    message = reader.friendly_error(error)
    assert words in message
    assert "Alex" not in message


def test_the_page_allows_only_the_hosts_it_needs() -> None:
    page = (APP_FOLDER / "index.html").read_text(encoding="utf-8")
    policy = re.search(r'Content-Security-Policy" content="([^"]+)"', page)
    assert policy is not None
    hosts = set(re.findall(r"https://([a-z.]+)", policy.group(1)))
    assert hosts == {
        "cdn.jsdelivr.net",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "pypi.org",
        "files.pythonhosted.org",
    }
    scripts = "".join(path.read_text(encoding="utf-8") for path in APP_FOLDER.glob("*.js"))
    assert set(re.findall(r"https://([a-z.]+)", scripts)) == {"cdn.jsdelivr.net"}


def test_money_and_uids_cross_as_float64(opened: dict[str, Any]) -> None:
    numbers = opened["players"]["numbers"]
    count = opened["players"]["count"]
    for name in ("uid", "club_uid", "transfer_value", "contract_wage"):
        assert len(numbers[name]) == 8 * count, name


def test_opening_a_save_drops_what_the_last_one_left(career_save_path: Path) -> None:
    reader.open_save(str(career_save_path))
    reader.read_players()
    reader.read_stats()
    reader.open_save(str(career_save_path))
    assert {"players", "stats", "stats_by_player", "order"}.isdisjoint(reader._state)
    reader.close_save()
    reader._state.clear()


def test_a_save_without_a_managed_club_has_no_squad_download(
    opened: dict[str, Any], tmp_path: Path
) -> None:
    del opened
    reader._state["club_uid"] = None
    result = reader.call("write_csv", "squad", str(tmp_path / "squad.csv"))
    assert result == {"error": "This save has no managed club, so there is no squad to download."}
    assert not (tmp_path / "squad.csv").exists()


def test_combined_rows_add_counts_and_weight_the_rating(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        rows = [
            r
            for r in career_save.player_season_stats()
            if r.player_uid == PLAYER_A_UID and r.kind == "league"
        ]
    total = reader.combined(rows)
    assert total.minutes == sum(r.minutes for r in rows)
    assert total.goals == sum(r.goals for r in rows)
    assert total.team_id is None and total.club_uid is None
    rated = [(r.average_rating, r.rated_appearances) for r in rows if r.average_rating]
    if rated:
        expected = sum(a * n for a, n in rated) / sum(n for _, n in rated)
        assert total.average_rating == pytest.approx(expected)
    assert reader.combined(rows[:1]) is rows[0]


def test_a_read_error_from_disk_gets_a_message_about_the_save_changing() -> None:
    assert "saved over it" in reader.friendly_error(OSError(29, "I/O error"))
