"""Flatten records into columns and write them as CSV, JSON, JSON Lines or DataFrames.

A record becomes a nested dict with record_to_dict and a flat row with flatten_dict. Nested
groups flatten to "<field>_<subfield>" columns, the same names pandas.json_normalize(sep="_")
gives for record_to_dict(record, json_ready=True). A coded value, or a tuple of coded values,
becomes a label column plus a "<field>_code" column. Tuples stay single values: JSON arrays in
JSON, ";"-joined text in CSV, or compact JSON text in CSV when their items are groups.
"""

from __future__ import annotations

import csv
import dataclasses
import functools
import importlib
import json
import operator
import os
import types
import typing
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from enum import StrEnum
from typing import Any, Literal, TextIO, TypeGuard, cast

from fmsave.models.common import CodedValue

type _FieldKind = Literal[
    "value", "date", "text_enum", "coded", "group", "values", "coded_values", "records", "unknown"
]
type _ScalarKind = Literal["value", "date", "text_enum"]
type _Step = _FieldRun | _FieldPlan

_UNKNOWN_FIELD_NAME = "unknown"
_CODE_SUFFIX = "_code"
_CSV_ITEM_SEPARATOR = ";"
_MISSING_PAIR: tuple[None, None] = (None, None)


def _read_no_fields(record: object) -> tuple[object, ...]:
    return ()


@dataclasses.dataclass(frozen=True, slots=True)
class _FieldRun:
    """Consecutive fields whose values are copied as they are.

    Attributes:
        values: The slice of the record's field values that the run covers.
        names: The field names of the run, in order.
    """

    values: slice
    names: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class _ClassPlan:
    """How the fields of one record class turn into dict keys and flat columns.

    Attributes:
        record_type: The record class.
        fields: One plan per dataclass field, in declaration order.
        columns: The flat column names, in order.
        read_fields: Returns every field value of a record as a tuple, in declaration order.
        steps: Runs of plain and date fields, and the plans of every other field, in
            declaration order. Used for flat values and for dicts that are not JSON-ready.
        json_steps: The same, but runs hold plain fields only. Used for JSON-ready dicts.
        all_plain: Whether steps is at most one run, so the field values are the flat values.
        json_all_plain: The same for json_steps, so the field values are the JSON-ready flat
            values.
        missing_columns: One None per column, for a missing group.
    """

    record_type: type
    fields: tuple[_FieldPlan, ...]
    columns: tuple[str, ...]
    read_fields: Callable[[object], tuple[object, ...]]
    steps: tuple[_Step, ...]
    json_steps: tuple[_Step, ...]
    all_plain: bool
    json_all_plain: bool
    missing_columns: tuple[None, ...]


_NO_MEMBERS = _ClassPlan(object, (), (), _read_no_fields, (), (), True, True, ())


@dataclasses.dataclass(frozen=True, slots=True)
class _FieldPlan:
    """How one dataclass field turns into dict keys."""

    name: str
    kind: _FieldKind
    index: int
    qualified_name: str
    code_name: str = ""
    item_kind: _ScalarKind = "value"
    members: _ClassPlan = _NO_MEMBERS
    unknown_keys: tuple[str, ...] = ()
    unknown_key_set: frozenset[str] = frozenset()


def _is_record_class(candidate: object) -> TypeGuard[type]:
    return (
        isinstance(candidate, type)
        and dataclasses.is_dataclass(candidate)
        and candidate is not CodedValue
    )


def _is_coded_value_type(annotation: object) -> bool:
    return annotation is CodedValue or typing.get_origin(annotation) is CodedValue


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


