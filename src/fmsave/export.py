"""Flatten records into columns and write them as CSV, JSON, JSON Lines or DataFrames.

A record becomes a nested dict with record_to_dict and a flat row with flatten_dict. Nested
groups flatten to "<field>_<subfield>" columns, the same names pandas.json_normalize(sep="_")
gives for record_to_dict(record, json_ready=True). A coded value becomes a label column plus a
"<field>_code" column. Tuples stay single values: JSON arrays in JSON, ";"-joined text in CSV,
or compact JSON text in CSV when their items are groups.
"""

from __future__ import annotations

import csv
import dataclasses
import functools
import importlib
import json
import os
import types
import typing
from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from enum import IntEnum, StrEnum
from typing import Any, Literal, TextIO, TypeGuard, cast

from fmsave.models.common import CodedValue

type _FieldKind = Literal[
    "value", "date", "text_enum", "coded", "group", "values", "records", "unknown"
]
type _ScalarKind = Literal["value", "date", "text_enum"]

_UNKNOWN_FIELD_NAME = "unknown"
_CSV_ITEM_SEPARATOR = ";"


@dataclasses.dataclass(frozen=True, slots=True)
class _FieldPlan:
    """How one dataclass field turns into dict keys."""

    name: str
    kind: _FieldKind
    item_kind: _ScalarKind = "value"
    member_plans: tuple[_FieldPlan, ...] = ()
    unknown_keys: tuple[str, ...] = ()


def _is_record_class(candidate: object) -> TypeGuard[type]:
    return (
        isinstance(candidate, type)
        and dataclasses.is_dataclass(candidate)
        and candidate is not CodedValue
    )


def _without_none(annotation: object) -> object:
    if typing.get_origin(annotation) not in (typing.Union, types.UnionType):
        return annotation
    member_types = [
        member_type for member_type in typing.get_args(annotation) if member_type is not type(None)
    ]
    if len(member_types) != 1:
        return annotation
    return member_types[0]


def _scalar_kind(annotation: object) -> _ScalarKind | None:
    if annotation is bool or annotation is int or annotation is str:
        return "value"
    if annotation is date:
        return "date"
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return "text_enum"
    return None


def _unknown_keys(record_type: type) -> tuple[str, ...]:
    declared_keys: object = getattr(record_type, "UNKNOWN_KEYS", None)
    if isinstance(declared_keys, tuple):
        key_items = cast("tuple[object, ...]", declared_keys)
        key_names = tuple(key for key in key_items if isinstance(key, str))
        if len(key_names) == len(key_items):
            return key_names
    raise TypeError(
        f"{record_type.__name__} has an {_UNKNOWN_FIELD_NAME} field but no UNKNOWN_KEYS tuple "
        "of key names"
    )


def _plan_field(record_type: type, field_name: str, annotation: object) -> _FieldPlan:
    field_type = _without_none(annotation)
    scalar_kind = _scalar_kind(field_type)
    if scalar_kind is not None:
        return _FieldPlan(field_name, scalar_kind)
    origin = typing.get_origin(field_type)
    if field_type is CodedValue or origin is CodedValue:
        return _FieldPlan(field_name, "coded")
    if _is_record_class(field_type):
        return _FieldPlan(field_name, "group", member_plans=_field_plans(field_type))
    if origin is tuple:
        type_arguments = typing.get_args(field_type)
        if len(type_arguments) == 2 and type_arguments[1] is Ellipsis:
            item_type: object = type_arguments[0]
            item_kind = _scalar_kind(item_type)
            if item_kind is not None:
                return _FieldPlan(field_name, "values", item_kind=item_kind)
            if _is_record_class(item_type):
                return _FieldPlan(field_name, "records", member_plans=_field_plans(item_type))
    if (
        origin is Mapping
        and field_name == _UNKNOWN_FIELD_NAME
        and typing.get_args(field_type) == (str, int)
    ):
        return _FieldPlan(field_name, "unknown", unknown_keys=_unknown_keys(record_type))
    raise TypeError(
        f"{record_type.__name__}.{field_name} has a type export does not support: {annotation!r}"
    )


