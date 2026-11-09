"""Match officials decoded from the save."""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class Official:
    """One match official.

    Attributes:
        referee_id: Save-local ID used by `Fixture.referee_id`.
        person_uid: The official's person UID.
        name: The official's name, or None when no name resolves.
    """

    referee_id: int
    person_uid: int
    name: str | None


register_field_statuses(Official, verified=("referee_id", "person_uid", "name"))
