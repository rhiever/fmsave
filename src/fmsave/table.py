"""The immutable sequence of records that every reader returns."""

from __future__ import annotations

import dataclasses
import os
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, ClassVar, NoReturn, cast, overload

from fmsave import export
from fmsave._frozen import FrozenMapping

_NAME_FIELD = "name"
_UID_FIELD = "uid"


def _normalized_name(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _dataclass_field_names(candidate: object) -> tuple[str, ...] | None:
    """Return the field names of a dataclass type, or None when candidate is not one."""
    if not isinstance(candidate, type) or not dataclasses.is_dataclass(candidate):
        return None
    return tuple(record_field.name for record_field in dataclasses.fields(candidate))


class Table[RecordT](Sequence[RecordT]):
    """An immutable sequence of records of one dataclass type, with queries and export.

    Indexing with an int returns a record and slicing returns a Table of the same record type.
    Queries return new tables and never change this one. Tables compare equal when they have
    the same record type and equal records, are not hashable, and can be pickled and
    deep-copied.
    """

    __slots__ = ("_coverage", "_record_type", "_records", "_uid_index")
    __hash__: ClassVar[None] = None  # pyright: ignore[reportIncompatibleMethodOverride]

    _records: tuple[RecordT, ...]
    _record_type: type[RecordT]
    _uid_index: dict[object, RecordT] | None
    _coverage: FrozenMapping[str, float] | None

    def __init__(self, records: Iterable[RecordT], record_type: type[RecordT]) -> None:
        """Store the records as a tuple.

        Args:
            records: The records, all of record_type.
            record_type: The dataclass the records are instances of.

        Raises:
            TypeError: record_type is not a dataclass, or a record is not exactly of record_type
                (an instance of a subclass is rejected too).
        """
        if _dataclass_field_names(record_type) is None:
            raise TypeError(f"Table record_type must be a dataclass, not {record_type!r}")
        stored_records = tuple(records)
        stray_types = set(map(type, stored_records))
        stray_types.discard(record_type)
        if stray_types:
            stray_names = ", ".join(sorted(stray_type.__name__ for stray_type in stray_types))
            raise TypeError(f"Table expected {record_type.__name__} records, not {stray_names}")
        self._store(stored_records, record_type)

    def _store(self, records: tuple[RecordT, ...], record_type: type[RecordT]) -> None:
        object.__setattr__(self, "_records", records)
        object.__setattr__(self, "_record_type", record_type)
        object.__setattr__(self, "_uid_index", None)
        object.__setattr__(self, "_coverage", None)

    def _from_checked_records(self, records: tuple[RecordT, ...]) -> Table[RecordT]:
        """Build a table of this record type from records already checked by this table."""
        table = cast("Table[RecordT]", object.__new__(Table))
        table._store(records, self._record_type)
        return table

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError(f"Table is immutable: cannot set {name!r}")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError(f"Table is immutable: cannot delete {name!r}")

    def __reduce__(self) -> tuple[type[Table[RecordT]], tuple[tuple[RecordT, ...], type[RecordT]]]:
        # The uid index and coverage are rebuilt on demand, so only the records are kept.
        return (Table, (self._records, self._record_type))

    @property
    def record_type(self) -> type[RecordT]:
        """The dataclass the records are instances of."""
        return self._record_type

    @overload
    def __getitem__(self, index: int) -> RecordT: ...

    @overload
    def __getitem__(self, index: slice) -> Table[RecordT]: ...

    def __getitem__(self, index: int | slice) -> RecordT | Table[RecordT]:
        if isinstance(index, slice):
            return self._from_checked_records(self._records[index])
        return self._records[index]

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[RecordT]:
        return iter(self._records)

    def __reversed__(self) -> Iterator[RecordT]:
        return reversed(self._records)

    def index(self, value: object, start: int = 0, stop: int | None = None) -> int:
        """Return the position of the first record equal to value between start and stop.

        A stop of None means the end of the table. Negative start and stop count from the end.

        Raises:
            ValueError: No such record.
        """
        return self._records.index(value, start, len(self._records) if stop is None else stop)

    def count(self, value: object) -> int:
        """Return how many records equal value."""
        return self._records.count(value)

    def __contains__(self, value: object) -> bool:
        return value in self._records

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Table):
            return NotImplemented
        other_table = cast("Table[object]", other)
        return (
            self._record_type is other_table._record_type and self._records == other_table._records
        )

    def __repr__(self) -> str:
        return f"Table[{self._record_type.__name__}]({len(self._records)} records)"

    def _field_names(self) -> tuple[str, ...]:
        return _dataclass_field_names(self._record_type) or ()

    def _require_field(self, field_name: str, method_name: str) -> None:
        if field_name not in self._field_names():
            raise ValueError(
                f"{method_name} needs a {field_name!r} field, and "
                f"{self._record_type.__name__} has none"
            )

    def where(self, **equals: object) -> Table[RecordT]:
        """Return the records whose named top-level fields all equal the given values.

        Nested group columns such as "contract_wage" are not field names; use filter for them.
        A coded-value field equals only a whole CodedValue with the same label and raw number,
        so passing just the label matches nothing. To match on the label alone, use filter,
        for example filter(lambda record: record.status.label is Status.FIRST_CHOICE).

        Raises:
            ValueError: A name is not a field of the record type. The message lists every such
                name and the valid field names.
        """
        field_names = self._field_names()
        unknown_names = [name for name in equals if name not in field_names]
        if unknown_names:
            raise ValueError(
                f"unknown {self._record_type.__name__} fields: {', '.join(unknown_names)}; "
                f"valid fields: {', '.join(field_names)}"
            )
        wanted_values = tuple(equals.items())
        return self.filter(
            lambda record: all(
                getattr(record, field_name) == wanted_value
                for field_name, wanted_value in wanted_values
            )
        )

    def filter(self, predicate: Callable[[RecordT], bool]) -> Table[RecordT]:
        """Return the records for which predicate returns true, in order."""
        return self._from_checked_records(
            tuple(record for record in self._records if predicate(record))
        )

    def find(self, *, name: str) -> Table[RecordT]:
        """Return the records whose name equals name, ignoring case and surrounding whitespace.

        Both names are compared after NFKC normalization and casefolding, so "NORTHBRIDGE FC"
        finds "Northbridge FC". The whole name must match: "northbridge" does not. Records
        whose name is None never match.

        Raises:
            ValueError: The record type has no name field.
        """
        self._require_field(_NAME_FIELD, "find")
        wanted_name = _normalized_name(name)

        def has_wanted_name(record: RecordT) -> bool:
            record_name: object = getattr(record, _NAME_FIELD)
            return isinstance(record_name, str) and _normalized_name(record_name) == wanted_name

        return self.filter(has_wanted_name)

    def _uid_lookup(self) -> dict[object, RecordT]:
        uid_index = self._uid_index
        if uid_index is None:
            self._require_field(_UID_FIELD, "uid lookup")
            # Walk backwards so the first record with a repeated uid is the one kept.
            uid_index = {getattr(record, _UID_FIELD): record for record in reversed(self._records)}
            object.__setattr__(self, "_uid_index", uid_index)
        return uid_index

    def by_uid(self, uid: int) -> RecordT:
        """Return the first record with this uid.

        Raises:
            KeyError: No record has this uid.
            ValueError: The record type has no uid field.
        """
        uid_index = self._uid_lookup()
        if uid not in uid_index:
            raise KeyError(f"no record with uid {uid}")
        return uid_index[uid]

    def get_by_uid(self, uid: int) -> RecordT | None:
        """Return the first record with this uid, or None when no record has it.

        Raises:
            ValueError: The record type has no uid field.
        """
        return self._uid_lookup().get(uid)

    @property
    def coverage(self) -> Mapping[str, float]:
        """The share of records whose value is not None, for each flat column.

        Keys are export.column_names(record_type). An empty tuple counts as present, and every
        column of a missing group counts as missing. An empty table gives 0.0 for every column.
        """
        coverage = self._coverage
        if coverage is None:
            record_count = len(self._records)
            present_counts = export.present_counts(self._records, self._record_type)
            coverage = FrozenMapping(
                {
                    column_name: present_count / record_count if record_count else 0.0
                    for column_name, present_count in present_counts.items()
                }
            )
            object.__setattr__(self, "_coverage", coverage)
        return coverage

    def to_columns(self) -> dict[str, list[object]]:
        """Return flat columns of Python values; see export.to_columns."""
        return export.to_columns(self._records, self._record_type)

    def to_dicts(self, *, json_ready: bool = False) -> list[dict[str, object]]:
        """Return one nested dict per record; see export.record_to_dict."""
        return [export.record_to_dict(record, json_ready=json_ready) for record in self._records]

    def to_pandas(self) -> Any:
        """Return a pandas.DataFrame of the flat columns; see export.to_pandas.

        Raises:
            ImportError: pandas is not installed.
        """
        return export.to_pandas(self.to_columns())

    def to_polars(self) -> Any:
        """Return a polars.DataFrame of the flat columns; see export.to_polars.

        Raises:
            ImportError: polars is not installed.
        """
        return export.to_polars(self.to_columns())

    def write_csv(self, path: str | os.PathLike[str]) -> None:
        """Write every flat column as UTF-8 CSV; see export.write_records_csv."""
        export.write_records_csv(self._records, self._record_type, path)

    def write_json(self, path: str | os.PathLike[str]) -> None:
        """Write the JSON-ready nested dicts as one JSON array; see export.write_json."""
        export.write_json(self._json_rows(), path)

    def write_jsonl(self, path: str | os.PathLike[str]) -> None:
        """Write the JSON-ready nested dicts as JSON Lines; see export.write_jsonl."""
        export.write_jsonl(self._json_rows(), path)

    def _json_rows(self) -> Iterator[dict[str, object]]:
        return (export.record_to_dict(record, json_ready=True) for record in self._records)