def _plan_field(record_type: type, index: int, field_name: str, annotation: object) -> _FieldPlan:
    qualified_name = f"{record_type.__name__}.{field_name}"
    code_name = f"{field_name}{_CODE_SUFFIX}"
    field_type = _without_none(annotation)
    scalar_kind = _scalar_kind(field_type)
    if scalar_kind is not None:
        return _FieldPlan(field_name, scalar_kind, index, qualified_name)
    if _is_coded_value_type(field_type):
        return _FieldPlan(field_name, "coded", index, qualified_name, code_name=code_name)
    if _is_record_class(field_type):
        return _FieldPlan(
            field_name, "group", index, qualified_name, members=_class_plan(field_type)
        )
    origin = typing.get_origin(field_type)
    if origin is tuple:
        type_arguments = typing.get_args(field_type)
        if len(type_arguments) == 2 and type_arguments[1] is Ellipsis:
            item_type: object = type_arguments[0]
            item_kind = _scalar_kind(_without_none(item_type))
            if item_kind is not None:
                return _FieldPlan(field_name, "values", index, qualified_name, item_kind=item_kind)
            if _is_coded_value_type(item_type):
                return _FieldPlan(
                    field_name, "coded_values", index, qualified_name, code_name=code_name
                )
            if _is_record_class(item_type):
                return _FieldPlan(
                    field_name, "records", index, qualified_name, members=_class_plan(item_type)
                )
    if (
        origin is Mapping
        and field_name == _UNKNOWN_FIELD_NAME
        and typing.get_args(field_type) == (str, int)
    ):
        unknown_keys = _unknown_keys(record_type)
        return _FieldPlan(
            field_name,
            "unknown",
            index,
            qualified_name,
            unknown_keys=unknown_keys,
            unknown_key_set=frozenset(unknown_keys),
        )
    raise TypeError(f"{qualified_name} has a type that export does not support: {annotation!r}")


def _nested_keys(field_plans: tuple[_FieldPlan, ...]) -> list[str]:
    keys: list[str] = []
    for field_plan in field_plans:
        keys.append(field_plan.name)
        if field_plan.code_name and field_plan.kind in ("coded", "coded_values"):
            keys.append(field_plan.code_name)
    return keys


def _flat_columns(field_plans: tuple[_FieldPlan, ...]) -> list[str]:
    columns: list[str] = []
    for field_plan in field_plans:
        match field_plan.kind:
            case "coded" | "coded_values":
                columns.extend((field_plan.name, field_plan.code_name))
            case "group":
                columns.extend(
                    f"{field_plan.name}_{member_column}"
                    for member_column in field_plan.members.columns
                )
            case "unknown":
                columns.extend(f"{field_plan.name}_{key}" for key in field_plan.unknown_keys)
            case "value" | "date" | "text_enum" | "values" | "records":
                columns.append(field_plan.name)
    return columns


_FLAT_RUN_KINDS: frozenset[_FieldKind] = frozenset(("value", "date"))
_JSON_RUN_KINDS: frozenset[_FieldKind] = frozenset(("value",))


def _steps(
    field_plans: tuple[_FieldPlan, ...], run_kinds: frozenset[_FieldKind]
) -> tuple[_Step, ...]:
    """Merge each stretch of consecutive fields whose kind is in run_kinds into one run."""
    steps: list[_Step] = []
    run_plans: list[_FieldPlan] = []
    for field_plan in (*field_plans, None):
        if field_plan is not None and field_plan.kind in run_kinds:
            run_plans.append(field_plan)
            continue
        if run_plans:
            run_values = slice(run_plans[0].index, run_plans[-1].index + 1)
            steps.append(_FieldRun(run_values, tuple(run_plan.name for run_plan in run_plans)))
            run_plans = []
        if field_plan is not None:
            steps.append(field_plan)
    return tuple(steps)


def _field_reader(field_names: tuple[str, ...]) -> Callable[[object], tuple[object, ...]]:
    if not field_names:
        return _read_no_fields
    if len(field_names) == 1:
        only_field_name = field_names[0]
        return lambda record: (getattr(record, only_field_name),)
    return operator.attrgetter(*field_names)


def _first_duplicate(names: Iterable[str]) -> str | None:
    seen_names: set[str] = set()
    for name in names:
        if name in seen_names:
            return name
        seen_names.add(name)
    return None


@functools.cache
def _class_plan(record_type: type) -> _ClassPlan:
    type_name = record_type.__name__
    if not dataclasses.is_dataclass(record_type) or record_type is CodedValue:
        raise TypeError(f"{type_name} is not a record dataclass")
    type_parameters: dict[str, object] = {
        type_parameter.__name__: type_parameter
        for type_parameter in getattr(record_type, "__type_params__", ())
    }
    field_types = typing.get_type_hints(record_type, localns=type_parameters)
    record_fields = dataclasses.fields(record_type)
    field_plans = tuple(
        _plan_field(record_type, index, record_field.name, field_types[record_field.name])
        for index, record_field in enumerate(record_fields)
    )
    columns = tuple(_flat_columns(field_plans))
    for names, name_role in ((_nested_keys(field_plans), "key"), (columns, "column")):
        duplicate_name = _first_duplicate(names)
        if duplicate_name is not None:
            raise ValueError(f"{type_name} has more than one {name_role} named {duplicate_name!r}")
    steps = _steps(field_plans, _FLAT_RUN_KINDS)
    json_steps = _steps(field_plans, _JSON_RUN_KINDS)
    return _ClassPlan(
        record_type=record_type,
        fields=field_plans,
        columns=columns,
        read_fields=_field_reader(tuple(record_field.name for record_field in record_fields)),
        steps=steps,
        json_steps=json_steps,
        all_plain=_is_one_run(steps),
        json_all_plain=_is_one_run(json_steps),
        missing_columns=(None,) * len(columns),
    )


