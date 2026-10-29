from __future__ import annotations

from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import FALLBACK_BUILD
from fmsave.export import column_names, record_to_dict
from fmsave.readers.nations import find_nation_table_layout, read_nations
from tests.fixtures.nations import nation_table_bytes

LAYOUT = find_nation_table_layout(4000, FALLBACK_BUILD)


def test_nations_use_save_local_ids_and_database_ids() -> None:
    rows, stats = read_nations(b"noise" + nation_table_bytes() + b"noise", LAYOUT)
    assert len(rows) == 251
    assert rows[0].nation_id == 0
    assert record_to_dict(rows[-1], json_ready=True) == {"nation_id": 250, "database_id": 900_250}
    assert stats.tables == 1
    assert stats.database_id_copies == len(rows)
    assert column_names(fmsave.Nation) == ("nation_id", "database_id")
    assert fmsave.field_status(fmsave.Nation, "database_id") == "unconfirmed"


@pytest.mark.parametrize(
    "data",
    [b"", nation_table_bytes()[:-1], nation_table_bytes() * 2],
    ids=("missing", "truncated", "ambiguous"),
)
def test_missing_truncated_or_ambiguous_tables_emit_no_nations(data: bytes) -> None:
    rows, stats = read_nations(data, LAYOUT)
    assert rows == ()
    assert stats.tables != 1


def test_duplicate_database_ids_and_wrong_ordinals_reject_the_table() -> None:
    data = nation_table_bytes()
    first = (900_000).to_bytes(4, "little")
    second = (900_001).to_bytes(4, "little")
    assert read_nations(data.replace(second, first), LAYOUT)[0] == ()
    footer_at = data.index(first) - 4
    wrong_ordinal = data[:footer_at] + (1).to_bytes(4, "little") + data[footer_at + 4 :]
    assert read_nations(wrong_ordinal, LAYOUT)[0] == ()


def test_nations_are_cached_and_survive_save_close(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as save:
        table = save.nations()
        assert save.nations() is table
        assert len(table) == 251
    assert table[0].nation_id == 0
    with pytest.raises(fmsave.SaveClosedError):
        save.nations()


def test_nation_checks_reject_missing_or_ambiguous_tables_on_full_saves() -> None:
    from fmsave._checks import evaluate_nations
    from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, GateBounds, find_layout
    from fmsave._reader_stats import NationStats

    bounds = find_layout(GateBounds, "game_db", 4000, FALLBACK_BUILD).layout
    for tables in (0, 2):
        gates = evaluate_nations(
            NationStats(candidates=tables, tables=tables, rows=0, database_id_copies=0),
            bounds,
            FULL_SAVE_MINIMUM_GAME_DB_BYTES,
        )
        assert gates[0].applied and not gates[0].passed
        assert not gates[1].applied


def test_nation_checks_report_disagreeing_database_id_copies() -> None:
    from fmsave._checks import evaluate_nations
    from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, GateBounds, find_layout
    from fmsave._reader_stats import NationStats

    bounds = find_layout(GateBounds, "game_db", 4000, FALLBACK_BUILD).layout
    gates = evaluate_nations(
        NationStats(candidates=1, tables=1, rows=251, database_id_copies=0),
        bounds,
        FULL_SAVE_MINIMUM_GAME_DB_BYTES,
    )
    assert gates[0].passed
    assert gates[1].applied and not gates[1].passed


@pytest.mark.parametrize("cut", [1, 5, 9, 13, 32, 100])
def test_truncated_record_fields_do_not_read_past_the_buffer(cut: int) -> None:
    assert read_nations(nation_table_bytes()[:cut], LAYOUT)[0] == ()
