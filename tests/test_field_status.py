from __future__ import annotations

import dataclasses
import inspect
import re
import types
import typing
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

import fmsave
import fmsave.models
from fmsave import _status
from fmsave._frozen import FrozenMapping
from fmsave._status import field_status, register_field_statuses, registered_statuses
from fmsave.models import CodedValue

ATTRIBUTE_ENTRY_PATTERN = re.compile(r"^ {4}(\w+): (.*)$")
NON_RECORD_CLASSES: frozenset[type] = frozenset({CodedValue})
# How an unconfirmed field marks itself in the attribute line of its record's docstring.
UNCONFIRMED_MARKER = "(unconfirmed)"


@dataclass(frozen=True, slots=True)
class ExampleAbility:
    current: int
    potential: int


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    uid: int
    ability: ExampleAbility


@dataclass(frozen=True, slots=True)
class ExampleSquad:
    uid: int
    abilities: tuple[ExampleAbility, ...]


@dataclass(frozen=True, slots=True)
class ExampleContract:
    """A contract.

    Attributes:
        wage: Weekly wage, spread over
            two lines (unconfirmed).
        months: Months left.

    Other text after the section.
    """

    wage: int
    months: int | None


@dataclass(frozen=True, slots=True)
class ExamplePlayer:
    uid: int
    contract: ExampleContract | None
    status: CodedValue[typing.Any]


@dataclass(frozen=True, slots=True)
class ExampleMixedRecord:
    either: ExampleAbility | ExampleContract
    bare_status: CodedValue  # type: ignore[type-arg]


@pytest.fixture(autouse=True)
def restore_registry() -> Iterator[None]:
    saved_statuses = {
        model_class: dict(statuses) for model_class, statuses in _status._statuses_by_class.items()
    }
    yield
    _status._statuses_by_class.clear()
    _status._statuses_by_class.update(saved_statuses)


def register_example_record() -> None:
    register_field_statuses(ExampleAbility, verified=["current"], unconfirmed=["potential"])
    register_field_statuses(ExampleRecord, verified=["uid"])


def test_nested_paths_resolve_through_group_classes() -> None:
    register_example_record()
    assert field_status(ExampleRecord, "ability.potential") == "unconfirmed"
    assert field_status(ExampleRecord, "ability.current") == "verified"
    assert field_status(ExampleRecord, "uid") == "verified"
    assert field_status(ExampleAbility, "potential") == "unconfirmed"


def test_registered_statuses_are_one_level_sorted_and_read_only() -> None:
    register_example_record()
    statuses = registered_statuses()
    assert statuses["ExampleAbility.current"] == "verified"
    assert statuses["ExampleRecord.uid"] == "verified"
    assert "ExampleRecord.ability.current" not in statuses
    assert "ExampleRecord.ability" not in statuses
    assert isinstance(statuses, FrozenMapping)
    assert list(statuses) == sorted(statuses)
    with pytest.raises(TypeError):
        statuses["ExampleRecord.uid"] = "unconfirmed"  # type: ignore[index]
    assert field_status(ExampleRecord, "uid") == "verified"


def test_registering_a_dotted_path_raises_value_error() -> None:
    with pytest.raises(ValueError, match="own class"):
        register_field_statuses(ExampleRecord, verified=["ability.current"])
    with pytest.raises(KeyError):
        field_status(ExampleRecord, "ability.current")


def test_registering_a_group_field_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"ExampleRecord\.ability.*ExampleAbility"):
        register_field_statuses(ExampleRecord, verified=["ability"])
    with pytest.raises(ValueError, match=r"ExamplePlayer\.contract.*ExampleContract"):
        register_field_statuses(ExamplePlayer, unconfirmed=["contract"])
    assert not any(key.startswith("ExampleRecord.") for key in registered_statuses())


