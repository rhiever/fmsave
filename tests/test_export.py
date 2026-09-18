from __future__ import annotations

import csv
import io
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import ClassVar, cast

import pytest

from fmsave._frozen import FrozenMapping
from fmsave.export import (
    column_names,
    flat_rows,
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
from fmsave.table import Table
from tests.helpers.export_asserts import assert_matches_json_normalize


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
    rating: float | None


@dataclass(frozen=True, slots=True)
class ExampleWithUnsupportedValue:
    rating: complex


@dataclass(frozen=True, slots=True)
class ExampleWithCollidingNames:
    ability: ExampleGroup
    ability_current: int


class ExampleTrait(IntEnum):
    UNKNOWN = -1
    TRIES_LONG_SHOTS = 12


@dataclass(frozen=True, slots=True)
class ExampleWithCodeSuffixClash:
    status: CodedValue[ExampleStatus] | None
    status_code: int


@dataclass(frozen=True, slots=True)
class ExampleWithoutUnknownKeys:
    uid: int
    unknown: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ExampleSectionList:
    """A record whose mapping field is keyed on the save rather than on the class."""

    name: str
    section_schemas: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ExampleSquadMember:
    uid: int
    traits: tuple[CodedValue[ExampleTrait], ...]
    home_grown_club_names: tuple[str | None, ...]
    chain_club_uids: tuple[int | None, ...]
    on_loan: bool


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


def flattened_record_dicts(records: Sequence[object]) -> list[dict[str, object]]:
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
        column_names(ExampleWithUnsupportedValue)


def test_a_float_is_a_plain_column_like_an_int() -> None:
    assert column_names(ExampleWithFloat) == ("rating",)
    float_records = [ExampleWithFloat(7.8), ExampleWithFloat(None)]
    assert to_columns(float_records, ExampleWithFloat) == {"rating": [7.8, None]}
    assert record_to_dict(float_records[0], json_ready=True) == {"rating": 7.8}
    assert_matches_json_normalize(float_records, ExampleWithFloat)


def test_colliding_column_names_raise_value_error() -> None:
    with pytest.raises(ValueError, match="ability_current"):
        column_names(ExampleWithCollidingNames)
    record = ExampleWithCollidingNames(ability=ExampleGroup(1, 2), ability_current=3)
    with pytest.raises(ValueError, match="ability_current"):
        record_to_dict(record, json_ready=False)


def test_coded_field_clashing_with_a_code_suffix_field_raises_value_error() -> None:
    record = ExampleWithCodeSuffixClash(status=CodedValue.from_raw(ExampleStatus, 3), status_code=4)
    with pytest.raises(ValueError, match="status_code"):
        record_to_dict(record, json_ready=False)


def test_flatten_dict_keeps_sequences_whole() -> None:
    nested = {"top": 1, "group": {"inner": {"deep": [1, 2]}, "items": ({"kept": 1},)}}
    assert flatten_dict(nested) == {
        "top": 1,
        "group_inner_deep": [1, 2],
        "group_items": ({"kept": 1},),
    }


def test_flattening_matches_pandas_json_normalize() -> None:
    assert_matches_json_normalize(BOTH_RECORDS, ExampleRecord)


def test_csv_writes_header_and_cells(tmp_path: Path) -> None:
    csv_path = tmp_path / "players.csv"
    write_csv(flattened_record_dicts(BOTH_RECORDS), column_names(ExampleRecord), csv_path)
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


MEMBER_WITH_TRAITS = ExampleSquadMember(
    uid=2001,
    traits=(CodedValue.from_raw(ExampleTrait, 12), CodedValue.from_raw(ExampleTrait, 40)),
    home_grown_club_names=("Northbridge FC", None, "Example Rovers"),
    chain_club_uids=(31, None, 33),
    on_loan=True,
)

MEMBER_WITHOUT_TRAITS = ExampleSquadMember(
    uid=2002, traits=(), home_grown_club_names=(), chain_club_uids=(None,), on_loan=False
)

BOTH_MEMBERS = (MEMBER_WITH_TRAITS, MEMBER_WITHOUT_TRAITS)

MEMBER_COLUMNS = (
    "uid",
    "traits",
    "traits_code",
    "home_grown_club_names",
    "chain_club_uids",
    "on_loan",
)


def test_column_names_cover_optional_item_and_coded_value_tuples() -> None:
    assert column_names(ExampleSquadMember) == MEMBER_COLUMNS
    for member in BOTH_MEMBERS:
        for json_ready in (False, True):
            flat_row = flatten_dict(record_to_dict(member, json_ready=json_ready))
            assert tuple(flat_row) == MEMBER_COLUMNS


def test_optional_item_tuples_keep_their_none_items() -> None:
    flat_row = flatten_dict(record_to_dict(MEMBER_WITH_TRAITS, json_ready=False))
    assert flat_row["home_grown_club_names"] == ("Northbridge FC", None, "Example Rovers")
    assert flat_row["chain_club_uids"] == (31, None, 33)
    nested_row = record_to_dict(MEMBER_WITH_TRAITS, json_ready=True)
    assert nested_row["home_grown_club_names"] == ["Northbridge FC", None, "Example Rovers"]
    assert nested_row["chain_club_uids"] == [31, None, 33]
    columns = to_columns(BOTH_MEMBERS, ExampleSquadMember)
    assert columns["home_grown_club_names"] == [("Northbridge FC", None, "Example Rovers"), ()]
    assert columns["chain_club_uids"] == [(31, None, 33), (None,)]


def test_coded_value_tuples_become_label_and_code_sequences() -> None:
    flat_row = flatten_dict(record_to_dict(MEMBER_WITH_TRAITS, json_ready=False))
    assert flat_row["traits"] == ("tries_long_shots", "unknown")
    assert flat_row["traits_code"] == (12, 40)
    nested_row = record_to_dict(MEMBER_WITH_TRAITS, json_ready=True)
    assert nested_row["traits"] == ["tries_long_shots", "unknown"]
    assert nested_row["traits_code"] == [12, 40]
    empty_flat_row = flatten_dict(record_to_dict(MEMBER_WITHOUT_TRAITS, json_ready=False))
    assert empty_flat_row["traits"] == ()
    assert empty_flat_row["traits_code"] == ()
    empty_nested_row = record_to_dict(MEMBER_WITHOUT_TRAITS, json_ready=True)
    assert empty_nested_row["traits"] == []
    assert empty_nested_row["traits_code"] == []
    columns = to_columns(BOTH_MEMBERS, ExampleSquadMember)
    assert columns["traits"] == [("tries_long_shots", "unknown"), ()]
    assert columns["traits_code"] == [(12, 40), ()]


def test_optional_item_and_coded_value_tuples_in_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "members.csv"
    write_csv(flattened_record_dicts(BOTH_MEMBERS), column_names(ExampleSquadMember), csv_path)
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        parsed_rows = list(csv.DictReader(csv_file))
    assert parsed_rows[0] == {
        "uid": "2001",
        "traits": "tries_long_shots;unknown",
        "traits_code": "12;40",
        "home_grown_club_names": "Northbridge FC;;Example Rovers",
        "chain_club_uids": "31;;33",
        "on_loan": "true",
    }
    assert parsed_rows[1]["traits"] == ""
    assert parsed_rows[1]["traits_code"] == ""


def test_optional_item_and_coded_value_tuples_in_json(tmp_path: Path) -> None:
    nested_rows = [record_to_dict(member, json_ready=True) for member in BOTH_MEMBERS]
    json_path = tmp_path / "members.json"
    write_json(nested_rows, json_path)
    loaded_rows = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded_rows[0]["home_grown_club_names"] == ["Northbridge FC", None, "Example Rovers"]
    assert loaded_rows[0]["traits"] == ["tries_long_shots", "unknown"]
    assert loaded_rows[0]["traits_code"] == [12, 40]
    assert loaded_rows[1]["traits_code"] == []
    stream = io.StringIO()
    write_jsonl(nested_rows, stream)
    assert '"home_grown_club_names":["Northbridge FC",null,"Example Rovers"]' in stream.getvalue()


def test_optional_item_and_coded_value_tuples_match_json_normalize() -> None:
    assert_matches_json_normalize(BOTH_MEMBERS, ExampleSquadMember)


def test_optional_item_and_coded_value_tuples_build_a_polars_frame() -> None:
    frame = to_polars(to_columns(BOTH_MEMBERS, ExampleSquadMember))
    assert frame.shape == (2, 6)


def test_none_item_in_a_coded_value_tuple_raises_type_error() -> None:
    member = replace(MEMBER_WITH_TRAITS, traits=(None,))
    with pytest.raises(TypeError, match=r"ExampleSquadMember\.traits"):
        record_to_dict(member, json_ready=True)
    with pytest.raises(TypeError, match=r"ExampleSquadMember\.traits"):
        to_columns([member], ExampleSquadMember)


def test_group_of_the_wrong_class_raises_type_error() -> None:
    holder = replace(ExampleContractHolder(uid=6, ability=None), ability=ExampleClause(None, None))
    with pytest.raises(TypeError, match=r"ExampleContractHolder\.ability"):
        record_to_dict(holder, json_ready=False)
    with pytest.raises(TypeError, match=r"ExampleContractHolder\.ability"):
        to_columns([holder], ExampleContractHolder)


def test_none_item_in_a_record_tuple_raises_type_error() -> None:
    record = replace(FULL_RECORD, clauses=(None,))
    with pytest.raises(TypeError, match=r"ExampleRecord\.clauses"):
        record_to_dict(record, json_ready=True)
    with pytest.raises(TypeError, match=r"ExampleRecord\.clauses"):
        to_columns([record], ExampleRecord)


def test_frozen_mapping_unknown_values_are_read() -> None:
    record = replace(FULL_RECORD, unknown=FrozenMapping({"e8": 3, "money_a": 7}))
    flat_row = flatten_dict(record_to_dict(record, json_ready=True))
    assert flat_row["unknown_money_a"] == 7
    assert flat_row["unknown_e8"] == 3
    columns = to_columns([record], ExampleRecord)
    assert columns["unknown_money_a"] == [7]
    assert columns["unknown_e8"] == [3]


def test_a_mapping_that_is_not_the_unknown_field_is_one_column() -> None:
    """Its keys come from the save, so they cannot be column names and the mapping stays whole."""
    record = ExampleSectionList("first", FrozenMapping({"alpha": 3, "beta": 4}))
    assert column_names(ExampleSectionList) == ("name", "section_schemas")
    for json_ready in (False, True):
        flat_row = flatten_dict(record_to_dict(record, json_ready=json_ready))
        assert set(flat_row) == set(column_names(ExampleSectionList))
        assert flat_row["section_schemas"] == {"alpha": 3, "beta": 4}
    assert to_columns([record], ExampleSectionList)["section_schemas"] == [{"alpha": 3, "beta": 4}]


def test_a_mapping_column_counts_as_present_even_when_it_holds_nothing() -> None:
    records = [
        ExampleSectionList("first", FrozenMapping({"alpha": 3})),
        ExampleSectionList("second", FrozenMapping({})),
    ]
    assert Table(records, ExampleSectionList).coverage == {"name": 1.0, "section_schemas": 1.0}


def test_a_mapping_column_reaches_both_frame_builders() -> None:
    records = [ExampleSectionList("first", FrozenMapping({"alpha": 3}))]
    columns = to_columns(records, ExampleSectionList)
    assert to_pandas(columns)["section_schemas"].tolist() == [{"alpha": 3}]
    # polars reads a struct column from dicts and from no other mapping.
    assert to_polars(columns)["section_schemas"].to_list() == [{"alpha": 3}]


def test_a_mapping_column_is_written_as_json(tmp_path: Path) -> None:
    records = [
        ExampleSectionList("first", FrozenMapping({"alpha": 3})),
        ExampleSectionList("second", FrozenMapping({})),
    ]
    csv_stream = io.StringIO(newline="")
    write_csv(flat_rows(records, ExampleSectionList), column_names(ExampleSectionList), csv_stream)
    assert csv_stream.getvalue().splitlines() == [
        "name,section_schemas",
        'first,"{""alpha"":3}"',
        "second,{}",
    ]
    # The writer that reads the records straight writes the same text.
    csv_path = tmp_path / "sections.csv"
    Table(records, ExampleSectionList).write_csv(csv_path)
    assert csv_path.read_bytes() == csv_stream.getvalue().encode("utf-8")
    json_stream = io.StringIO()
    write_json([record_to_dict(records[0], json_ready=True)], json_stream)
    assert json.loads(json_stream.getvalue())[0]["section_schemas"] == {"alpha": 3}


def test_a_mapping_column_that_is_not_a_mapping_raises_type_error() -> None:
    record = ExampleSectionList("first", cast("Mapping[str, int]", "not a mapping"))
    with pytest.raises(TypeError, match="ExampleSectionList.section_schemas is not a mapping"):
        record_to_dict(record, json_ready=False)


def test_unknown_field_without_unknown_keys_raises_type_error() -> None:
    with pytest.raises(TypeError, match="UNKNOWN_KEYS"):
        column_names(ExampleWithoutUnknownKeys)
    with pytest.raises(TypeError, match="UNKNOWN_KEYS"):
        record_to_dict(ExampleWithoutUnknownKeys(uid=1, unknown={}), json_ready=False)


def test_to_columns_rejects_records_of_another_type() -> None:
    with pytest.raises(TypeError, match="ExampleContractHolder"):
        to_columns([FULL_RECORD], ExampleContractHolder)


def test_to_columns_matches_flattened_record_dicts() -> None:
    record_sets: list[tuple[type, Sequence[object]]] = [
        (ExampleRecord, BOTH_RECORDS),
        (ExampleSquadMember, BOTH_MEMBERS),
        (
            ExampleContractHolder,
            (ExampleContractHolder(7, None), ExampleContractHolder(8, ExampleGroup(1, None))),
        ),
    ]
    for record_type, records in record_sets:
        expected_rows = flattened_record_dicts(records)
        columns = to_columns(records, record_type)
        for column_name, column_values in columns.items():
            assert column_values == [expected_row[column_name] for expected_row in expected_rows]


@dataclass(frozen=True, slots=True)
class ExampleSpell:
    start: date | None
    end: date | None


@dataclass(frozen=True, slots=True)
class ExampleLoanHolder:
    uid: int
    loan: ExampleSpell | None
    spells: tuple[ExampleSpell, ...]
    match_dates: tuple[date, ...] | None


LOAN_HOLDERS = (
    ExampleLoanHolder(
        uid=3001,
        loan=ExampleSpell(date(2030, 7, 1), None),
        spells=(ExampleSpell(date(2029, 1, 2), date(2029, 6, 30)),),
        match_dates=(date(2030, 8, 9), date(2030, 8, 16)),
    ),
    ExampleLoanHolder(uid=3002, loan=None, spells=(), match_dates=None),
)


def test_flat_rows_match_flattened_record_dicts_for_every_shape() -> None:
    record_sets: list[tuple[type, Sequence[object]]] = [
        (ExampleRecord, BOTH_RECORDS),
        (ExampleRecord, (replace(FULL_RECORD, unknown=FrozenMapping({"e8": 3})),)),
        (ExampleSquadMember, BOTH_MEMBERS),
        (
            ExampleContractHolder,
            (ExampleContractHolder(7, None), ExampleContractHolder(8, ExampleGroup(1, None))),
        ),
        (ExampleClause, (ExampleClause(None, None), ExampleClause(FULL_RECORD.clauses[0].kind, 5))),
        (ExampleGroup, ()),
        (ExampleLoanHolder, LOAN_HOLDERS),
    ]
    for record_type, records in record_sets:
        for json_ready in (False, True):
            expected_rows = [
                flatten_dict(record_to_dict(record, json_ready=json_ready)) for record in records
            ]
            actual_rows = list(flat_rows(records, record_type, json_ready=json_ready))
            assert actual_rows == expected_rows, (record_type.__name__, json_ready)
            for actual_row, expected_row in zip(actual_rows, expected_rows, strict=True):
                assert list(actual_row) == list(expected_row)
                for column_name, expected_value in expected_row.items():
                    assert type(actual_row[column_name]) is type(expected_value), column_name


def test_flat_rows_default_keeps_python_values() -> None:
    first_row = next(flat_rows(LOAN_HOLDERS, ExampleLoanHolder))
    assert first_row["loan_start"] == date(2030, 7, 1)
    assert first_row["match_dates"] == (date(2030, 8, 9), date(2030, 8, 16))
    json_row = next(flat_rows(LOAN_HOLDERS, ExampleLoanHolder, json_ready=True))
    assert json_row["loan_start"] == "2030-07-01"
    assert json_row["match_dates"] == ["2030-08-09", "2030-08-16"]


def test_flat_rows_reject_records_of_another_type() -> None:
    with pytest.raises(TypeError, match="ExampleContractHolder"):
        list(flat_rows([FULL_RECORD], ExampleContractHolder))
    with pytest.raises(TypeError, match="ExampleContractHolder"):
        list(flat_rows([FULL_RECORD], ExampleContractHolder, json_ready=True))


def test_flat_rows_checks_the_record_type_when_called() -> None:
    with pytest.raises(TypeError, match="not a record dataclass"):
        flat_rows([], int)
    with pytest.raises(TypeError, match="not a record dataclass"):
        flat_rows(iter(()), CodedValue, json_ready=True)
    unstarted_rows = flat_rows([FULL_RECORD], ExampleContractHolder)
    with pytest.raises(TypeError, match="ExampleContractHolder"):
        next(unstarted_rows)


def test_group_type_error_names_the_expected_class() -> None:
    holder = replace(ExampleContractHolder(uid=6, ability=None), ability=ExampleClause(None, None))
    with pytest.raises(TypeError, match="is not an instance of ExampleGroup or None"):
        list(flat_rows([holder], ExampleContractHolder))
