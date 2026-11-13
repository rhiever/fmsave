"""Unserved suspensions: bans a player has been given and has not yet served.

The reader lists unserved bans it recognizes, including some the game no longer displays.
The reason those bans are hidden is unconfirmed.

A ban stores one id and one scope code that says what the id refers to. A ban on one
competition stores a competition id in the **stage** id space, the same space `stages()`,
`competitions()`, `fixtures()`, `league_tables()` and `player_match_stats()` use, so it joins
to all of them. Other bans store a **nation** id and can apply to a subset of that nation's
competitions. `competition_id` and `nation_id` are populated according to the reference
namespace.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import ClassVar

from fmsave._status import register_field_statuses


class SuspensionScope(StrEnum):
    """The kind of reference stored with a ban, or Europe for the recognized European form.

    The save writes one code per ban. Code 1 means the ban covers the one competition its id
    names. Codes 5, 6 and 10 carry a nation id and read as NATION. The set of competitions
    covered can vary by code. In FM26, code 5 matched the Domestic cup label on the Bans
    screen. `Suspension.scope_code` retains the original code. An UNKNOWN scope leaves both
    id fields empty. The EUROPE form also leaves both ids empty.
    """

    COMPETITION = "competition"
    NATION = "nation"
    EUROPE = "europe"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlayerSuspension:
    """One unserved suspension, as listed on its player.

    Attributes:
        scope: Whether the ban references a competition or a nation, has Europe scope, or is UNKNOWN.
        scope_code: The stored scope code. Code 1 references a competition. Codes 5, 6 and
            10 reference a nation and can differ in the competitions they cover. The recognized
            Europe form uses code 15.
        competition_id: Id of the competition the ban applies to, in the **stage** id space,
            so it joins `stages()`, `competitions()`, `fixtures()`, `league_tables()` and
            `player_match_stats()`. None unless the scope is COMPETITION.
        competition_name: Denormalised name of competition_id, which is None unless a name
            map is supplied, because the save stores no competition names. A competition the
            game itself created during the career has a database id no name source outside
            the save carries, so some rows stay unnamed even with a full map (unconfirmed).
        nation_id: Save-local id of the nation the ban references, in the same id space as
            `Club.nation_id` and `Player.nation_id`. None unless the scope is NATION.
        issued_date: Date the ban was issued.
    """

    scope: SuspensionScope
    scope_code: int
    competition_id: int | None
    competition_name: str | None
    nation_id: int | None
    issued_date: date


@dataclass(frozen=True, slots=True)
class Suspension:
    """One unserved suspension, with its player and the club the player belongs to.

    A ban the game no longer displays is listed here too.

    Attributes:
        player_uid: Uid of the suspended player, copied from the decoded player
            (unconfirmed).
        player_name: Denormalised name of player_uid (unconfirmed).
        club_uid: Uid of the club the player belongs to, which for a player registered with
            a team another club controls is that controlling club; None for a free agent or
            a team that does not resolve to a club. Copied from the decoded player
            (unconfirmed). It is the club the player belongs to **now**, which for an old
            ban need not be the club he was banned at.
        club_name: Denormalised full name of club_uid (unconfirmed).
        scope: Whether the ban references a competition or a nation, has Europe scope, or is UNKNOWN.
        scope_code: The stored scope code. Code 1 references a competition. Codes 5, 6 and
            10 reference a nation and can differ in the competitions they cover. The recognized
            Europe form uses code 15.
        competition_id: Id of the competition the ban applies to, in the **stage** id space,
            so it joins `stages()`, `competitions()`, `fixtures()`, `league_tables()` and
            `player_match_stats()`. None unless the scope is COMPETITION.
        competition_name: Denormalised name of competition_id, which is None unless a name
            map is supplied, because the save stores no competition names. A competition the
            game itself created during the career has a database id no name source outside
            the save carries, so some rows stay unnamed even with a full map (unconfirmed).
        nation_id: Save-local id of the nation the ban references, in the same id space as
            `Club.nation_id` and `Player.nation_id`. None unless the scope is NATION.
        issued_date: Date the ban was issued.
        unknown: Numeric fields with no known meaning (unconfirmed).
    """

    player_uid: int
    player_name: str | None
    club_uid: int | None
    club_name: str | None
    scope: SuspensionScope
    scope_code: int
    competition_id: int | None
    competition_name: str | None
    nation_id: int | None
    issued_date: date
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("e7",)


# scope, scope_code, competition_id and nation_id are verified together, because one
# measurement over several saves settles all four. Every ban whose scope code is 1 stores a
# number the save's own competition table holds, and wherever the fixture calendar can test
# it, the player's club played that very competition on the day the ban was issued - against
# a shuffled control that scores near nothing, and with every exception a ban old enough for
# the player to have changed club since. A ban whose code is 5, 6 or 10 never passes that
# test and instead stores a nation the player or his club holds, which no code-1 ban ever
# does. This verifies the reference namespace. The set of competitions covered can vary
# among codes that reference a nation.
register_field_statuses(
    PlayerSuspension,
    verified=("scope", "scope_code", "competition_id", "nation_id", "issued_date"),
    unconfirmed=("competition_name",),
)
# player_uid, club_uid and club_name are copies of Player fields, so they carry the status of
# the fields they are copied from rather than a stronger one of their own.
register_field_statuses(
    Suspension,
    verified=("scope", "scope_code", "competition_id", "nation_id", "issued_date"),
    unconfirmed=(
        "player_uid",
        "player_name",
        "club_uid",
        "club_name",
        "competition_name",
        "unknown",
    ),
)
