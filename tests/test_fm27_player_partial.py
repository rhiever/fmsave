"""Unsupported player subfields stay unknown, never invented empty collections."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

import fmsave
from fmsave.export import record_to_dict
from tests.fixtures.career import player_bytes
from tests.fixtures.game_db import name_pools_bytes
from tests.test_fm27_club_table import club_body
from tests.test_fm27_experimental import fm27_fragment
from tests.test_fm27_persons import shifted_block


def test_fm27_players_keep_unsupported_suspensions_unknown(tmp_path: Path) -> None:
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
    with pytest.warns(UserWarning, match="experimental"):
        save = fmsave.open(fm27_fragment(tmp_path, game_db=data), experimental_fm27=True)
    with save:
        rows = save.players()
        assert len(rows) == 1
        assert rows[0].name == "Alex Example"
        assert rows[0].age == 28
        assert rows[0].height_cm == 180
        assert rows[0].ability.current == 120
        assert rows[0].club_uid == 0
        assert rows[0].suspensions is None
        assert record_to_dict(rows[0], json_ready=True)["suspensions"] is None
        assert rows.coverage["suspensions"] == 0.0
        with pytest.raises(fmsave.UnsupportedGameError):
            save.suspensions()
        assert len(save.contracts()) == 0
