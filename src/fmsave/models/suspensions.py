"""Unserved suspensions: bans a player has been given and has not yet served.

The save keeps a player's suspension only while it is unserved. Every unserved ban it holds is
listed here, including bans the game no longer shows because no fixture is left to serve them,
for example after a cup exit; the save stores no flag that tells those apart. A suspension's
competition id belongs to the suspension id space, not to the id space of fixture stages, so
the two do not join; competition names arrive in a later release.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class PlayerSuspension:
    """One unserved suspension, as listed on its player.

    Attributes:
        suspension_competition_id: Id of the competition the ban applies to, in the
            suspension id space (not the id space of fixture stages); competition names
            arrive in a later release.
        issued_date: Date the ban was issued.
    """

    suspension_competition_id: int
    issued_date: date


@dataclass(frozen=True, slots=True)
class Suspension:
    """One unserved suspension, with its player and the club the player belongs to.

    A ban the game no longer shows, because no fixture is left to serve it, is listed here
    too.

    Attributes:
        player_uid: Uid of the suspended player.
        player_name: Denormalised name of player_uid (unconfirmed).
        club_uid: Uid of the club the player belongs to, which for a player registered with
            a team another club controls is that controlling club; None for a free agent or
            a team that does not resolve to a club.
        club_name: Denormalised full name of club_uid.
        suspension_competition_id: Id of the competition the ban applies to, in the
            suspension id space (not the id space of fixture stages); competition names
            arrive in a later release.
        issued_date: Date the ban was issued.
        unknown: Numeric fields with no known meaning (unconfirmed).
    """

    player_uid: int
    player_name: str | None
    club_uid: int | None
    club_name: str | None
    suspension_competition_id: int
    issued_date: date
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("e7", "e14")


register_field_statuses(
    PlayerSuspension,
    verified=("suspension_competition_id", "issued_date"),
)
register_field_statuses(
    Suspension,
    verified=("player_uid", "club_uid", "club_name", "suspension_competition_id", "issued_date"),
    unconfirmed=("player_name", "unknown"),
)
