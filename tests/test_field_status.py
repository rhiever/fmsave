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
from fmsave._status import (
    field_status,
    register_field_statuses,
    registered_statuses,
    unconfirmed_marker,
)
from fmsave.models import CodedValue

ATTRIBUTE_ENTRY_PATTERN = re.compile(r"^ {4}(\w+): (.*)$")


@dataclass(frozen=True, slots=True)
class ExampleAbility:
    current: int
    potential: int


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    uid: int
    ability: ExampleAbility


@pytest.fixture(autouse=True)
def restore_registry() -> Iterator[None]:
    saved_statuses = {
        model_class: dict(statuses) for model_class, statuses in _status._statuses_by_class.items()
    }
    yield
    _status._statuses_by_class.clear()
    _status._statuses_by_class.update(saved_statuses)


def register_example_record() -> None:
    register_field_statuses(
        ExampleRecord, verified=["uid", "ability.current"], unconfirmed=["ability.potential"]
    )


def test_registered_paths_report_their_status() -> None:
    register_example_record()
    assert field_status(ExampleRecord, "ability.potential") == "unconfirmed"
    assert field_status(ExampleRecord, "ability.current") == "verified"
    assert field_status(ExampleRecord, "uid") == "verified"
    assert registered_statuses()["ExampleRecord.ability.current"] == "verified"


def test_registered_statuses_are_sorted_and_read_only() -> None:
    register_example_record()
    statuses = registered_statuses()
    assert isinstance(statuses, FrozenMapping)
    assert list(statuses) == sorted(statuses)
    with pytest.raises(TypeError):
        statuses["ExampleRecord.uid"] = "unconfirmed"  # type: ignore[index]
    assert field_status(ExampleRecord, "uid") == "verified"


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
    register_example_record()
    with pytest.raises(KeyError, match=r"ExampleRecord.*'missing'"):
        field_status(ExampleRecord, "missing")
    with pytest.raises(KeyError, match=r"ExampleAbility.*'current'"):
        field_status(ExampleAbility, "current")


def test_same_status_can_be_registered_again() -> None:
    register_example_record()
    register_field_statuses(ExampleRecord, verified=["uid"], unconfirmed=["ability.potential"])
    assert field_status(ExampleRecord, "uid") == "verified"


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


def test_unconfirmed_marker_text() -> None:
    assert unconfirmed_marker == "(unconfirmed)"


def nested_group_class(field_type: object) -> type | None:
    if typing.get_origin(field_type) in (typing.Union, types.UnionType):
        candidate_types = [
            argument for argument in typing.get_args(field_type) if argument is not type(None)
        ]
    else:
        candidate_types = [field_type]
    if len(candidate_types) != 1:
        return None
    candidate_type = candidate_types[0]
    if (
        isinstance(candidate_type, type)
        and dataclasses.is_dataclass(candidate_type)
        and candidate_type is not CodedValue
    ):
        return candidate_type
    return None


def field_types(model_class: type) -> dict[str, object]:
    type_parameters = {
        parameter.__name__: parameter for parameter in getattr(model_class, "__type_params__", ())
    }
    return typing.get_type_hints(model_class, localns=type_parameters)


def documented_classes(model_class: type, prefix: str = "") -> Iterator[tuple[type, str]]:
    """Yield the model class and every nested group class, each with its path prefix."""
    yield model_class, prefix
    resolved_types = field_types(model_class)
    for model_field in dataclasses.fields(model_class):
        group_class = nested_group_class(resolved_types[model_field.name])
        if group_class is not None:
            yield from documented_classes(group_class, f"{prefix}{model_field.name}.")


def leaf_field_paths(model_class: type) -> set[str]:
    leaf_paths: set[str] = set()
    for owner_class, prefix in documented_classes(model_class):
        resolved_types = field_types(owner_class)
        for model_field in dataclasses.fields(owner_class):
            if nested_group_class(resolved_types[model_field.name]) is None:
                leaf_paths.add(f"{prefix}{model_field.name}")
    return leaf_paths


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


PUBLIC_MODEL_CLASSES = [
    exported
    for exported_name in fmsave.models.__all__
    if isinstance(exported := getattr(fmsave.models, exported_name), type)
    and dataclasses.is_dataclass(exported)
]


def test_public_models_include_the_save_metadata() -> None:
    assert {fmsave.SaveInfo, fmsave.SectionInfo, CodedValue} <= set(PUBLIC_MODEL_CLASSES)


@pytest.mark.parametrize(
    "model_class", PUBLIC_MODEL_CLASSES, ids=[model.__name__ for model in PUBLIC_MODEL_CLASSES]
)
def test_every_public_model_field_has_a_status(model_class: type) -> None:
    expected_paths = leaf_field_paths(model_class)
    for field_path in expected_paths:
        assert field_status(model_class, field_path) in ("verified", "unconfirmed"), field_path
    name_prefix = f"{model_class.__name__}."
    registered_paths = {
        registered_key.removeprefix(name_prefix)
        for registered_key in registered_statuses()
        if registered_key.startswith(name_prefix)
    }
    assert registered_paths == expected_paths


@pytest.mark.parametrize(
    "model_class", PUBLIC_MODEL_CLASSES, ids=[model.__name__ for model in PUBLIC_MODEL_CLASSES]
)
def test_docstrings_mark_exactly_the_unconfirmed_fields(model_class: type) -> None:
    for owner_class, prefix in documented_classes(model_class):
        entries = attribute_entries(owner_class)
        resolved_types = field_types(owner_class)
        field_names = [model_field.name for model_field in dataclasses.fields(owner_class)]
        assert set(entries) == set(field_names), owner_class.__name__
        for field_name in field_names:
            if nested_group_class(resolved_types[field_name]) is None:
                expects_marker = field_status(model_class, prefix + field_name) == "unconfirmed"
            else:
                expects_marker = False
            has_marker = unconfirmed_marker in entries[field_name]
            assert has_marker == expects_marker, f"{owner_class.__name__}.{field_name}"


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


def test_docstring_check_reads_nested_groups_and_continuation_lines() -> None:
    assert attribute_entries(ExampleContract) == {
        "wage": "Weekly wage, spread over two lines (unconfirmed).",
        "months": "Months left.",
    }
    assert leaf_field_paths(ExamplePlayer) == {
        "uid",
        "contract.wage",
        "contract.months",
        "status",
    }
