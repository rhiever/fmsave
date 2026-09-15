from __future__ import annotations

import copy
import csv
import json
import pickle
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from pathlib import Path

import pytest

from fmsave import CodedValue, Table, export
from fmsave._frozen import FrozenMapping


class ExampleRole(IntEnum):
    UNKNOWN = -1
    FIRST_CHOICE = 3


@dataclass(frozen=True, slots=True)
class ExampleRoleHolder:
    uid: int
    role: CodedValue[ExampleRole]


@dataclass(frozen=True, slots=True)
class ExampleClubRecord:
    uid: int
    name: str | None
    nation_id: int | None
    reputation: int | None


@dataclass(frozen=True, slots=True)
class ExampleNamelessRecord:
    reference: int


@dataclass(frozen=True, slots=True)
class ExampleFounding:
    founded_on: date | None
    city_name: str | None


@dataclass(frozen=True, slots=True)
class ExampleDetailedClub:
    uid: int
    name: str | None
    founding: ExampleFounding | None
    rival_uids: tuple[int, ...] | None


CLUB_RECORDS = (
    ExampleClubRecord(7, "Northbridge FC", 3, 5000),
    ExampleClubRecord(8, "Southport Example", 3, None),
    ExampleClubRecord(9, "northbridge fc", 4, 1200),
    ExampleClubRecord(7, "Duplicate Uid", None, 10),
)


def example_table() -> Table[ExampleClubRecord]:
    return Table(CLUB_RECORDS, ExampleClubRecord)


def uids_of(table: Table[ExampleClubRecord]) -> list[int]:
    return [club.uid for club in table]


def test_sequence_length_and_negative_index() -> None:
    table = example_table()
    assert len(table) == 4
    assert table[-1].name == "Duplicate Uid"
    assert table[0].uid == 7
    assert list(table) == list(CLUB_RECORDS)
    assert CLUB_RECORDS[1] in table


def test_slice_is_a_table_of_the_same_record_type() -> None:
    table = example_table()
    sliced_table = table[1:3]
    assert isinstance(sliced_table, Table)
    assert len(sliced_table) == 2
    assert sliced_table.record_type is ExampleClubRecord
    assert uids_of(sliced_table) == [8, 9]
    assert uids_of(table[::-2]) == [7, 8]


def test_index_out_of_range_raises_index_error() -> None:
    table = example_table()
    with pytest.raises(IndexError):
        table[10]
    with pytest.raises(IndexError):
        table[-5]


def test_stores_a_tuple_of_any_iterable() -> None:
    table = Table(iter(CLUB_RECORDS), ExampleClubRecord)
    assert len(table) == 4
    assert table == example_table()


def test_record_type_must_be_a_dataclass() -> None:
    with pytest.raises(TypeError):
        Table([1, 2], int)
    with pytest.raises(TypeError):
        Table(CLUB_RECORDS, CLUB_RECORDS[0])  # type: ignore[arg-type]


def test_records_must_be_exactly_the_record_type() -> None:
    @dataclass(frozen=True, slots=True)
    class ExampleClubSubclass(ExampleClubRecord):
        pass

    with pytest.raises(TypeError, match="ExampleClubRecord.*ExampleNamelessRecord"):
        Table([CLUB_RECORDS[0], ExampleNamelessRecord(1)], ExampleClubRecord)  # type: ignore[list-item]
    with pytest.raises(TypeError, match="ExampleClubSubclass"):
        Table([ExampleClubSubclass(1, "Northbridge FC", 3, None)], ExampleClubRecord)
    with pytest.raises(TypeError, match="ExampleClubRecord"):
        Table(iter([None]), ExampleClubRecord)  # type: ignore[list-item]
    assert len(Table([], ExampleClubRecord)) == 0


def test_slices_and_queries_keep_the_record_type() -> None:
    table = example_table()
    assert table[1:][0] == CLUB_RECORDS[1]
    assert table.where(nation_id=3).record_type is ExampleClubRecord
    assert table.filter(lambda club: club.uid == 9)[0] == CLUB_RECORDS[2]
    assert table.find(name="southport example").record_type is ExampleClubRecord


def test_index_count_and_reversed_use_the_record_tuple() -> None:
    table = example_table()
    for method_name in ("index", "count", "__reversed__"):
        assert getattr(Table, method_name) is not getattr(Sequence, method_name), method_name
    assert table.index(CLUB_RECORDS[2]) == 2
    assert table.index(CLUB_RECORDS[2], 1, 3) == 2
    assert table.index(CLUB_RECORDS[3], -1) == 3
    with pytest.raises(ValueError):
        table.index(CLUB_RECORDS[0], 1)
    with pytest.raises(ValueError):
        table.index(CLUB_RECORDS[2], 0, 2)
    assert table.count(CLUB_RECORDS[1]) == 1
    assert table.count(ExampleNamelessRecord(1)) == 0
    assert type(reversed(table)) is type(reversed(()))
    assert list(reversed(table)) == list(reversed(CLUB_RECORDS))