def _is_one_run(steps: tuple[_Step, ...]) -> bool:
    return len(steps) == 0 or (len(steps) == 1 and isinstance(steps[0], _FieldRun))


def column_names(record_type: type) -> tuple[str, ...]:
    """Return the flat column names of a record type, in field declaration order.

    The names come from the type hints alone, are computed once per type, and equal the keys of
    flatten_dict(record_to_dict(record, ...)) for every record of the type.

    Raises:
        TypeError: record_type is not a record dataclass, a field has a type that export does
            not support, or an unknown field has no UNKNOWN_KEYS.
        ValueError: Two fields give the same dict key or flat column name.
    """
    return _class_plan(record_type).columns


def _sequence_items(field_plan: _FieldPlan, value: object) -> Sequence[object]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_plan.qualified_name} is not a tuple or None")
    return cast("Sequence[object]", value)


def _coded_pair(field_plan: _FieldPlan, value: object) -> tuple[object, object]:
    if value is None:
        return _MISSING_PAIR
    if not isinstance(value, CodedValue):
        raise TypeError(f"{field_plan.qualified_name} is not a CodedValue or None")
    coded_value = cast("CodedValue[Any]", value)
    return coded_value.label_text, coded_value.raw


def _scalar_items(field_plan: _FieldPlan, value: object, *, json_ready: bool) -> object:
    if value is None:
        return None
    items = _sequence_items(field_plan, value)
    if field_plan.item_kind == "text_enum":
        items = [item.value if isinstance(item, StrEnum) else item for item in items]
    elif field_plan.item_kind == "date" and json_ready:
        items = [item.isoformat() if isinstance(item, date) else item for item in items]
    return list(items) if json_ready else tuple(items)


def _coded_items(
    field_plan: _FieldPlan, value: object, *, json_ready: bool
) -> tuple[object, object]:
    if value is None:
        return _MISSING_PAIR
    labels: list[str] = []
    codes: list[int] = []
    for item in _sequence_items(field_plan, value):
        if not isinstance(item, CodedValue):
            raise TypeError(f"{field_plan.qualified_name} holds an item that is not a CodedValue")
        coded_item = cast("CodedValue[Any]", item)
        labels.append(coded_item.label_text)
        codes.append(coded_item.raw)
    if json_ready:
        return labels, codes
    return tuple(labels), tuple(codes)


def _record_items(field_plan: _FieldPlan, value: object, *, json_ready: bool) -> object:
    if value is None:
        return None
    members = field_plan.members
    nested_items: list[object] = []
    for item in _sequence_items(field_plan, value):
        if not isinstance(item, members.record_type):
            raise TypeError(
                f"{field_plan.qualified_name} holds an item that is not an instance of "
                f"{members.record_type.__name__}"
            )
        nested_items.append(_nested_record(item, members, json_ready=json_ready))
    return nested_items if json_ready else tuple(nested_items)


def _unknown_values(field_plan: _FieldPlan, value: object) -> list[object]:
    if value is None:
        return [None] * len(field_plan.unknown_keys)
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_plan.qualified_name} is not a mapping")
    unknown_mapping = cast("Mapping[object, object]", value)
    undeclared_keys = [key for key in unknown_mapping if key not in field_plan.unknown_key_set]
    if undeclared_keys:
        raise ValueError(
            f"{field_plan.qualified_name} has keys missing from UNKNOWN_KEYS: "
            + ", ".join(repr(key) for key in undeclared_keys)
        )
    return [unknown_mapping.get(key) for key in field_plan.unknown_keys]


def _group_type_error(field_plan: _FieldPlan) -> TypeError:
    return TypeError(
        f"{field_plan.qualified_name} is not an instance of "
        f"{field_plan.members.record_type.__name__} or None"
    )


