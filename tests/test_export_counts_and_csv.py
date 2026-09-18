"""Coverage counts and CSV text built straight from records, checked against plain references.

_present_counts and Table.coverage are compared with counts taken from the columns to_columns
builds. _write_records_csv is compared with a copy of the CSV writer that converts each cell of
the flat rows from flat_rows. Two hand-written records are also checked against hard-coded
coverage and CSV text, which share no code with the writer.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import ClassVar

import pytest

import fmsave
from fmsave import Club, CodedValue, Contract, ManagedClub, Player, Suspension, Table, cli, export
from fmsave._frozen import FrozenMapping

FIXTURE_RECORD_TYPES: tuple[type, ...] = (Player, Contract, Suspension, Club, ManagedClub)
SAMPLED_SEEDS = range(40)


def reference_present_counts(records: Sequence[object], record_type: type) -> dict[str, int]:
    return {
        column_name: len(column_values) - column_values.count(None)
        for column_name, column_values in export.to_columns(records, record_type).items()
    }


def reference_coverage(records: Sequence[object], record_type: type) -> dict[str, float]:
    record_count = len(records)
    return {
        column_name: (
            (len(column_values) - column_values.count(None)) / record_count if record_count else 0.0
        )
        for column_name, column_values in export.to_columns(records, record_type).items()
    }


def reference_json_default(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def reference_compact_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=reference_json_default
    )


def reference_csv_cell(value: object) -> str:
    """One CSV cell exactly as write_csv converted a flat value before cells were planned."""
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
        return reference_compact_json(value)
    if isinstance(value, (tuple, list)):
        items: Sequence[object] = value
        if any(isinstance(item, Mapping) for item in items):
            return reference_compact_json(items)
        return ";".join(reference_csv_cell(item) for item in items)
    return str(value)


def reference_csv_text(
    records: Sequence[object], record_type: type, columns: Sequence[str] | None
) -> str:
    column_list = list(export.column_names(record_type) if columns is None else columns)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(column_list)
    for flat_row in export.flat_rows(records, record_type):
        writer.writerow([reference_csv_cell(flat_row[name]) for name in column_list])
    return stream.getvalue()


def written_csv_text(
    records: Sequence[object], record_type: type, columns: Sequence[str] | None
) -> str:
    stream = io.StringIO(newline="")
    export._write_records_csv(
        records, record_type, stream, columns=columns, operation_name="write_csv"
    )
    return stream.getvalue()


def present_counts(records: Sequence[object], record_type: type) -> dict[str, int]:
    return export._present_counts(records, record_type, operation_name="coverage")


@pytest.fixture(scope="module")
def fixture_records(career_save_path: Path) -> dict[type, tuple[object, ...]]:
    """Every table of the career fixture, plus records with absent and empty values."""
    with fmsave.open(career_save_path) as career_save:
        players = tuple(career_save.players())
        contracts = tuple(career_save.contracts())
        suspensions = tuple(career_save.suspensions())
        clubs = tuple(career_save.clubs())
        managed_clubs = tuple(career_save.managed_clubs())
    suspended_player = next(player for player in players if player.suspensions)
    assert suspended_player.contract is not None
    sparse_contract = replace(
        suspended_player.contract, squad_status=None, kind=None, clauses=(), unknown={}
    )
    return {
        Player: (
            *players,
            replace(suspended_player, contract=sparse_contract),
            replace(
                suspended_player,
                contract=None,
                personality=None,
                suspensions=(),
                traits=(),
                birth_date=None,
                on_loan=None,
            ),
        ),
        Contract: (*contracts, sparse_contract),
        Suspension: (
            *suspensions,
            replace(
                suspensions[0],
                club_uid=None,
                club_name=None,
                competition_id=None,
                competition_name=None,
                unknown={},
            ),
        ),
        Club: (*clubs, replace(clubs[0], teams=(), reputation=None, city_id=None)),
        ManagedClub: (
            *managed_clubs,
            replace(managed_clubs[0], manager_name=None, manager_staff_uid=None),
        ),
    }


@pytest.mark.parametrize("record_type", FIXTURE_RECORD_TYPES, ids=lambda kind: kind.__name__)
def test_coverage_equals_the_share_of_present_values_in_the_built_columns(
    fixture_records: dict[type, tuple[object, ...]], record_type: type
) -> None:
    records = fixture_records[record_type]
    for chosen_records in (records, records[-1:], ()):
        coverage = Table(chosen_records, record_type).coverage
        expected_coverage = reference_coverage(chosen_records, record_type)
        assert list(coverage.items()) == list(expected_coverage.items())
        assert present_counts(chosen_records, record_type) == reference_present_counts(
            chosen_records, record_type
        )
    assert any(0.0 < share < 1.0 for share in Table(records, record_type).coverage.values())


def test_the_fixture_players_cover_absent_groups_coded_values_and_unknown_keys(
    fixture_records: dict[type, tuple[object, ...]],
) -> None:
    coverage = Table(fixture_records[Player], Player).coverage
    for partly_present_column in (
        "contract_wage",
        "contract_squad_status",
        "contract_squad_status_code",
        "contract_unknown_money_a",
        "personality_ambition",
        "birth_date",
    ):
        assert 0.0 < coverage[partly_present_column] < 1.0, partly_present_column
    assert coverage["suspensions"] == 1.0
    assert coverage["traits_code"] == 1.0


@pytest.mark.parametrize("record_type", FIXTURE_RECORD_TYPES, ids=lambda kind: kind.__name__)
def test_csv_text_equals_the_reference_writer(
    fixture_records: dict[type, tuple[object, ...]], record_type: type, tmp_path: Path
) -> None:
    records = fixture_records[record_type]
    columns = list(export.column_names(record_type))
    selections: list[list[str] | None] = [
        None,
        columns[::-1],
        columns[-1:],
        [columns[-1], columns[0], columns[-1]],
    ]
    for selection in selections:
        expected_text = reference_csv_text(records, record_type, selection)
        assert written_csv_text(records, record_type, selection) == expected_text
        cli_stream = io.StringIO(newline="")
        cli._write_records(records, record_type, "csv", selection, cli_stream)
        assert cli_stream.getvalue() == expected_text
    csv_path = tmp_path / "table.csv"
    Table(records, record_type).write_csv(csv_path)
    assert csv_path.read_bytes() == reference_csv_text(records, record_type, None).encode("utf-8")


class ExampleMood(IntEnum):
    UNKNOWN = -1
    CALM = 1
    BOLD = 2


class ExampleSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class ExampleSpell:
    start: date | None
    mood: CodedValue[ExampleMood] | None


@dataclass(frozen=True, slots=True)
class ExampleProfile:
    level: int | None
    active: bool
    spell: ExampleSpell | None


@dataclass(frozen=True, slots=True)
class ExampleEntry:
    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("a", "b")

    kind: CodedValue[ExampleMood]
    note: str | None
    spell: ExampleSpell | None
    unknown: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ExampleSampledRecord:
    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("x", "y", "z")

    uid: int
    name: str | None
    on_loan: bool | None
    born: date | None
    side: ExampleSide | None
    mood: CodedValue[ExampleMood] | None
    profile: ExampleProfile | None
    tags: tuple[str | None, ...] | None
    dates: tuple[date, ...]
    moods: tuple[CodedValue[ExampleMood], ...]
    entries: tuple[ExampleEntry, ...]
    unknown: Mapping[str, int]


TEXT_SAMPLES = (
    "Alex Example",
    "",
    "comma, inside",
    'quote " inside',
    "line\nbreak",
    "Łukasz Exämple 東京",
    " padded ",
)


def sometimes_none[ValueT](random_source: random.Random, value: ValueT) -> ValueT | None:
    return None if random_source.random() < 0.3 else value


def sampled_date(random_source: random.Random) -> date:
    return date(random_source.randint(1990, 2035), random_source.randint(1, 12), 28)


def sampled_mood(random_source: random.Random) -> CodedValue[ExampleMood]:
    return CodedValue.from_raw(ExampleMood, random_source.choice((1, 2, 9)))


def sampled_spell(random_source: random.Random) -> ExampleSpell:
    return ExampleSpell(
        sometimes_none(random_source, sampled_date(random_source)),
        sometimes_none(random_source, sampled_mood(random_source)),
    )


def sampled_unknown(random_source: random.Random, keys: tuple[str, ...]) -> Mapping[str, int]:
    unknown_values = {key: random_source.randint(-5, 5) for key in keys}
    kept_values = {
        key: value for key, value in unknown_values.items() if random_source.random() < 0.5
    }
    return FrozenMapping(kept_values) if random_source.random() < 0.5 else kept_values


def sampled_record(random_source: random.Random, uid: int) -> ExampleSampledRecord:
    return ExampleSampledRecord(
        uid=uid * random_source.choice((1, -1, 10**12)),
        name=sometimes_none(random_source, random_source.choice(TEXT_SAMPLES)),
        on_loan=sometimes_none(random_source, random_source.random() < 0.5),
        born=sometimes_none(random_source, sampled_date(random_source)),
        side=sometimes_none(random_source, random_source.choice(tuple(ExampleSide))),
        mood=sometimes_none(random_source, sampled_mood(random_source)),
        profile=sometimes_none(
            random_source,
            ExampleProfile(
                sometimes_none(random_source, random_source.randint(0, 200)),
                random_source.random() < 0.5,
                sometimes_none(random_source, sampled_spell(random_source)),
            ),
        ),
        tags=sometimes_none(
            random_source,
            tuple(
                sometimes_none(random_source, random_source.choice(TEXT_SAMPLES))
                for _ in range(random_source.randint(0, 3))
            ),
        ),
        dates=tuple(sampled_date(random_source) for _ in range(random_source.randint(0, 2))),
        moods=tuple(sampled_mood(random_source) for _ in range(random_source.randint(0, 3))),
        entries=tuple(
            ExampleEntry(
                sampled_mood(random_source),
                sometimes_none(random_source, random_source.choice(TEXT_SAMPLES)),
                sometimes_none(random_source, sampled_spell(random_source)),
                sampled_unknown(random_source, ExampleEntry.UNKNOWN_KEYS),
            )
            for _ in range(random_source.randint(0, 2))
        ),
        unknown=sampled_unknown(random_source, ExampleSampledRecord.UNKNOWN_KEYS),
    )


def sampled_records(seed: int) -> tuple[ExampleSampledRecord, ...]:
    random_source = random.Random(seed)
    return tuple(sampled_record(random_source, uid) for uid in range(random_source.randint(0, 30)))


def test_counts_and_csv_match_the_references_on_sampled_records() -> None:
    columns = list(export.column_names(ExampleSampledRecord))
    for seed in SAMPLED_SEEDS:
        records = sampled_records(seed)
        coverage = Table(records, ExampleSampledRecord).coverage
        expected_coverage = reference_coverage(records, ExampleSampledRecord)
        assert list(coverage.items()) == list(expected_coverage.items()), seed
        selection_source = random.Random(seed)
        selections: list[list[str] | None] = [
            None,
            selection_source.sample(columns, selection_source.randint(1, len(columns))),
        ]
        for selection in selections:
            assert written_csv_text(records, ExampleSampledRecord, selection) == (
                reference_csv_text(records, ExampleSampledRecord, selection)
            ), seed


def hand_written_records() -> tuple[ExampleSampledRecord, ExampleSampledRecord]:
    """A full record with a partial unknown mapping and coded tuples, and a sparse record."""
    full_record = ExampleSampledRecord(
        uid=7,
        name="Alex Example",
        on_loan=True,
        born=date(2001, 4, 28),
        side=ExampleSide.LEFT,
        mood=CodedValue.from_raw(ExampleMood, 2),
        profile=ExampleProfile(150, False, ExampleSpell(date(2030, 1, 28), None)),
        tags=("quick", None, "tall"),
        dates=(date(2029, 3, 28),),
        moods=(CodedValue.from_raw(ExampleMood, 1), CodedValue.from_raw(ExampleMood, 9)),
        entries=(),
        unknown={"x": 3, "z": -1},
    )
    sparse_record = ExampleSampledRecord(
        uid=8,
        name=None,
        on_loan=None,
        born=None,
        side=None,
        mood=None,
        profile=None,
        tags=None,
        dates=(),
        moods=(),
        entries=(
            ExampleEntry(CodedValue.from_raw(ExampleMood, 1), "comma, inside", None, {"b": 4}),
        ),
        unknown=FrozenMapping({"y": 0}),
    )
    return full_record, sparse_record


HAND_WRITTEN_COVERAGE = {
    "uid": 1.0,
    "name": 0.5,
    "on_loan": 0.5,
    "born": 0.5,
    "side": 0.5,
    "mood": 0.5,
    "mood_code": 0.5,
    "profile_level": 0.5,
    "profile_active": 0.5,
    "profile_spell_start": 0.5,
    "profile_spell_mood": 0.0,
    "profile_spell_mood_code": 0.0,
    "tags": 0.5,
    "dates": 1.0,
    "moods": 1.0,
    "moods_code": 1.0,
    "entries": 1.0,
    "unknown_x": 0.5,
    "unknown_y": 0.5,
    "unknown_z": 0.5,
}

HAND_WRITTEN_CSV_TEXT = (
    "uid,name,on_loan,born,side,mood,mood_code,profile_level,profile_active,"
    "profile_spell_start,profile_spell_mood,profile_spell_mood_code,tags,dates,moods,"
    "moods_code,entries,unknown_x,unknown_y,unknown_z\r\n"
    "7,Alex Example,true,2001-04-28,left,bold,2,150,false,2030-01-28,,,quick;;tall,"
    "2029-03-28,calm;unknown,1;9,,3,,-1\r\n"
    '8,,,,,,,,,,,,,,,,"[{""kind"":""calm"",""kind_code"":1,""note"":""comma, inside"",'
    '""spell"":{""start"":null,""mood"":null,""mood_code"":null},'
    '""unknown"":{""a"":null,""b"":4}}]",,0,\r\n'
)


def test_hand_written_records_give_the_hard_coded_coverage_and_csv_text() -> None:
    records = hand_written_records()
    coverage = Table(records, ExampleSampledRecord).coverage
    assert list(coverage.items()) == list(HAND_WRITTEN_COVERAGE.items())
    assert present_counts(records, ExampleSampledRecord) == {
        column_name: round(share * len(records))
        for column_name, share in HAND_WRITTEN_COVERAGE.items()
    }
    assert written_csv_text(records, ExampleSampledRecord, None) == HAND_WRITTEN_CSV_TEXT
    assert written_csv_text(records, ExampleSampledRecord, ["unknown_z", "moods_code"]) == (
        "unknown_z,moods_code\r\n-1,1;9\r\n,\r\n"
    )


def test_a_single_column_of_none_is_written_as_a_quoted_empty_cell() -> None:
    record = replace(sampled_records(1)[0], name=None)
    expected_text = 'name\r\n""\r\n'
    assert reference_csv_text((record,), ExampleSampledRecord, ["name"]) == expected_text
    assert written_csv_text((record,), ExampleSampledRecord, ["name"]) == expected_text


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"uid": True}, id="bool-in-an-int-field"),
        pytest.param({"uid": 7.5}, id="float-in-an-int-field"),
        pytest.param({"name": date(2031, 1, 2)}, id="date-in-a-str-field"),
        pytest.param({"name": ("a", None, 3)}, id="tuple-in-a-str-field"),
        pytest.param({"name": {"key": date(2031, 1, 2)}}, id="mapping-in-a-str-field"),
        pytest.param({"name": ExampleSide.LEFT}, id="text-enum-in-a-str-field"),
        pytest.param({"on_loan": 1}, id="int-in-a-bool-field"),
        pytest.param({"tags": ("a", {"key": 1})}, id="mapping-item-in-a-text-tuple"),
        pytest.param({"unknown": {"x": True}}, id="bool-unknown-value"),
    ],
)
def test_values_of_undeclared_types_are_written_like_the_reference_writer(
    changes: dict[str, object],
) -> None:
    record = replace(sampled_records(2)[0], **changes)
    for selection in (None, ["uid"], ["name"], ["unknown_x", "on_loan", "tags"]):
        assert written_csv_text((record,), ExampleSampledRecord, selection) == (
            reference_csv_text((record,), ExampleSampledRecord, selection)
        )


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"profile": ExampleSpell(None, None)}, id="group-of-another-class"),
        pytest.param({"mood": 3}, id="coded-value-that-is-an-int"),
        pytest.param({"tags": "not a tuple"}, id="tuple-that-is-a-string"),
        pytest.param({"moods": (None,)}, id="none-in-coded-values"),
        pytest.param({"entries": (ExampleSpell(None, None),)}, id="record-of-another-class"),
        pytest.param(
            {"entries": (ExampleEntry(3, None, None, {}),)},  # pyright: ignore[reportArgumentType]
            id="coded-value-inside-a-record-item",
        ),
        pytest.param({"unknown": {"x": 1, "stray": 2}}, id="undeclared-unknown-key"),
        pytest.param({"unknown": [("x", 1)]}, id="unknown-that-is-not-a-mapping"),
    ],
)
def test_counts_and_csv_reject_the_values_to_columns_rejects(changes: dict[str, object]) -> None:
    record = replace(sampled_records(2)[0], **changes)
    with pytest.raises((TypeError, ValueError)) as expected_error:
        export.to_columns([record], ExampleSampledRecord)
    expected_message = re.escape(str(expected_error.value))
    with pytest.raises(expected_error.type, match=expected_message):
        present_counts([record], ExampleSampledRecord)
    with pytest.raises(expected_error.type, match=expected_message):
        _ = Table([record], ExampleSampledRecord).coverage
    with pytest.raises(expected_error.type, match=expected_message):
        written_csv_text((record,), ExampleSampledRecord, None)


def test_records_of_another_type_are_rejected_under_the_public_operation_name(
    tmp_path: Path,
) -> None:
    wrong_records = (ExampleSpell(None, None),)
    expected_message = "expected ExampleSampledRecord records, not ExampleSpell"
    with pytest.raises(TypeError, match=f"^coverage {expected_message}$"):
        present_counts(wrong_records, ExampleSampledRecord)
    with pytest.raises(TypeError, match=f"^write_csv {expected_message}$"):
        written_csv_text(wrong_records, ExampleSampledRecord, None)
    with pytest.raises(TypeError, match=f"^write_records {expected_message}$"):
        cli._write_records(wrong_records, ExampleSampledRecord, "csv", None, io.StringIO())
    # The Table constructor already rejects such records, so they are put in place directly.
    table = Table((), ExampleSampledRecord)
    object.__setattr__(table, "_records", wrong_records)
    with pytest.raises(TypeError, match=f"^coverage {expected_message}$"):
        _ = table.coverage
    with pytest.raises(TypeError, match=f"^write_csv {expected_message}$"):
        table.write_csv(tmp_path / "table.csv")


def test_the_csv_writer_checks_the_columns_before_writing() -> None:
    stream = io.StringIO(newline="")
    with pytest.raises(ValueError, match="unknown columns: nope, also_nope"):
        export._write_records_csv(
            (),
            ExampleSampledRecord,
            stream,
            columns=["nope", "uid", "also_nope"],
            operation_name="write_csv",
        )
    with pytest.raises(TypeError, match="not a string"):
        export._write_records_csv(
            (), ExampleSampledRecord, stream, columns="uid", operation_name="write_csv"
        )
    assert stream.getvalue() == ""
    export._write_records_csv(
        (), ExampleSampledRecord, stream, columns=[], operation_name="write_csv"
    )
    assert stream.getvalue() == reference_csv_text((), ExampleSampledRecord, [])
