from __future__ import annotations

import csv
import io
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import ClassVar

import pandas
import pytest

from fmsave.export import (
    column_names,
    flatten_dict,
    record_to_dict,
    select_columns,
    to_columns,
    to_pandas,
    to_polars,
    write_csv,
    write_json,
    write_jsonl,
)
from fmsave.models import CodedValue, ContractEndSource


class ExampleStatus(IntEnum):
    UNKNOWN = -1
    FIRST_CHOICE = 3


class ExampleKind(IntEnum):
    UNKNOWN = -1
    MIN_FEE_RELEASE = 0x11


@dataclass(frozen=True, slots=True)
class ExampleGroup:
    current: int | None
    potential: int | None


@dataclass(frozen=True, slots=True)
class ExampleClause:
    kind: CodedValue[ExampleKind] | None
    value: int | None


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("money_a", "e8")

    uid: int
    name: str
    birth_date: date | None
    ability: ExampleGroup
    squad_status: CodedValue[ExampleStatus] | None
    end_source: ContractEndSource
    nation_ids: tuple[int, ...]
    clauses: tuple[ExampleClause, ...]
    on_loan: bool | None
    unknown: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ExampleContractHolder:
    uid: int
    ability: ExampleGroup | None


@dataclass(frozen=True, slots=True)
class ExampleWithFloat:
    rating: float


@dataclass(frozen=True, slots=True)
class ExampleWithCollidingNames:
    ability: ExampleGroup
    ability_current: int


FULL_RECORD = ExampleRecord(
    uid=1001,
    name="Alex Example",
    birth_date=date(2004, 2, 29),
    ability=ExampleGroup(140, 165),
    squad_status=CodedValue.from_raw(ExampleStatus, 3),
    end_source=ContractEndSource.TAIL,
    nation_ids=(12, 40),
    clauses=(ExampleClause(CodedValue.from_raw(ExampleKind, 0x11), 250000),),
    on_loan=None,
    unknown={"money_a": 7},
)

SPARSE_RECORD = ExampleRecord(
    uid=1002,
    name="Sam Example",
    birth_date=None,
    ability=ExampleGroup(None, None),
    squad_status=CodedValue.from_raw(ExampleStatus, 9),
    end_source=ContractEndSource.NONE,
    nation_ids=(),
    clauses=(),
    on_loan=None,
    unknown={},
)

EXPECTED_FULL_FLAT_ROW: dict[str, object] = {
    "uid": 1001,
    "name": "Alex Example",
    "birth_date": date(2004, 2, 29),
    "ability_current": 140,
    "ability_potential": 165,
    "squad_status": "first_choice",
    "squad_status_code": 3,
    "end_source": "tail",
    "nation_ids": (12, 40),
    "clauses": ({"kind": "min_fee_release", "kind_code": 17, "value": 250000},),
    "on_loan": None,
    "unknown_money_a": 7,
    "unknown_e8": None,
}

BOTH_RECORDS = (FULL_RECORD, SPARSE_RECORD)


def flat_rows(records: tuple[ExampleRecord, ...]) -> list[dict[str, object]]:
    return [flatten_dict(record_to_dict(record, json_ready=False)) for record in records]


def test_flat_dict_has_the_expected_values_in_declaration_order() -> None:
    flat_row = flatten_dict(record_to_dict(FULL_RECORD, json_ready=False))
    assert list(flat_row.items()) == list(EXPECTED_FULL_FLAT_ROW.items())
    assert type(flat_row["end_source"]) is str


def test_nested_dict_keeps_groups_and_coded_siblings() -> None:
    nested_row = record_to_dict(FULL_RECORD, json_ready=True)
    assert nested_row["ability"] == {"current": 140, "potential": 165}
    assert nested_row["birth_date"] == "2004-02-29"
    assert nested_row["nation_ids"] == [12, 40]
    assert nested_row["clauses"] == [{"kind": "min_fee_release", "kind_code": 17, "value": 250000}]
    assert nested_row["unknown"] == {"money_a": 7, "e8": None}


def test_column_names_match_the_flat_dict_keys() -> None:
    assert column_names(ExampleRecord) == tuple(EXPECTED_FULL_FLAT_ROW)
    for record in BOTH_RECORDS:
        for json_ready in (False, True):
            flat_row = flatten_dict(record_to_dict(record, json_ready=json_ready))
            assert tuple(flat_row) == column_names(ExampleRecord)