def _missing_nested(class_plan: _ClassPlan) -> dict[str, object]:
    """Build the nested dict of a missing group: every key present, every value None."""
    nested: dict[str, object] = {}
    for field_plan in class_plan.fields:
        match field_plan.kind:
            case "group":
                nested[field_plan.name] = _missing_nested(field_plan.members)
            case "unknown":
                nested[field_plan.name] = dict.fromkeys(field_plan.unknown_keys)
            case "coded" | "coded_values":
                nested[field_plan.name] = None
                nested[field_plan.code_name] = None
            case "value" | "date" | "text_enum" | "values" | "records":
                nested[field_plan.name] = None
    return nested


def _nested_record(
    record: object, class_plan: _ClassPlan, *, json_ready: bool
) -> dict[str, object]:
    field_values = class_plan.read_fields(record)
    nested: dict[str, object] = {}
    for step in class_plan.json_steps if json_ready else class_plan.steps:
        if isinstance(step, _FieldRun):
            nested.update(zip(step.names, field_values[step.values]))
            continue
        field_name = step.name
        value = field_values[step.index]
        match step.kind:
            case "value":
                nested[field_name] = value
            case "date":
                nested[field_name] = (
                    value.isoformat() if json_ready and isinstance(value, date) else value
                )
            case "text_enum":
                nested[field_name] = value.value if isinstance(value, StrEnum) else value
            case "coded":
                nested[field_name], nested[step.code_name] = _coded_pair(step, value)
            case "group":
                members = step.members
                if value is None:
                    nested[field_name] = _missing_nested(members)
                elif isinstance(value, members.record_type):
                    nested[field_name] = _nested_record(value, members, json_ready=json_ready)
                else:
                    raise _group_type_error(step)
            case "values":
                nested[field_name] = _scalar_items(step, value, json_ready=json_ready)
            case "coded_values":
                nested[field_name], nested[step.code_name] = _coded_items(
                    step, value, json_ready=json_ready
                )
            case "records":
                nested[field_name] = _record_items(step, value, json_ready=json_ready)
            case "unknown":
                nested[field_name] = dict(zip(step.unknown_keys, _unknown_values(step, value)))
    return nested


def _append_flat_values(
    flat_values: list[object], record: object, class_plan: _ClassPlan, *, json_ready: bool
) -> None:
    """Append a record's flat column values, in column order, without building nested dicts."""
    field_values = class_plan.read_fields(record)
    for step in class_plan.json_steps if json_ready else class_plan.steps:
        if isinstance(step, _FieldRun):
            flat_values.extend(field_values[step.values])
            continue
        value = field_values[step.index]
        match step.kind:
            case "group":
                members = step.members
                if value is None:
                    flat_values.extend(members.missing_columns)
                elif not isinstance(value, members.record_type):
                    raise _group_type_error(step)
                elif members.json_all_plain if json_ready else members.all_plain:
                    flat_values.extend(members.read_fields(value))
                else:
                    _append_flat_values(flat_values, value, members, json_ready=json_ready)
            case "coded":
                flat_values.extend(_coded_pair(step, value))
            case "text_enum":
                flat_values.append(value.value if isinstance(value, StrEnum) else value)
            case "values":
                flat_values.append(_scalar_items(step, value, json_ready=json_ready))
            case "coded_values":
                flat_values.extend(_coded_items(step, value, json_ready=json_ready))
            case "records":
                flat_values.append(_record_items(step, value, json_ready=json_ready))
            case "unknown":
                flat_values.extend(_unknown_values(step, value))
            case "date":
                flat_values.append(
                    value.isoformat() if json_ready and isinstance(value, date) else value
                )
            case "value":
                flat_values.append(value)


