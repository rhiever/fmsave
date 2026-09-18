"""Per-match player records: what one player did in one match the save still holds.

**This is never a full season, and never a career.** The save keeps a capped history of about
twenty matches per player per spell at a team, **counted across all competitions at once** and
not per competition, dropping the oldest as new ones arrive. So a player who has played more
than that in his current spell has only his most recent matches here, and **a per-competition
total summed from these records is short without saying so**: it looks ordinary, nothing marks
it as truncated, and a sum that happens to match a figure the game displays is a coincidence
rather than a confirmation. Friendlies, internationals and youth matches are kept apart from
these records and none of them appears here at all.

A record's `competition_id` belongs to the **stage** id space, the same space `stages()`,
`fixtures()` and the league tables use. It does **not** join to
`Suspension.suspension_competition_id`, which belongs to a separate suspension id space.

The position a record stores is a bit mask of this structure's own, and a bit of it means
nothing anywhere else in the save.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


class MatchPosition(IntEnum):
    """The position a player filled in one match, for the mask bits whose meaning is confirmed.

    The save stores the position as a 16-bit mask carrying exactly one bit, and a member's
    value here is that bit's index, not the mask. Fourteen of the sixteen bits carry records on
    every save measured, so the mask covers a full set of positions; only one of them is named.

    A bit earns a name only where a position label the game itself displayed was matched to that
    exact bit, and only the goalkeeper bit is. Every record of a player the game labels "GK"
    carries this bit, and all but one of the records carrying it, over every save measured,
    belongs to a player the save rates a goalkeeper. No other bit has such a label: the players
    whose displayed label would separate one bit from its neighbours play several positions, so
    their label fits more than one bit, and a bit named from a neighbouring bit's meaning would
    be silently wrong where a raw mask is plainly incomplete.

    What the other bits are is therefore left open, and the raw mask is kept on every record so
    a caller can group by it. Grouping by the raw mask is sound whatever the bits mean; reading
    a position into one is not.

    A mask that is zero, carries a bit no label names, or carries more than one bit reads as
    UNKNOWN with its raw value kept. Fewer than five records per save carry a zero mask and none
    at all carries two bits.
    """

    UNKNOWN = -1
    GOALKEEPER = 0


@dataclass(frozen=True, slots=True)
class PlayerMatchStats:
    """One player's record of one match the save still holds.

    **Never a whole season and never a career.** The save keeps about twenty matches per player
    per spell at a team, counted across all competitions at once rather than per competition,
    and drops the oldest as new ones arrive. A per-competition total summed from these rows is
    therefore short without saying so, and nothing in a row marks it as truncated. Friendlies,
    internationals and youth matches are kept apart from these records and are not here at all.

    `competition_id` belongs to the **stage** id space, the same space `stages()`, `fixtures()`
    and the league tables use. It does **not** join to
    `Suspension.suspension_competition_id`, which belongs to a separate suspension id space.

    Attributes:
        player_uid: Uid of the player the record belongs to, which is the player whose object
            holds it (unconfirmed).
        player_name: Denormalised name of player_uid (unconfirmed).
        date: The date the match was played.
        competition_id: Id of the competition, in the **stage** id space (not the id space a
            suspension's competition id belongs to). It is stored on the record itself rather
            than reached through a stage.
        opponent_team_id: The opposing side's first-team id, exactly as stored. It is a team
            id and never a club index.
        opponent_club_uid: Uid of the club fielding the opposing team, or None when no club
            lists that team.
        opponent_club_name: Denormalised name of opponent_club_uid, or None when the team does
            not resolve.
        opponent_club_short_name: Denormalised short name of opponent_club_uid, or None when
            the team does not resolve.
        opponent_team_slot: The opposing team's slot in its club's team list, 0 for the first
            entry, or None when the team does not resolve (unconfirmed).
        played: Whether the save holds a performance body for this match. Every field below
            that can be None is None when it is false, because the record then stops before
            them and the bytes where they would sit belong to the next match (unconfirmed).
        position: The position played, as a coded value over the mask the record stores. Only
            the goalkeeper bit is named; every other mask keeps its raw value and reads as
            UNKNOWN. None when the save holds no body.
        minutes: Minutes played, or None when the save holds no body. No value the game
            displays has been matched to this number; what says it is minutes played is its
            shape. On the saves measured about half of bodies hold exactly 90, over 0.993
            hold 90 or less, none holds more than 130, and the rest are spread over the
            values below 90 rather than clustered (unconfirmed).
        left_at_minute: The minute the player left the pitch, which is 0 for a player who was
            still on at the end; None when the save holds no body (unconfirmed).
        goals: Goals scored, or None when the save holds no body.
        assists: Assists, or None when the save holds no body. This is a **hypothesis**: no
            displayed label has been matched to this byte, and the count shown on a player's
            season statistics screen is what would confirm it (unconfirmed).
        rating: The match rating, which is the stored number divided by ten and so exact to one
            decimal; None when the save holds no body. A match the game gave no rating for
            stores zero (unconfirmed).
        passes_attempted: Passes attempted, or None when the save holds no body (unconfirmed).
        passes_completed: Passes completed, or None when the save holds no body (unconfirmed).
        body_valid: fmsave's own sanity flag, not a value the save stores: true when the save
            holds a body for this match and its minutes, rating and goals are all inside the
            bounds a match can reach. A false flag never blanks a value; every number is kept
            exactly as stored so a caller can see what the save holds (unconfirmed).
        unknown: Numeric fields with no known meaning. "role_code" moves with the position
            played but its meaning is not established, and it is None without a body, so it is
            absent from the mapping then; "tag" is inside the header and is always read
            (unconfirmed).
    """

    player_uid: int
    player_name: str | None
    date: datetime.date
    competition_id: int
    opponent_team_id: int
    opponent_club_uid: int | None
    opponent_club_name: str | None
    opponent_club_short_name: str | None
    opponent_team_slot: int | None
    played: bool
    position: CodedValue[MatchPosition] | None
    minutes: int | None
    left_at_minute: int | None
    goals: int | None
    assists: int | None
    rating: float | None
    passes_attempted: int | None
    passes_completed: int | None
    body_valid: bool
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("tag", "role_code")


register_field_statuses(
    PlayerMatchStats,
    verified=(
        "date",
        "competition_id",
        "opponent_team_id",
        "opponent_club_uid",
        "opponent_club_name",
        "opponent_club_short_name",
        "position",
        "goals",
    ),
    unconfirmed=(
        "player_uid",
        "player_name",
        "opponent_team_slot",
        "played",
        "minutes",
        "assists",
        "left_at_minute",
        "rating",
        "passes_attempted",
        "passes_completed",
        "body_valid",
        "unknown",
    ),
)