def test_tuple_of_dataclasses_registers_as_a_leaf() -> None:
    register_field_statuses(ExampleSquad, verified=["uid", "abilities"])
    assert field_status(ExampleSquad, "abilities") == "verified"
    with pytest.raises(KeyError, match=r"ExampleSquad.*'abilities\.current'"):
        field_status(ExampleSquad, "abilities.current")


def test_coded_value_field_registers_as_a_leaf() -> None:
    register_field_statuses(ExamplePlayer, verified=["uid"], unconfirmed=["status"])
    assert field_status(ExamplePlayer, "status") == "unconfirmed"


def test_unions_of_records_and_bare_coded_values_register_as_leaves() -> None:
    register_field_statuses(ExampleMixedRecord, verified=["either", "bare_status"])
    assert field_status(ExampleMixedRecord, "either") == "verified"
    assert field_status(ExampleMixedRecord, "bare_status") == "verified"
    with pytest.raises(KeyError, match=r"ExampleMixedRecord.*'either\.current'"):
        field_status(ExampleMixedRecord, "either.current")


def test_dotted_path_on_a_non_dataclass_raises_key_error() -> None:
    class ExamplePlainClass:
        uid: int = 0

    with pytest.raises(KeyError, match=r"ExamplePlainClass.*'uid\.x'"):
        field_status(ExamplePlainClass, "uid.x")


def test_coded_value_is_not_registered() -> None:
    assert not any(key.startswith("CodedValue.") for key in registered_statuses())


def test_registration_accepts_any_iterable_of_paths() -> None:
    register_field_statuses(ExampleRecord, verified=(path for path in ["uid"]))
    assert field_status(ExampleRecord, "uid") == "verified"


def test_single_string_instead_of_paths_raises_type_error() -> None:
    with pytest.raises(TypeError, match="verified"):
        register_field_statuses(ExampleRecord, verified="uid")
    with pytest.raises(TypeError, match="unconfirmed"):
        register_field_statuses(ExampleRecord, unconfirmed="uid")
    with pytest.raises(KeyError):
        field_status(ExampleRecord, "uid")


def test_unregistered_path_raises_key_error_naming_class_and_path() -> None:
    register_field_statuses(ExampleRecord, verified=["uid"])
    with pytest.raises(KeyError, match=r"ExampleRecord.*'missing'"):
        field_status(ExampleRecord, "missing")
    with pytest.raises(KeyError, match=r"ExampleRecord.*'ability\.current'"):
        field_status(ExampleRecord, "ability.current")
    with pytest.raises(KeyError, match=r"ExampleAbility.*'current'"):
        field_status(ExampleAbility, "current")


def test_unknown_segment_raises_key_error_naming_class_and_path() -> None:
    register_example_record()
    with pytest.raises(KeyError, match=r"ExampleRecord.*'height\.current'"):
        field_status(ExampleRecord, "height.current")
    with pytest.raises(KeyError, match=r"ExampleRecord.*'ability\.height'"):
        field_status(ExampleRecord, "ability.height")


def test_path_through_a_non_group_field_raises_key_error() -> None:
    register_example_record()
    with pytest.raises(KeyError, match=r"ExampleRecord.*'uid\.x'"):
        field_status(ExampleRecord, "uid.x")


def test_same_status_can_be_registered_again() -> None:
    register_example_record()
    register_field_statuses(ExampleRecord, verified=["uid"])
    register_field_statuses(ExampleAbility, unconfirmed=["potential"])
    assert field_status(ExampleRecord, "ability.potential") == "unconfirmed"


def test_conflicting_re_registration_raises_value_error() -> None:
    register_example_record()
    with pytest.raises(ValueError, match=r"ExampleRecord\.uid"):
        register_field_statuses(ExampleRecord, unconfirmed=["uid"])
    assert field_status(ExampleRecord, "uid") == "verified"