def test_missing_coded_value_gives_both_keys_none() -> None:
    clause = ExampleClause(kind=None, value=None)
    assert record_to_dict(clause, json_ready=True) == {
        "kind": None,
        "kind_code": None,
        "value": None,
    }


def test_missing_group_keeps_its_columns_as_none() -> None:
    holder = ExampleContractHolder(uid=5, ability=None)
    assert flatten_dict(record_to_dict(holder, json_ready=False)) == {
        "uid": 5,
        "ability_current": None,
        "ability_potential": None,
    }
    assert column_names(ExampleContractHolder) == ("uid", "ability_current", "ability_potential")


def test_unsupported_annotation_raises_type_error_naming_the_field() -> None:
    with pytest.raises(TypeError, match="rating"):
        column_names(ExampleWithFloat)


def test_colliding_column_names_raise_type_error() -> None:
    with pytest.raises(TypeError, match="ability_current"):
        column_names(ExampleWithCollidingNames)


def test_flatten_dict_keeps_sequences_whole() -> None:
    nested = {"top": 1, "group": {"inner": {"deep": [1, 2]}, "items": ({"kept": 1},)}}
    assert flatten_dict(nested) == {
        "top": 1,
        "group_inner_deep": [1, 2],
        "group_items": ({"kept": 1},),
    }


def normalized_cell(cell: object) -> object:
    if isinstance(cell, (list, tuple)):
        return list(cell)
    if cell is None:
        return None
    if isinstance(cell, float) and math.isnan(cell):
        return None
    if cell is pandas.NA or cell is pandas.NaT:
        return None
    return cell


def test_flattening_matches_pandas_json_normalize() -> None:
    nested_rows = [record_to_dict(record, json_ready=True) for record in BOTH_RECORDS]
    frame = pandas.json_normalize(nested_rows, sep="_")
    expected_columns = column_names(ExampleRecord)
    # json_normalize lists top-level values before flattened groups, so compare names only.
    assert len(frame.columns) == len(expected_columns)
    assert set(frame.columns) == set(expected_columns)
    for row_index, nested_row in enumerate(nested_rows):
        expected_row = flatten_dict(nested_row)
        for column_name in expected_columns:
            assert normalized_cell(frame.at[row_index, column_name]) == normalized_cell(
                expected_row[column_name]
            ), column_name


def test_csv_writes_header_and_cells(tmp_path: Path) -> None:
    csv_path = tmp_path / "players.csv"
    write_csv(flat_rows(BOTH_RECORDS), column_names(ExampleRecord), csv_path)
    csv_text = csv_path.read_bytes().decode("utf-8")
    csv_lines = csv_text.split("\r\n")
    assert csv_lines[0] == ",".join(column_names(ExampleRecord))
    assert csv_lines[1] == (
        "1001,Alex Example,2004-02-29,140,165,first_choice,3,tail,12;40,"
        '"[{""kind"":""min_fee_release"",""kind_code"":17,""value"":250000}]",,7,'
    )
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        parsed_rows = list(csv.DictReader(csv_file))
    assert len(parsed_rows) == 2
    assert parsed_rows[1]["squad_status"] == "unknown"
    assert parsed_rows[1]["squad_status_code"] == "9"
    assert parsed_rows[1]["birth_date"] == ""


def test_csv_booleans_and_stream_destination_stays_open() -> None:
    stream = io.StringIO(newline="")
    write_csv(
        [{"on_loan": True, "free": False, "dates": (date(2030, 1, 2),)}],
        ["on_loan", "free", "dates"],
        stream,
    )
    assert not stream.closed
    assert stream.getvalue() == "on_loan,free,dates\r\ntrue,false,2030-01-02\r\n"


def test_csv_round_trips_non_ascii_text(tmp_path: Path) -> None:
    non_ascii_name = "Łukasz Exämple 東京"
    csv_path = tmp_path / "names.csv"
    write_csv([{"uid": 1, "name": non_ascii_name}], ["uid", "name"], csv_path)
    assert non_ascii_name in csv_path.read_bytes().decode("utf-8")
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        parsed_rows = list(csv.reader(csv_file))
    assert parsed_rows == [["uid", "name"], ["1", non_ascii_name]]


