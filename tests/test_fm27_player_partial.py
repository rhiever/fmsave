"""FM27 player, contract, and suspension reads with and without strict validation."""

from __future__ import annotations

import struct
import warnings
from pathlib import Path

import pytest

import fmsave
from fmsave import _checks
from fmsave._checks import GateResult, ReaderCheck
from fmsave._frozen import FrozenMapping
from fmsave._layouts import GateBounds
from fmsave._reader_stats import PlayerStats
from fmsave.export import record_to_dict
from tests.fixtures.career import player_bytes
from tests.fixtures.container import packed_date
from tests.fixtures.game_db import name_pools_bytes, suspension_entry_bytes
from tests.test_fm27_club_table import club_body
from tests.test_fm27_experimental import BUILD, UNREGISTERED_BUILD, fm27_fragment
from tests.test_fm27_persons import shifted_block


def fm27_player_path(
    tmp_path: Path, *, birth_year: int = 2004, build: str = BUILD, with_ban: bool = False
) -> Path:
    clubs = struct.pack("<IB", 1, 0) + club_body(finance=0) + struct.pack("<III", 0, 6100, 6100)
    person = shifted_block(relations=False, birth_year=birth_year)
    ban = (
        suspension_entry_bytes(scope_id=222, issued=packed_date(182, 2032), e7=3, scope_code=1)
        if with_ban
        else b""
    )
    player = player_bytes(
        pindex=100,
        uid=8000,
        team_id=71001,
        current_ability=120,
        potential_ability=150,
        transfer_value_raw=500_000,
        height_cm=180,
        trailing=person + ban,
    )
    data = name_pools_bytes(("Alex",), ("Example",), ()) + clubs + bytes(256) + player
    return fm27_fragment(tmp_path, game_db=data, build=build)


def fm27_player_save(
    tmp_path: Path,
    *,
    birth_year: int = 2004,
    build: str = BUILD,
    strict: bool = False,
    with_ban: bool = False,
) -> fmsave.Save:
    path = fm27_player_path(tmp_path, birth_year=birth_year, build=build, with_ban=with_ban)
    with pytest.warns(fmsave.UnknownBuildWarning, match="FM27"):
        return fmsave.open(path, strict=strict)


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
def test_strict_fm27_advisory_suspension_check_preserves_all_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_reader: str
) -> None:
    monkeypatch.setattr(_checks, "check_suspensions", failing_suspension_check)
    with fm27_player_save(tmp_path, strict=True, with_ban=True) as save:
        with pytest.warns(fmsave.ReaderCheckWarning, match="suspension_entries_minimum"):
            getattr(save, first_reader)()
        rows = save.players()
        assert len(rows) == 1
        assert rows[0].suspensions is not None
        assert len(rows[0].suspensions) == 1
        assert record_to_dict(rows[0], json_ready=True)["suspensions"] is not None
        assert rows.coverage["suspensions"] == 1.0
        assert len(save.contracts()) == 0
        assert len(save.suspensions()) == 1


def test_fm27_suspension_check_that_passes_is_kept_for_validation(tmp_path: Path) -> None:
    with fm27_player_save(tmp_path) as save:
        save.players()
        report = fmsave.validate_save(save)

    (suspensions,) = [reader for reader in report.readers if reader.reader == "suspensions"]
    assert suspensions.status == "ok"
    assert "suspension_entries_minimum" in [gate.name for gate in suspensions.gates]


def failing_player_check(*_args: object) -> ReaderCheck:
    gate = GateResult("relation_sentinel", 0, 1, None, passed=False, applied=True)
    return ReaderCheck("players", 0, (gate,), FrozenMapping({}))


@pytest.mark.parametrize("reader", ["players", "contracts", "suspensions"])
def test_fm27_failed_player_check_stops_all_three_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str
) -> None:
    monkeypatch.setattr(_checks, "check_players", failing_player_check)
    with (
        fm27_player_save(tmp_path, strict=True) as save,
        pytest.raises(fmsave.ReaderCheckError, match="relation_sentinel"),
    ):
        getattr(save, reader)()


@pytest.mark.parametrize("build", [BUILD, UNREGISTERED_BUILD])
def test_fm27_default_returns_players_after_a_failed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build: str
) -> None:
    monkeypatch.setattr(_checks, "check_players", failing_player_check)
    with fm27_player_save(tmp_path, build=build) as save:
        with pytest.warns(fmsave.ReaderCheckWarning, match="relation_sentinel"):
            players = save.players()
        assert len(players) == 1
        assert save.players() is players


def test_fm27_default_returns_decoded_suspensions_after_a_failed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_checks, "check_suspensions", failing_suspension_check)
    with fm27_player_save(tmp_path, with_ban=True) as save:
        with pytest.warns(fmsave.ReaderCheckWarning, match="suspension_entries_minimum"):
            suspensions = save.suspensions()
        assert len(suspensions) == 1
        player = save.players()[0]
        assert player.suspensions is not None
        assert len(player.suspensions) == 1
        assert suspensions[0].player_uid == player.uid


@pytest.fixture
def apply_age_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluate_players = _checks.evaluate_players

    def evaluate_ages(
        stats: PlayerStats, bounds: GateBounds, _game_db_bytes: int
    ) -> tuple[GateResult, ...]:
        # The fixture holds a real person block but is too small for population checks.
        return tuple(
            gate
            for gate in evaluate_players(stats, bounds, bounds.minimum_applies_from_bytes)
            if gate.name in {"age_median", "aged_in_range"}
        )

    monkeypatch.setattr(_checks, "evaluate_players", evaluate_ages)


def test_fm27_young_players_remain_readable(tmp_path: Path, apply_age_checks: None) -> None:
    with fm27_player_save(tmp_path, birth_year=2015, build=UNREGISTERED_BUILD) as save:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", fmsave.ReaderCheckWarning)
            players = save.players()
            contracts = save.contracts()
        assert len(caught) == 1
        assert caught[0].category is fmsave.ReaderCheckWarning
        assert "age_median=17" in str(caught[0].message)
        assert players[0].age == 17
        assert len(contracts) == 0
        (report,) = [
            reader for reader in fmsave.validate_save(save).readers if reader.reader == "players"
        ]
        assert report.status == "ok"
        assert report.coverage["age"] == 1.0
        (median,) = [gate for gate in report.gates if gate.name == "age_median"]
        assert median.observed == 17
        assert not median.passed
        assert median.to_json_dict()["advisory"] is True


def test_fm27_age_range_is_advisory_even_in_strict_mode(
    tmp_path: Path, apply_age_checks: None
) -> None:
    with fm27_player_save(tmp_path, birth_year=1986, strict=True) as save:
        with pytest.warns(fmsave.ReaderCheckWarning, match="aged_in_range"):
            players = save.players()
        assert players[0].age == 46