def test_path_listed_as_both_statuses_raises_value_error() -> None:
    with pytest.raises(ValueError, match="uid"):
        register_field_statuses(ExampleRecord, verified=["uid"], unconfirmed=["uid"])
    with pytest.raises(KeyError):
        field_status(ExampleRecord, "uid")


def test_unknown_top_level_field_raises_value_error() -> None:
    with pytest.raises(ValueError, match="height"):
        register_field_statuses(ExampleRecord, verified=["height"])
    with pytest.raises(ValueError, match="height"):
        register_field_statuses(ExampleRecord, verified=["height.current"])


@pytest.mark.parametrize("malformed_path", ["", "ability.", "ability..current", "uid "])
def test_malformed_path_raises_value_error(malformed_path: str) -> None:
    with pytest.raises(ValueError):
        register_field_statuses(ExampleRecord, verified=[malformed_path])


def test_non_dataclass_model_raises_value_error() -> None:
    class ExamplePlainClass:
        uid: int = 0

    with pytest.raises(ValueError, match="uid"):
        register_field_statuses(ExamplePlainClass, verified=["uid"])


def test_registering_no_paths_records_nothing() -> None:
    statuses_before = dict(registered_statuses())
    register_field_statuses(ExampleRecord)
    assert dict(registered_statuses()) == statuses_before
    assert ExampleRecord not in _status._statuses_by_class


def test_failed_registration_changes_nothing() -> None:
    statuses_before = dict(registered_statuses())
    with pytest.raises(ValueError):
        register_field_statuses(ExampleRecord, verified=["uid", "ability"])
    with pytest.raises(ValueError):
        register_field_statuses(ExampleRecord, verified=["uid", "height"])
    assert dict(registered_statuses()) == statuses_before


def test_different_classes_sharing_a_name_raise_value_error() -> None:
    register_example_record()
    other_record_class = dataclasses.make_dataclass("ExampleRecord", [("uid", int)], frozen=True)
    with pytest.raises(ValueError, match="ExampleRecord"):
        register_field_statuses(other_record_class, verified=["uid"])


def test_real_registry_holds_save_info_statuses() -> None:
    assert fmsave.field_status(fmsave.SaveInfo, "game_date") == "unconfirmed"
    assert fmsave.field_status(fmsave.SaveInfo, "build") == "verified"
    assert fmsave.field_status(fmsave.SectionInfo, "unknown") == "unconfirmed"
    assert fmsave.field_status(fmsave.SectionInfo, "schema") == "verified"


def resolved_field_types(model_class: type) -> dict[str, object]:
    type_parameters = {
        parameter.__name__: parameter for parameter in getattr(model_class, "__type_params__", ())
    }
    return typing.get_type_hints(model_class, localns=type_parameters)


def without_none(field_type: object) -> list[object]:
    if typing.get_origin(field_type) in (typing.Union, types.UnionType):
        return [argument for argument in typing.get_args(field_type) if argument is not type(None)]
    return [field_type]


def is_record_class(candidate_type: object) -> typing.TypeGuard[type]:
    return (
        isinstance(candidate_type, type)
        and dataclasses.is_dataclass(candidate_type)
        and candidate_type not in NON_RECORD_CLASSES
    )


def group_class(field_type: object) -> type | None:
    member_types = without_none(field_type)
    if len(member_types) == 1 and is_record_class(member_types[0]):
        return member_types[0]
    return None


def leaf_field_names(record_class: type) -> set[str]:
    field_types = resolved_field_types(record_class)
    return {
        model_field.name
        for model_field in dataclasses.fields(record_class)
        if group_class(field_types[model_field.name]) is None
    }


def reachable_record_classes(record_class: type) -> Iterator[type]:
    """Yield the record class, then every group class and tuple element record class it uses."""
    yield record_class
    field_types = resolved_field_types(record_class)
    for model_field in dataclasses.fields(record_class):
        field_type = field_types[model_field.name]
        nested_classes = [
            argument
            for member_type in without_none(field_type)
            for argument in (
                typing.get_args(member_type)
                if typing.get_origin(member_type) is tuple
                else [member_type]
            )
            if is_record_class(argument)
        ]
        for nested_class in nested_classes:
            yield from reachable_record_classes(nested_class)


