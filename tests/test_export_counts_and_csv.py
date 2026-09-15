"""Coverage counts built straight from records, checked against a plain reference.

present_counts and Table.coverage are compared with counts taken from the columns to_columns
builds.
"""

from __future__ import annotations

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
from fmsave import Club, CodedValue, Contract, ManagedClub, Player, Suspension, Table, export
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
        suspended_player.contract, squad_status=None, type=None, clauses=(), unknown={}
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
            replace(suspensions[0], club_uid=None, club_name=None, unknown={"e14": 1}),
        ),
        Club: (*clubs, replace(clubs[0], teams=(), reputation=None, city_id=None)),
        ManagedClub: (
            *managed_clubs,
            replace(managed_clubs[0], manager_name=None, manager_person_uid=None),
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
        assert export.present_counts(chosen_records, record_type) == reference_present_counts(
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


def test_counts_match_the_reference_on_sampled_records() -> None:
    for seed in SAMPLED_SEEDS:
        records = sampled_records(seed)
        coverage = Table(records, ExampleSampledRecord).coverage
        expected_coverage = reference_coverage(records, ExampleSampledRecord)
        assert list(coverage.items()) == list(expected_coverage.items()), seed


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
def test_counts_reject_the_values_to_columns_rejects(changes: dict[str, object]) -> None:
    record = replace(sampled_records(2)[0], **changes)
    with pytest.raises((TypeError, ValueError)) as expected_error:
        export.to_columns([record], ExampleSampledRecord)
    expected_message = re.escape(str(expected_error.value))
    with pytest.raises(expected_error.type, match=expected_message):
        export.present_counts([record], ExampleSampledRecord)
    with pytest.raises(expected_error.type, match=expected_message):
        _ = Table([record], ExampleSampledRecord).coverage


def test_records_of_another_type_are_rejected() -> None:
    wrong_records = [ExampleSpell(None, None)]
    with pytest.raises(TypeError, match="present_counts expected ExampleSampledRecord"):
        export.present_counts(wrong_records, ExampleSampledRecord)
