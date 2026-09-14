"""The registry of field statuses: whether each public field's meaning is verified."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Literal

from fmsave._frozen import FrozenMapping

type FieldStatus = Literal["verified", "unconfirmed"]

unconfirmed_marker = "(unconfirmed)"

_statuses_by_class: dict[type, dict[str, FieldStatus]] = {}


def _path_list(model_class: type, paths: Iterable[str], argument_name: str) -> list[str]:
    if isinstance(paths, str):
        raise TypeError(
            f"{argument_name} for {model_class.__name__} must be an iterable of paths, not a string"
        )
    return list(paths)


def _dataclass_field_names(model_class: type) -> set[str]:
    if not dataclasses.is_dataclass(model_class):
        return set()
    return {model_field.name for model_field in dataclasses.fields(model_class)}


def register_field_statuses(
    model_class: type, *, verified: Iterable[str] = (), unconfirmed: Iterable[str] = ()
) -> None:
    """Record the status of fields of a record class.

    Field paths use dots for nested groups, for example "ability.current" or "contract.wage".
    Registering a path again with the same status is allowed. When any path is rejected,
    nothing from the call is recorded.

    Raises:
        TypeError: verified or unconfirmed is a single string instead of an iterable of paths.
        ValueError: A path is malformed, its first part is not a dataclass field of the class, it
            is listed with both statuses, it is already registered with the other status, or a
            different class with the same name already has registered statuses.
    """
    class_name = model_class.__name__
    requested_statuses: dict[str, FieldStatus] = {}
    for field_path in _path_list(model_class, verified, "verified"):
        requested_statuses[field_path] = "verified"
    for field_path in _path_list(model_class, unconfirmed, "unconfirmed"):
        if requested_statuses.get(field_path) == "verified":
            raise ValueError(
                f"{class_name}.{field_path} is listed as both verified and unconfirmed"
            )
        requested_statuses[field_path] = "unconfirmed"

    field_names = _dataclass_field_names(model_class)
    for field_path in requested_statuses:
        path_parts = field_path.split(".")
        if not all(path_part.isidentifier() for path_part in path_parts):
            raise ValueError(f"malformed field path {field_path!r} for {class_name}")
        if path_parts[0] not in field_names:
            raise ValueError(
                f"{class_name} has no dataclass field {path_parts[0]!r} (path {field_path!r})"
            )

    for registered_class in _statuses_by_class:
        if registered_class is not model_class and registered_class.__name__ == class_name:
            raise ValueError(f"a different class named {class_name} already has field statuses")

    existing_statuses = _statuses_by_class.get(model_class, {})
    for field_path, status in requested_statuses.items():
        existing_status = existing_statuses.get(field_path)
        if existing_status is not None and existing_status != status:
            raise ValueError(
                f"{class_name}.{field_path} is already registered as {existing_status}"
            )

    if requested_statuses:
        _statuses_by_class.setdefault(model_class, {}).update(requested_statuses)


def field_status(model_class: type, field_name: str) -> FieldStatus:
    """Return whether the meaning of a public record field is verified or unconfirmed.

    Args:
        model_class: A record class, for example fmsave.SaveInfo.
        field_name: The field name, with dots for nested groups, for example "contract.wage".

    Raises:
        KeyError: The field has no registered status.
    """
    try:
        return _statuses_by_class[model_class][field_name]
    except KeyError:
        raise KeyError(
            f"{model_class.__name__} has no registered status for {field_name!r}"
        ) from None


def registered_statuses() -> FrozenMapping[str, FieldStatus]:
    """Return every registered status, keyed by "<ClassName>.<field path>" in sorted order."""
    named_statuses: dict[str, FieldStatus] = {
        f"{model_class.__name__}.{field_path}": status
        for model_class, statuses in _statuses_by_class.items()
        for field_path, status in statuses.items()
    }
    sorted_statuses: dict[str, FieldStatus] = dict(sorted(named_statuses.items()))
    return FrozenMapping(sorted_statuses)