def attribute_entries(model_class: type) -> dict[str, str]:
    docstring_lines = inspect.cleandoc(model_class.__doc__ or "").splitlines()
    if "Attributes:" not in docstring_lines:
        return {}
    entry_parts: dict[str, list[str]] = {}
    current_parts: list[str] | None = None
    for line in docstring_lines[docstring_lines.index("Attributes:") + 1 :]:
        if not line.strip():
            continue
        if not line.startswith(" "):
            break
        entry_match = ATTRIBUTE_ENTRY_PATTERN.match(line)
        if entry_match is not None:
            current_parts = [entry_match.group(2)]
            entry_parts[entry_match.group(1)] = current_parts
        elif current_parts is not None:
            current_parts.append(line.strip())
    return {entry_name: " ".join(parts) for entry_name, parts in entry_parts.items()}


def public_record_classes() -> list[type]:
    found_classes: dict[str, type] = {}
    for exported_name in fmsave.models.__all__:
        exported = getattr(fmsave.models, exported_name)
        if not is_record_class(exported):
            continue
        for record_class in reachable_record_classes(exported):
            found_classes[f"{record_class.__module__}.{record_class.__qualname__}"] = record_class
    return [found_classes[class_key] for class_key in sorted(found_classes)]


PUBLIC_RECORD_CLASSES = public_record_classes()
PUBLIC_RECORD_IDS = [record_class.__name__ for record_class in PUBLIC_RECORD_CLASSES]


def test_public_records_include_the_save_metadata_but_not_coded_values() -> None:
    assert {fmsave.SaveInfo, fmsave.SectionInfo} <= set(PUBLIC_RECORD_CLASSES)
    assert CodedValue not in PUBLIC_RECORD_CLASSES


@pytest.mark.parametrize("record_class", PUBLIC_RECORD_CLASSES, ids=PUBLIC_RECORD_IDS)
def test_every_record_field_is_a_group_or_has_one_status(record_class: type) -> None:
    name_prefix = f"{record_class.__name__}."
    registered_fields = {
        registered_key.removeprefix(name_prefix)
        for registered_key in registered_statuses()
        if registered_key.startswith(name_prefix)
    }
    assert registered_fields == leaf_field_names(record_class)


@pytest.mark.parametrize("record_class", PUBLIC_RECORD_CLASSES, ids=PUBLIC_RECORD_IDS)
def test_docstrings_mark_exactly_the_unconfirmed_fields(record_class: type) -> None:
    entries = attribute_entries(record_class)
    field_names = [model_field.name for model_field in dataclasses.fields(record_class)]
    assert set(entries) == set(field_names), record_class.__name__
    leaf_names = leaf_field_names(record_class)
    for field_name in field_names:
        expects_marker = (
            field_name in leaf_names and field_status(record_class, field_name) == "unconfirmed"
        )
        has_marker = UNCONFIRMED_MARKER in entries[field_name]
        assert has_marker == expects_marker, f"{record_class.__name__}.{field_name}"


def test_docstring_parser_joins_continuation_lines() -> None:
    assert attribute_entries(ExampleContract) == {
        "wage": "Weekly wage, spread over two lines (unconfirmed).",
        "months": "Months left.",
    }


def test_completeness_helpers_find_groups_and_tuple_elements() -> None:
    assert leaf_field_names(ExamplePlayer) == {"uid", "status"}
    assert leaf_field_names(ExampleSquad) == {"uid", "abilities"}
    assert list(reachable_record_classes(ExamplePlayer)) == [ExamplePlayer, ExampleContract]
    assert list(reachable_record_classes(ExampleSquad)) == [ExampleSquad, ExampleAbility]