def test_json_writes_iso_dates_and_nulls(tmp_path: Path) -> None:
    json_path = tmp_path / "players.json"
    nested_rows = [record_to_dict(record, json_ready=True) for record in BOTH_RECORDS]
    write_json(nested_rows, json_path)
    file_bytes = json_path.read_bytes()
    assert b"\r" not in file_bytes
    file_text = file_bytes.decode("utf-8")
    assert file_text == json.dumps(nested_rows, ensure_ascii=False, indent=2) + "\n"
    loaded_rows = json.loads(file_text)
    assert loaded_rows[0]["birth_date"] == "2004-02-29"
    assert loaded_rows[1]["birth_date"] is None
    assert loaded_rows[0]["unknown"] == {"money_a": 7, "e8": None}
    assert loaded_rows == nested_rows


def test_json_of_no_rows_is_an_empty_array(tmp_path: Path) -> None:
    json_path = tmp_path / "empty.json"
    write_json([], json_path)
    assert json_path.read_text(encoding="utf-8") == "[]\n"


def test_jsonl_writes_one_compact_object_per_line(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "players.jsonl"
    nested_rows = [record_to_dict(record, json_ready=True) for record in BOTH_RECORDS]
    nested_rows[0]["name"] = "Łukasz Exämple 東京"
    write_jsonl(nested_rows, jsonl_path)
    file_bytes = jsonl_path.read_bytes()
    assert b"\r" not in file_bytes
    file_lines = file_bytes.decode("utf-8").split("\n")
    assert file_lines[-1] == ""
    json_lines = file_lines[:-1]
    assert len(json_lines) == 2
    assert ": " not in json_lines[1]
    assert "Łukasz Exämple 東京" in json_lines[0]
    loaded_rows = [json.loads(json_line) for json_line in json_lines]
    assert loaded_rows[0]["birth_date"] == "2004-02-29"
    assert loaded_rows[1]["on_loan"] is None
    assert loaded_rows == nested_rows


def test_unknown_key_outside_the_declared_keys_raises_value_error() -> None:
    record = ExampleRecord(
        uid=1003,
        name="Jo Example",
        birth_date=None,
        ability=ExampleGroup(None, None),
        squad_status=None,
        end_source=ContractEndSource.FALLBACK,
        nation_ids=(),
        clauses=(),
        on_loan=False,
        unknown={"money_a": 1, "stray": 2},
    )
    with pytest.raises(ValueError, match="stray"):
        record_to_dict(record, json_ready=False)


def test_select_columns_keeps_the_requested_order() -> None:
    flat_row = flatten_dict(record_to_dict(FULL_RECORD, json_ready=False))
    assert select_columns(flat_row, ["name", "ability_current"]) == {
        "name": "Alex Example",
        "ability_current": 140,
    }
    with pytest.raises(ValueError, match="nope"):
        select_columns(flat_row, ["name", "nope"])


def test_to_columns_keeps_python_values() -> None:
    columns = to_columns(BOTH_RECORDS, ExampleRecord)
    assert tuple(columns) == column_names(ExampleRecord)
    assert columns["birth_date"] == [date(2004, 2, 29), None]
    assert columns["nation_ids"] == [(12, 40), ()]


def test_to_pandas_uses_nullable_integers_for_integer_columns_with_none() -> None:
    frame = to_pandas(to_columns(BOTH_RECORDS, ExampleRecord))
    assert len(frame) == 2
    assert frame["ability_current"].dtype == "Int64"
    assert frame["uid"].dtype == "int64"
    assert list(frame.columns) == list(column_names(ExampleRecord))


def test_to_polars_builds_a_frame_of_every_column() -> None:
    frame = to_polars(to_columns(BOTH_RECORDS, ExampleRecord))
    assert frame.shape == (2, 13)


def test_to_pandas_without_pandas_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)
    with pytest.raises(ImportError, match=r"fmsave\[pandas\]"):
        to_pandas({"uid": [1]})


def test_to_polars_without_polars_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "polars", None)
    with pytest.raises(ImportError, match=r"fmsave\[polars\]"):
        to_polars({"uid": [1]})