def test_index_accepts_a_negative_or_missing_stop() -> None:
    table = example_table()
    assert table.index(CLUB_RECORDS[2], 0, -1) == 2
    with pytest.raises(ValueError):
        table.index(CLUB_RECORDS[3], 0, -1)
    assert table.index(CLUB_RECORDS[3], 1, None) == 3
    assert table.index(CLUB_RECORDS[3], stop=None) == 3
    assert table.index(CLUB_RECORDS[3], -2, None) == 3


def test_where_docstring_explains_coded_value_matching() -> None:
    where_docstring = Table.where.__doc__ or ""
    assert "CodedValue" in where_docstring
    assert "raw" in where_docstring
    assert "filter" in where_docstring


def test_where_compares_coded_values_as_a_whole() -> None:
    first_choice = CodedValue(ExampleRole.FIRST_CHOICE, 3)
    unknown_role = CodedValue(ExampleRole.UNKNOWN, 7)
    table = Table(
        [ExampleRoleHolder(1, first_choice), ExampleRoleHolder(2, unknown_role)],
        ExampleRoleHolder,
    )
    assert [holder.uid for holder in table.where(role=first_choice)] == [1]
    assert len(table.where(role=ExampleRole.FIRST_CHOICE)) == 0
    assert len(table.where(role=CodedValue(ExampleRole.UNKNOWN, 8))) == 0
    label_matches = table.filter(lambda holder: holder.role.label is ExampleRole.UNKNOWN)
    assert [holder.uid for holder in label_matches] == [2]


def test_equality_needs_the_same_record_type_and_records() -> None:
    table = example_table()
    assert table == Table(list(CLUB_RECORDS), ExampleClubRecord)
    assert table != Table(CLUB_RECORDS[:3], ExampleClubRecord)
    assert Table([], ExampleClubRecord) != Table([], ExampleNamelessRecord)
    assert table != CLUB_RECORDS
    assert table != list(CLUB_RECORDS)


def test_where_keeps_exact_matches() -> None:
    table = example_table()
    assert uids_of(table.where(nation_id=3)) == [7, 8]
    assert uids_of(table.where(nation_id=3, reputation=None)) == [8]
    assert table.where() == table
    assert table.where(nation_id=3).record_type is ExampleClubRecord


def test_where_unknown_field_lists_unknown_and_valid_names() -> None:
    with pytest.raises(ValueError, match="colour") as error_info:
        example_table().where(colour="red")
    assert "nation_id" in str(error_info.value)
    assert "reputation" in str(error_info.value)


def test_where_accepts_only_top_level_field_names() -> None:
    detailed_table = Table([], ExampleDetailedClub)
    with pytest.raises(ValueError, match="founding_city_name"):
        detailed_table.where(founding_city_name="Example City")


def test_filter_keeps_records_the_predicate_accepts() -> None:
    table = example_table()
    assert uids_of(table.filter(lambda club: (club.reputation or 0) > 1000)) == [7, 9]


def test_find_matches_whole_names_ignoring_case_and_whitespace() -> None:
    table = example_table()
    assert uids_of(table.find(name="NORTHBRIDGE FC")) == [7, 9]
    assert len(table.find(name="northbridge")) == 0
    assert isinstance(table.find(name="northbridge"), Table)
    assert len(table.find(name=" Northbridge FC ")) == 2


def test_find_normalizes_compatibility_characters_and_skips_missing_names() -> None:
    clubs = Table(
        [
            ExampleClubRecord(20, "Ｅｘａｍｐｌｅ Rovers", None, None),
            ExampleClubRecord(21, None, None, None),
            ExampleClubRecord(22, "  STRASSE united\t", None, None),
        ],
        ExampleClubRecord,
    )
    assert uids_of(clubs.find(name="example rovers")) == [20]
    assert uids_of(clubs.find(name="Straße United")) == [22]


def test_find_without_a_name_field_raises_value_error() -> None:
    with pytest.raises(ValueError, match="name"):
        Table([ExampleNamelessRecord(1)], ExampleNamelessRecord).find(name="Northbridge FC")


def test_by_uid_returns_the_first_occurrence() -> None:
    table = example_table()
    assert table.by_uid(7).name == "Northbridge FC"
    assert table.by_uid(9).name == "northbridge fc"
    assert table.get_by_uid(8) == CLUB_RECORDS[1]


def test_missing_uid_raises_key_error_or_returns_none() -> None:
    table = example_table()
    with pytest.raises(KeyError, match="no record with uid 99"):
        table.by_uid(99)
    assert table.get_by_uid(99) is None


def test_uid_lookup_without_a_uid_field_raises_value_error() -> None:
    nameless_table = Table([ExampleNamelessRecord(1)], ExampleNamelessRecord)
    with pytest.raises(ValueError, match="uid"):
        nameless_table.by_uid(1)
    with pytest.raises(ValueError, match="uid"):
        nameless_table.get_by_uid(1)


