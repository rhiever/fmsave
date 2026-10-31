"""Fictional stadium tables distinguish unavailable and empty fixture calendars."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import fmsave
from fmsave._checks import evaluate_stadiums
from fmsave._errors import ReaderCheckError
from fmsave._layouts import FALLBACK_BUILD, GateBounds, StadiumTableLayout, find_layout
from fmsave.models.stadiums import Stadium
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.stadiums import StadiumIndex, build_stadiums, read_stadium_index
from fmsave.table import Table
from tests.fixtures.career import NORTHBRIDGE_UID, career_fragment
from tests.fixtures.stadiums import stadium_row_bytes, stadium_table_bytes

LAYOUT = find_layout(StadiumTableLayout, "game_db", 4000, FALLBACK_BUILD).layout
BOUNDS = find_layout(GateBounds, "game_db", 4000, FALLBACK_BUILD).layout


def fictional_indexes(tmp_path: Path) -> tuple[StadiumIndex, ClubIndex]:
    # All rows are independently built by test fixtures, never production layouts.
    rows = [
        stadium_row_bytes(
            ordinal=ordinal,
            uid=70_000 + ordinal,
            all_seater=10_000 + ordinal,
            expansion=12_000 + ordinal,
            owner_club_index=1,
            capacity=8_000,
            name="Example Park" if ordinal == 13 else None,
        )
        for ordinal in range(1, 14)
    ]
    index = read_stadium_index(stadium_table_bytes(rows), LAYOUT, "example")
    with fmsave.open(career_fragment().write(tmp_path / "example.bin")) as save:
        clubs = save._context.club_index()
    return index, clubs


def test_unavailable_calendar_preserves_intrinsic_fields_and_owner_join(tmp_path: Path) -> None:
    index, clubs = fictional_indexes(tmp_path)
    rows, stats = build_stadiums(index, clubs, None, LAYOUT)
    assert len(rows) == 13
    ground = rows[-1]
    assert ground.name == "Example Park"
    assert ground.all_seater_capacity == 10_013
    assert ground.expansion_capacity == 12_013
    assert ground.capacity == 8_000
    assert ground.pitch_length_dm == 1050 and ground.pitch_width_dm == 680
    assert ground.owner_club_uid == NORTHBRIDGE_UID
    assert ground.owner_club_name == "Northbridge FC"
    assert all(row.home_club_uids is None and row.home_club_names is None for row in rows)
    assert stats.table_end_reached == 1
    assert stats.owners_set == stats.owners_resolved == 13
    assert stats.clubs_with_home_ground == 0
    assert stats.owning_clubs_with_home_ground == 0
    assert stats.owning_clubs_home_ground_owned == 0
    gates = evaluate_stadiums(stats, BOUNDS, 100_000_000)
    assert any(gate.name == "stadium_rows_minimum" and gate.applied for gate in gates)
    home_gate = next(gate for gate in gates if gate.name == "stadium_home_grounds_owned")
    assert not home_gate.applied


def test_empty_available_calendar_is_present_empty_not_unknown(tmp_path: Path) -> None:
    index, clubs = fictional_indexes(tmp_path)
    unknown, _ = build_stadiums(index, clubs, None, LAYOUT)
    empty, _ = build_stadiums(index, clubs, (), LAYOUT)
    assert unknown[0].home_club_uids is None
    assert empty[0].home_club_uids == ()
    assert empty[0].home_club_names == ()
    assert Table(unknown, Stadium).coverage["home_club_uids"] == 0.0
    assert Table(unknown, Stadium).coverage["home_club_names"] == 0.0
    assert Table(empty, Stadium).coverage["home_club_uids"] == 1.0
    assert Table(empty, Stadium).coverage["home_club_names"] == 1.0
    assert Table(unknown, Stadium).coverage["all_seater_capacity"] == 1.0


def test_unknown_calendar_exports_json_null_not_empty_lists(tmp_path: Path) -> None:
    index, clubs = fictional_indexes(tmp_path)
    rows, _ = build_stadiums(index, clubs, None, LAYOUT)
    decoded = json.loads(json.dumps(Table(rows, Stadium).to_dicts(json_ready=True)))
    assert decoded[0]["home_club_uids"] is None
    assert decoded[0]["home_club_names"] is None
    assert decoded[0]["owner_club_uid"] == NORTHBRIDGE_UID


def test_missing_calendar_does_not_disable_intrinsic_table_end_check(tmp_path: Path) -> None:
    index, clubs = fictional_indexes(tmp_path)
    damaged = dataclasses.replace(index, reached_table_end=False)
    with pytest.raises(ReaderCheckError, match="table end"):
        build_stadiums(damaged, clubs, None, LAYOUT)


def test_fm27_validation_does_not_carry_unsupported_calendar_into_independent_stadiums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_fm27_experimental import fm27_fragment

    # This tests orchestration only: the independently tested stadium reader owns its
    # validation and must still be called after the unsupported shared calendar pass.
    monkeypatch.setattr(fmsave.Save, "stadiums", lambda self: Table((), Stadium))
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(fm27_fragment(tmp_path))
    with save:
        report = fmsave.validate_save(save)
    readers = {reader.reader: reader for reader in report.readers}
    assert readers["fixtures"].status != "ok"
    assert readers["stadiums"].status == "ok"
    assert readers["stadiums"].record_count == 0
