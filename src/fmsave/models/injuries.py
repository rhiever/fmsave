"""Injury records: the names the game gives the injuries it can hand out.

The names are the game's own text, as the save stores it, in the language the save was written
in. They are not in any section of the save: every per-match file the save holds carries one
copy of the table, so a save that holds no per-match file has no names at all. Some injury
codes have no entry in the table, so a code a player's injury carries need not be named here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class InjuryType:
    """One named injury the game can hand out.

    Attributes:
        id: The code the save stores on an injury of this type (unconfirmed).
        name: The game's own name for the injury, in the language the save was written in
            (unconfirmed).
        unknown: Numeric fields with no known meaning: a flag byte, and a second id in an id
            space of its own (unconfirmed).
    """

    id: int
    name: str
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("flag", "second_id")


# The id is the space the typed injury records use, which is measured rather than displayed;
# it becomes verified once an in-game screen names one of these codes.
register_field_statuses(InjuryType, unconfirmed=("id", "name", "unknown"))