def test_coverage_is_the_share_of_present_flat_values() -> None:
    table = example_table()
    assert table.coverage == {"uid": 1.0, "name": 1.0, "nation_id": 0.75, "reputation": 0.75}
    assert isinstance(table.coverage, FrozenMapping)
    assert Table([], ExampleClubRecord).coverage["name"] == 0.0


def test_coverage_counts_empty_tuples_as_present_and_missing_groups_as_missing() -> None:
    detailed_table = Table(
        [
            ExampleDetailedClub(1, "Northbridge FC", ExampleFounding(date(1901, 5, 4), None), ()),
            ExampleDetailedClub(2, "Southport Example", None, None),
        ],
        ExampleDetailedClub,
    )
    assert detailed_table.coverage == {
        "uid": 1.0,
        "name": 1.0,
        "founding_founded_on": 0.5,
        "founding_city_name": 0.0,
        "rival_uids": 0.5,
    }
    assert list(Table([], ExampleDetailedClub).coverage.values()) == [0.0] * 5


def test_coverage_is_read_only() -> None:
    coverage = example_table().coverage
    with pytest.raises(TypeError):
        coverage["uid"] = 0.0  # type: ignore[index]


def test_table_is_immutable_and_unhashable() -> None:
    table = example_table()
    with pytest.raises(AttributeError):
        table.record_type = ExampleNamelessRecord  # type: ignore[misc]
    with pytest.raises(AttributeError):
        table.colour = "red"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        table._records = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        del table._records
    with pytest.raises(TypeError):
        hash(table)
    assert not hasattr(table, "__dict__")
    assert table == example_table()


def test_repr_shows_the_record_type_and_count_only() -> None:
    table = example_table()
    assert repr(table) == "Table[ExampleClubRecord](4 records)"
    assert "Northbridge" not in repr(table)
    assert repr(Table([], ExampleClubRecord)) == "Table[ExampleClubRecord](0 records)"


def test_subscripted_class_builds_a_table() -> None:
    table = Table[ExampleClubRecord](CLUB_RECORDS, ExampleClubRecord)
    assert table == example_table()


def test_pickle_and_copies_round_trip_equal() -> None:
    table = example_table()
    assert table.by_uid(7).name == "Northbridge FC"
    assert table.coverage["name"] == 1.0
    copied_tables = [
        pickle.loads(pickle.dumps(table, protocol=protocol)) for protocol in range(2, 6)
    ]
    copied_tables.extend((copy.deepcopy(table), copy.copy(table)))
    for copied_table in copied_tables:
        assert type(copied_table) is Table
        assert copied_table == table
        assert copied_table.record_type is ExampleClubRecord
        assert copied_table.by_uid(7).name == "Northbridge FC"
        assert copied_table.get_by_uid(99) is None
        assert copied_table.coverage == table.coverage


def test_pickle_before_the_uid_index_is_built() -> None:
    table = example_table()
    copied_table = pickle.loads(pickle.dumps(table))
    assert copied_table.by_uid(9).name == "northbridge fc"
    assert table.by_uid(8).name == "Southport Example"


def test_to_dicts_delegates_to_export() -> None:
    table = example_table()
    assert table.to_dicts(json_ready=True) == [
        export.record_to_dict(record, json_ready=True) for record in table
    ]
    assert table.to_dicts() == [export.record_to_dict(record, json_ready=False) for record in table]


def test_to_columns_delegates_to_export() -> None:
    table = example_table()
    assert table.to_columns() == export.to_columns(CLUB_RECORDS, ExampleClubRecord)


def test_write_csv_writes_every_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "clubs.csv"
    example_table().write_csv(csv_path)
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        parsed_rows = list(reader)
        assert reader.fieldnames == list(export.column_names(ExampleClubRecord))
    assert len(parsed_rows) == 4
    assert parsed_rows[0]["name"] == "Northbridge FC"
    assert parsed_rows[1]["reputation"] == ""


def test_write_json_and_jsonl_write_json_ready_nested_rows(tmp_path: Path) -> None:
    detailed_table = Table(
        [ExampleDetailedClub(1, "Northbridge FC", ExampleFounding(date(1901, 5, 4), None), (2,))],
        ExampleDetailedClub,
    )
    expected_rows = detailed_table.to_dicts(json_ready=True)
    json_path = tmp_path / "clubs.json"
    jsonl_path = tmp_path / "clubs.jsonl"
    detailed_table.write_json(json_path)
    detailed_table.write_jsonl(jsonl_path)
    assert json.loads(json_path.read_text(encoding="utf-8")) == expected_rows
    jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(jsonl_line) for jsonl_line in jsonl_lines] == expected_rows
    assert expected_rows[0]["founding"] == {"founded_on": "1901-05-04", "city_name": None}


def test_to_pandas_and_to_polars_build_frames_of_every_column() -> None:
    table = example_table()
    pandas_frame = table.to_pandas()
    assert list(pandas_frame.columns) == ["uid", "name", "nation_id", "reputation"]
    assert pandas_frame["reputation"].dtype == "Int64"
    polars_frame = table.to_polars()
    assert polars_frame.shape == (4, 4)