def record_to_dict(record: object, *, json_ready: bool) -> dict[str, object]:
    """Turn a record into a nested dict of its fields, in declaration order.

    A group field becomes a nested dict, and a missing group a nested dict of None values. A
    coded value "x" becomes the keys "x" (its label text) and "x_code" (its raw number); a tuple
    of coded values becomes the same two keys holding the label texts and the raw numbers in
    order. A StrEnum becomes its value string. The unknown field becomes a dict with exactly
    the record type's UNKNOWN_KEYS, None where a key is absent. Tuples of plain values keep
    their None items.

    Args:
        record: A record dataclass instance.
        json_ready: When true, dates become ISO 8601 strings and tuples become lists.

    Raises:
        TypeError: The record's type is not supported (see column_names), or a value does not
            match its field's type: for example a group of another class, or a None item in a
            tuple of records or coded values.
        ValueError: Two fields of the type give the same key or column name, or the unknown
            mapping holds a key its type does not declare in UNKNOWN_KEYS.
    """
    return _nested_record(record, _class_plan(type(record)), json_ready=json_ready)


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
        TypeError: A record is not exactly of record_type, record_type is not supported, or a
            value does not match its field's type.
        ValueError: Two fields give the same column name, or a record's unknown mapping holds
            an undeclared key.
    """
    class_plan = _class_plan(record_type)
    columns: dict[str, list[object]] = {name: [] for name in class_plan.columns}
    column_appenders = [column_values.append for column_values in columns.values()]
    flat_values: list[object] = []
    for record in records:
        if type(record) is not record_type:
            raise _record_type_error("to_columns", record_type, record)
        flat_values.clear()
        _append_flat_values(flat_values, record, class_plan, json_ready=False)
        for append_value, value in zip(column_appenders, flat_values, strict=True):
            append_value(value)
    return columns


def flat_rows[RecordT](
    records: Iterable[RecordT], record_type: type[RecordT], *, json_ready: bool = False
) -> Iterator[dict[str, object]]:
    """Yield each record as a flat row keyed by column_names(record_type), one at a time.

    Each row equals flatten_dict(record_to_dict(record, json_ready=json_ready)), but is built
    in one pass without nested dicts.

    Args:
        records: Records that are all exactly of record_type.
        record_type: The record class.
        json_ready: When true, dates become ISO 8601 strings and tuples become lists.

    Raises:
        TypeError: A record is not exactly of record_type, record_type is not supported, or a
            value does not match its field's type.
        ValueError: Two fields give the same column name, or a record's unknown mapping holds
            an undeclared key.

    An unsupported record_type raises when flat_rows is called; problems with the records
    themselves raise while the rows are iterated.
    """
    class_plan = _class_plan(record_type)
    return _flat_row_values(records, record_type, class_plan, json_ready=json_ready)


def _flat_row_values(
    records: Iterable[object], record_type: type, class_plan: _ClassPlan, *, json_ready: bool
) -> Iterator[dict[str, object]]:
    columns = class_plan.columns
    for record in records:
        if type(record) is not record_type:
            raise _record_type_error("flat_rows", record_type, record)
        flat_values: list[object] = []
        _append_flat_values(flat_values, record, class_plan, json_ready=json_ready)
        yield dict(zip(columns, flat_values, strict=True))


def _record_type_error(function_name: str, record_type: type, record: object) -> TypeError:
    return TypeError(
        f"{function_name} expected {record_type.__name__} records, not {type(record).__name__}"
    )


def _json_default(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _csv_cell(value: object) -> str:
    if type(value) is str:
        return value
    if type(value) is int:
        return str(value)
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


def _cell_reader(column_list: list[str]) -> Callable[[Mapping[str, object]], tuple[object, ...]]:
    if not column_list:
        return lambda flat_row: ()
    if len(column_list) == 1:
        only_column_name = column_list[0]
        return lambda flat_row: (flat_row[only_column_name],)
    return operator.itemgetter(*column_list)


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
    list of plain values is joined with ";" (a None item is an empty segment), and one holding
    dicts is compact JSON text. Rows end with "\\r\\n", as in standard CSV. A path is opened
    and closed here; a stream is written to and left open, and should have been opened with
    newline="".

    Raises:
        TypeError: columns is a single string instead of a sequence of names.
        KeyError: A row has no value for one of the columns.
    """
    if isinstance(columns, str):
        raise TypeError("columns must be a sequence of column names, not a string")
    column_list = list(columns)
    read_cells = _cell_reader(column_list)
    with _text_output(destination, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(column_list)
        for flat_row in flat_rows:
            # Strings and plain ints, the most common cells, skip the conversion call.
            writer.writerow(
                [
                    cell
                    if (cell_type := type(cell)) is str or cell_type is int
                    else _csv_cell(cell)
                    for cell in read_cells(flat_row)
                ]
            )


def write_json(
    nested_rows: Iterable[Mapping[str, object]], destination: str | os.PathLike[str] | TextIO
) -> None:
    """Write nested rows as one UTF-8 JSON array, indented by 2 spaces.

    Rows are expected from record_to_dict(record, json_ready=True). The text equals
    json.dumps(rows, ensure_ascii=False, indent=2) plus a final newline, but rows are written
    one at a time. A path destination is opened with "\\n" line endings on every OS and closed
    here. A stream destination is written to and left open, and its own newline setting
    applies.
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
    """Write nested rows as UTF-8 JSON Lines: one compact object per line.

    Rows are expected from record_to_dict(record, json_ready=True). A path destination is
    opened with "\\n" line endings on every OS and closed here. A stream destination is written
    to and left open, and its own newline setting applies.
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
