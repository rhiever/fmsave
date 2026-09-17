"""Injury records: the names the game gives the injuries it can hand out, and who was hurt.

The names are the game's own text, as the save stores it, in the language the save was written
in. They are not in any section of the save: every per-match file the save holds carries one
copy of the table, so a save that holds no per-match file has no names at all. Some injury
codes have no entry in the table, so a code a player's injury carries need not be named here.

The history is one table of two kinds of row. A `HISTORY` row is an injury the game's Injury
History tab shows: when it happened, and which team the person was at. A `TYPED` row carries
the injury type of a recent or current episode. The save keeps the history for about the last
two years only.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


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


class InjuryRecordKind(StrEnum):
    """Which of the save's two injury stores a row came out of."""

    HISTORY = "history"
    TYPED = "typed"


class InjuryCause(IntEnum):
    """How an injury came about. No in-game label names any stored code yet."""

    UNKNOWN = -1


class InjurySeverity(IntEnum):
    """How bad an injury was. No in-game label names any stored code yet."""

    UNKNOWN = -1


@dataclass(frozen=True, slots=True)
class InjuryRecord:
    """One injury the save remembers, of either kind.

    Attributes:
        kind: Which store the row came from: HISTORY for an injury that happened, TYPED for a
            row carrying an injury type (verified).
        player_uid: Uid of the person the row is stored against, or None when the save no
            longer keeps that person as a player, which is about one HISTORY row in twenty
            (unconfirmed).
        player_name: Denormalised display name of player_uid; None wherever player_uid is
            (unconfirmed).
        date: When the injury happened, on a HISTORY row. On a TYPED row it is the row's own
            date, which can be days behind or weeks ahead of the in-game date, and None when
            the save stores no date at all (verified).
        team_id: Id of the team the person was registered with at the time, on a HISTORY row;
            None on every TYPED row, which carries no team (verified).
        club_uid: Uid of the club that fields team_id, which for a team another club controls
            is the controlling club; None when no club lists that team and on every TYPED row
            (verified).
        club_name: Denormalised full name of club_uid; None wherever club_uid is (verified).
        team_slot: The team's slot in club_uid's team list, counting that club's own teams
            first and then the teams it controls; None wherever club_uid is (unconfirmed).
        type_id: The injury's type code, on a TYPED row; None on every HISTORY row, which
            carries no type (verified).
        type_name: Denormalised name of type_id from `Save.injury_types`, None for the codes
            that table has no entry for and on every row of a save with no per-match file
            (unconfirmed).
        cause: How the injury came about, on a HISTORY row; None on every TYPED row. Every
            stored code reads UNKNOWN and keeps its raw number (unconfirmed).
        severity: How bad the injury was, on a HISTORY row; None on every TYPED row. Every
            stored code reads UNKNOWN and keeps its raw number (unconfirmed).
        unknown: Numeric fields with no known meaning, each present only on the kind of row
            that carries it: `r0` a byte that is 1 on every row of every save, `hi7_date` the
            time-slot bits of the row's date word, and, on a TYPED row, `r11` and `r12`
            (unconfirmed).
    """

    kind: InjuryRecordKind
    player_uid: int | None
    player_name: str | None
    date: datetime.date | None
    team_id: int | None
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    type_id: int | None
    type_name: str | None
    cause: CodedValue[InjuryCause] | None
    severity: CodedValue[InjurySeverity] | None
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("r0", "r11", "r12", "hi7_date")


# The id is the space the typed injury records use, which is measured rather than displayed;
# it becomes verified once an in-game screen names one of these codes.
register_field_statuses(InjuryType, unconfirmed=("id", "name", "unknown"))
# The person link is the stored index plus one, which is measured against the player records
# rather than shown anywhere, and `type_name` is only as good as `InjuryType.name` it copies.
register_field_statuses(
    InjuryRecord,
    verified=("kind", "date", "team_id", "club_uid", "club_name", "type_id"),
    unconfirmed=(
        "player_uid",
        "player_name",
        "team_slot",
        "type_name",
        "cause",
        "severity",
        "unknown",
    ),
)
