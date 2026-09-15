"""Clubs and the teams they field."""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class Team:
    """One team in a club's team list.

    Attributes:
        team_id: The team's id, which player records use to name their team (unconfirmed).
        slot: Position in the club's team list, 0 for the first entry. Which side each later
            slot holds, such as a reserve or youth team, is not known (unconfirmed).
    """

    team_id: int
    slot: int


@dataclass(frozen=True, slots=True)
class Club:
    """A club from the save's game database.

    Club names are not unique: look clubs up by uid.

    Attributes:
        uid: The club's id in the game database (unconfirmed).
        name: Full club name (unconfirmed).
        short_name: Short club name (unconfirmed).
        nation_id: Id of the nation whose league the club plays in (unconfirmed).
        fa_nation_id: Id of the nation whose football association the club belongs to. It
            differs from nation_id for a club that plays in another nation's league
            (unconfirmed).
        city_id: Id of the club's city, or None when the save stores the missing-id marker
            instead (unconfirmed).
        teams: The club's teams in stored order, or an empty tuple when the team list cannot
            be read (unconfirmed).
        reputation: Club reputation from 1 to 10000, or None when the save holds no valid
            value.
        last_league_position: League position at the end of the last completed season, or
            None when the save holds none. It is not the position in the current table.
    """

    uid: int
    name: str
    short_name: str
    nation_id: int
    fa_nation_id: int
    city_id: int | None
    teams: tuple[Team, ...]
    reputation: int | None
    last_league_position: int | None


register_field_statuses(Team, unconfirmed=("team_id", "slot"))
register_field_statuses(
    Club,
    verified=("reputation", "last_league_position"),
    unconfirmed=("uid", "name", "short_name", "nation_id", "fa_nation_id", "city_id", "teams"),
)
