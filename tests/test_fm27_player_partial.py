"""FM27 players keep suspensions unknown when the suspension check fails, never empty."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

import fmsave
from fmsave import _checks
from fmsave._checks import GateResult, ReaderCheck
from fmsave._frozen import FrozenMapping
from fmsave.export import record_to_dict
from tests.fixtures.career import player_bytes
from tests.fixtures.game_db import name_pools_bytes
from tests.test_fm27_club_table import club_body
from tests.test_fm27_experimental import fm27_fragment
from tests.test_fm27_persons import shifted_block


def fm27_player_save(tmp_path: Path) -> fmsave.Save:
    clubs = struct.pack("<IB", 1, 0) + club_body(finance=0) + struct.pack("<III", 0, 6100, 6100)
    person = shifted_block(relations=False)
    player = player_bytes(
        pindex=100,
        uid=8000,
        team_id=71001,
        current_ability=120,
        potential_ability=150,
        transfer_value_raw=500_000,
        height_cm=180,
        trailing=person,
    )
    data = name_pools_bytes(("Alex",), ("Example",), ()) + clubs + bytes(256) + player
    with pytest.warns(UserWarning, match="FM27"):
        return fmsave.open(fm27_fragment(tmp_path, game_db=data))


def test_fm27_players_carry_the_suspensions_the_search_found(tmp_path: Path) -> None:
    with fm27_player_save(tmp_path) as save:
        rows = save.players()
        assert len(rows) == 1
        assert rows[0].name == "Alex Example"
        assert rows[0].age == 28
        assert rows[0].height_cm == 180
        assert rows[0].ability.current == 120
        assert rows[0].club_uid == 0
        assert rows[0].suspensions == ()
        assert len(save.suspensions()) == 0
        assert len(save.contracts()) == 0


def failing_suspension_check(*_args: object) -> ReaderCheck:
    gate = GateResult("suspension_entries_minimum", 0, 1, None, passed=False, applied=True)
    return ReaderCheck("suspensions", 0, (gate,), FrozenMapping({}))


@pytest.mark.parametrize("first_reader", ["players", "contracts", "suspensions"])
def test_fm27_failed_suspension_check_stops_only_suspensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_reader: str
) -> None:
    monkeypatch.setattr(_checks, "check_suspensions", failing_suspension_check)
    with fm27_player_save(tmp_path) as save:
        if first_reader == "suspensions":
            with pytest.raises(fmsave.ReaderCheckError, match="suspension_entries_minimum"):
                save.suspensions()
        else:
            getattr(save, first_reader)()
        rows = save.players()
        assert len(rows) == 1
        assert rows[0].suspensions is None
        assert record_to_dict(rows[0], json_ready=True)["suspensions"] is None
        assert rows.coverage["suspensions"] == 0.0
        assert len(save.contracts()) == 0
        with pytest.raises(fmsave.ReaderCheckError, match="suspension_entries_minimum"):
            save.suspensions()