@functools.cache
def _field_plans(record_type: type) -> tuple[_FieldPlan, ...]:
    type_name = record_type.__name__
    if not dataclasses.is_dataclass(record_type) or record_type is CodedValue:
        raise TypeError(f"{type_name} is not a record dataclass")
    type_parameters: dict[str, object] = {
        type_parameter.__name__: type_parameter
        for type_parameter in getattr(record_type, "__type_params__", ())
    }
    field_types = typing.get_type_hints(record_type, localns=type_parameters)
    return tuple(
        _plan_field(record_type, record_field.name, field_types[record_field.name])
        for record_field in dataclasses.fields(record_type)
    )


def _plan_columns(plans: tuple[_FieldPlan, ...], prefix: str) -> list[str]:
    columns: list[str] = []
    for plan in plans:
        column_name = f"{prefix}{plan.name}"
        match plan.kind:
            case "coded":
                columns.extend((column_name, f"{column_name}_code"))
            case "group":
                columns.extend(_plan_columns(plan.member_plans, f"{column_name}_"))
            case "unknown":
                columns.extend(f"{column_name}_{key}" for key in plan.unknown_keys)
            case "value" | "date" | "text_enum" | "values" | "records":
                columns.append(column_name)
    return columns


@functools.cache
def column_names(record_type: type) -> tuple[str, ...]:
    """Return the flat column names of a record type, in field declaration order.

    The names come from the type hints alone, and equal the keys of
    flatten_dict(record_to_dict(record, ...)) for every record of the type.

    Raises:
        TypeError: record_type is not a record dataclass, a field has a type export does not
            support, an unknown field has no UNKNOWN_KEYS, or two fields flatten to the same
            column name.
    """
    names = _plan_columns(_field_plans(record_type), "")
    seen_names: set[str] = set()
    for name in names:
        if name in seen_names:
            raise TypeError(f"{record_type.__name__} has more than one column named {name!r}")
        seen_names.add(name)
    return tuple(names)


def _scalar_value(value: object, kind: _ScalarKind, *, json_ready: bool) -> object:
    if kind == "date" and json_ready and isinstance(value, date):
        return value.isoformat()
    if kind == "text_enum" and isinstance(value, StrEnum):
        return value.value
    return value


def _sequence_items(record: object, field_name: str, value: object) -> Sequence[object]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{type(record).__name__}.{field_name} is not a tuple")
    return cast("Sequence[object]", value)


def _unknown_values(
    record: object, value: object, unknown_keys: tuple[str, ...]
) -> dict[str, object]:
    if value is None:
        return {key: None for key in unknown_keys}
    if not isinstance(value, Mapping):
        raise TypeError(f"{type(record).__name__}.{_UNKNOWN_FIELD_NAME} is not a mapping")
    unknown_mapping = cast("Mapping[object, object]", value)
    undeclared_keys = [key for key in unknown_mapping if key not in unknown_keys]
    if undeclared_keys:
        raise ValueError(
            f"{type(record).__name__}.{_UNKNOWN_FIELD_NAME} has keys missing from UNKNOWN_KEYS: "
            + ", ".join(repr(key) for key in undeclared_keys)
        )
    return {key: unknown_mapping.get(key) for key in unknown_keys}


def _record_values(
    record: object, plans: tuple[_FieldPlan, ...], *, json_ready: bool
) -> dict[str, object]:
    """Build the nested dict for a record, or all-None values for a missing group."""
    values: dict[str, object] = {}
    for plan in plans:
        value: object = None if record is None else getattr(record, plan.name)
        match plan.kind:
            case "value" | "date" | "text_enum":
                values[plan.name] = _scalar_value(value, plan.kind, json_ready=json_ready)
            case "coded":
                if value is None:
                    values[plan.name] = None
                    values[f"{plan.name}_code"] = None
                elif isinstance(value, CodedValue):
                    coded_value = cast("CodedValue[IntEnum]", value)
                    values[plan.name] = coded_value.label_text
                    values[f"{plan.name}_code"] = coded_value.raw
                else:
                    raise TypeError(f"{type(record).__name__}.{plan.name} is not a CodedValue")
            case "group":
                values[plan.name] = _record_values(value, plan.member_plans, json_ready=json_ready)
            case "values" | "records":
                if value is None:
                    values[plan.name] = None
                    continue
                items = _sequence_items(record, plan.name, value)
                if plan.kind == "values":
                    converted_items = tuple(
                        _scalar_value(item, plan.item_kind, json_ready=json_ready) for item in items
                    )
                else:
                    converted_items = tuple(
                        _record_values(item, plan.member_plans, json_ready=json_ready)
                        for item in items
                    )
                values[plan.name] = list(converted_items) if json_ready else converted_items
            case "unknown":
                values[plan.name] = _unknown_values(record, value, plan.unknown_keys)
    return values


def record_to_dict(record: object, *, json_ready: bool) -> dict[str, object]:
    """Turn a record into a nested dict of its fields, in declaration order.

    A group field becomes a nested dict, and a missing group a nested dict of None values. A
    coded value "x" becomes the keys "x" (its label text) and "x_code" (its raw number). A
    StrEnum becomes its value string. The unknown field becomes a dict with exactly the
    record type's UNKNOWN_KEYS, None where a key is absent.

    Args:
        record: A record dataclass instance.
        json_ready: When true, dates become ISO 8601 strings and tuples become lists.

    Raises:
        TypeError: The record's type is not supported (see column_names), or a value does not
            match its field's type.
        ValueError: The unknown mapping holds a key its type does not declare in UNKNOWN_KEYS.
    """
    return _record_values(record, _field_plans(type(record)), json_ready=json_ready)


def _flatten_into(flat: dict[str, object], nested: Mapping[str, object], prefix: str) -> None:
    for key, value in nested.items():
        column_name = f"{prefix}{key}"
        if isinstance(value, dict):
            _flatten_into(flat, cast("dict[str, object]", value), f"{column_name}_")
        else:
            flat[column_name] = value


def flatten_dict(nested: Mapping[str, object]) -> dict[str, object]:
    """Join the keys of nested dicts with "_", the way pandas.json_normalize(sep="_") does.

    Lists and tuples are kept whole as single values, even when their items are dicts.
    """
    flat: dict[str, object] = {}
    _flatten_into(flat, nested, "")
    return flat


def select_columns(flat_row: Mapping[str, object], selected: Sequence[str]) -> dict[str, object]:
    """Return the selected columns of a flat row, in the order they were selected.

    Raises:
        ValueError: A selected name is not a column of the row. The message lists every such
            name.
    """
    unknown_names = [name for name in selected if name not in flat_row]
    if unknown_names:
        raise ValueError("unknown columns: " + ", ".join(unknown_names))
    return {name: flat_row[name] for name in selected}


def to_columns(records: Iterable[object], record_type: type) -> dict[str, list[object]]:
    """Collect records into flat columns of Python values, keyed by column_names(record_type).

    Values are not made JSON-ready: dates stay datetime.date and tuples stay tuples.

    Raises:
        TypeError: A record is not exactly of record_type, or record_type is not supported.
        ValueError: A record's unknown mapping holds an undeclared key.
    """
    names = column_names(record_type)
    columns: dict[str, list[object]] = {name: [] for name in names}
    for record in records:
        if type(record) is not record_type:
            raise TypeError(
                f"to_columns expected {record_type.__name__} records, not {type(record).__name__}"
            )
        flat_row = flatten_dict(record_to_dict(record, json_ready=False))
        for name in names:
            columns[name].append(flat_row[name])
    return columns


def _json_default(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _compact_json(cast("Mapping[object, object]", value))
    if isinstance(value, (tuple, list)):
        items = cast("Sequence[object]", value)
        if any(isinstance(item, Mapping) for item in items):
            return _compact_json(items)
        return _CSV_ITEM_SEPARATOR.join(_csv_cell(item) for item in items)
    return str(value)


@contextmanager
def _text_output(
    destination: str | os.PathLike[str] | TextIO, *, newline: str
) -> Generator[TextIO, None, None]:
    """Yield a text stream: a path is opened as UTF-8 and closed, a stream is left open."""
    if isinstance(destination, (str, os.PathLike)):
        with open(destination, "w", encoding="utf-8", newline=newline) as stream:
            yield stream
    else:
        yield destination


def write_csv(
    flat_rows: Iterable[Mapping[str, object]],
    columns: Sequence[str],
    destination: str | os.PathLike[str] | TextIO,
) -> None:
    """Write flat rows as UTF-8 CSV with a header row, keeping only the given columns.

    None is an empty cell, booleans are "true" or "false" and dates are ISO 8601. A tuple or
    list of plain values is joined with ";", and one holding dicts is compact JSON text. Rows
    end with "\\r\\n", as in standard CSV. A path is opened and closed here; a stream is written
    to and left open, and should have been opened with newline="".

    Raises:
        TypeError: columns is a single string instead of a sequence of names.
        KeyError: A row has no value for one of the columns.
    """
    if isinstance(columns, str):
        raise TypeError("columns must be a sequence of column names, not a string")
    column_list = list(columns)
    with _text_output(destination, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(column_list)
        for flat_row in flat_rows:
            writer.writerow([_csv_cell(flat_row[name]) for name in column_list])


def write_json(
    nested_rows: Iterable[Mapping[str, object]], destination: str | os.PathLike[str] | TextIO
) -> None:
    """Write nested rows as one UTF-8 JSON array, indented by 2 spaces, with "\\n" line endings.

    Rows are expected from record_to_dict(record, json_ready=True). The text equals
    json.dumps(rows, ensure_ascii=False, indent=2) plus a final newline, but rows are written
    one at a time. A path is opened and closed here; a stream is left open.
    """
    with _text_output(destination, newline="\n") as stream:
        wrote_a_row = False
        for nested_row in nested_rows:
            row_text = json.dumps(nested_row, ensure_ascii=False, indent=2, default=_json_default)
            stream.write("," if wrote_a_row else "[")
            stream.write("\n  " + row_text.replace("\n", "\n  "))
            wrote_a_row = True
        stream.write("\n]\n" if wrote_a_row else "[]\n")


def write_jsonl(
    nested_rows: Iterable[Mapping[str, object]], destination: str | os.PathLike[str] | TextIO
) -> None:
    """Write nested rows as UTF-8 JSON Lines: one compact object per line, ending in "\\n".

    Rows are expected from record_to_dict(record, json_ready=True). A path is opened and closed
    here; a stream is left open.
    """
    with _text_output(destination, newline="\n") as stream:
        for nested_row in nested_rows:
            stream.write(_compact_json(nested_row) + "\n")


def _is_nullable_integer_column(values: list[object]) -> bool:
    has_integer = False
    has_none = False
    for value in values:
        if value is None:
            has_none = True
        elif isinstance(value, int) and not isinstance(value, bool):
            has_integer = True
        else:
            return False
    return has_integer and has_none


def to_pandas(columns: Mapping[str, list[object]]) -> Any:
    """Build a pandas.DataFrame from flat columns, such as those from to_columns.

    Integer columns that also hold None use the nullable "Int64" dtype. Every other column
    uses the pandas default.

    Returns:
        A pandas.DataFrame. The return type is Any because pandas is an optional dependency.

    Raises:
        ImportError: pandas is not installed.
    """
    try:
        pandas_module = importlib.import_module("pandas")
    except ImportError as error:
        raise ImportError('to_pandas() needs pandas: pip install "fmsave[pandas]"') from error
    frame_columns: dict[str, object] = {
        name: pandas_module.array(values, dtype="Int64")
        if _is_nullable_integer_column(values)
        else values
        for name, values in columns.items()
    }
    return pandas_module.DataFrame(frame_columns)


def to_polars(columns: Mapping[str, list[object]]) -> Any:
    """Build a polars.DataFrame from flat columns, such as those from to_columns.

    Returns:
        A polars.DataFrame built with strict=False. The return type is Any because polars is an
        optional dependency.

    Raises:
        ImportError: polars is not installed.
    """
    try:
        polars_module = importlib.import_module("polars")
    except ImportError as error:
        raise ImportError('to_polars() needs polars: pip install "fmsave[polars]"') from error
    return polars_module.DataFrame(dict(columns), strict=False)
