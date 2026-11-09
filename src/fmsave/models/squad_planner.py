"""Numbered slots in the human manager's squad planner."""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class SquadPlannerSlot:
    """One numbered slot in the human manager's squad planner.

    Attributes:
        season_offset: 0 for the current season, 1 for the next, and 2 for the season after (unconfirmed).
        slot: Slot number from 1 to 27 in stored order (unconfirmed).
        player_uids: Player UIDs in depth order (unconfirmed). An empty slot is an empty
            tuple. Each unresolved player reference appears as None in its original place.
    """

    season_offset: int
    slot: int
    player_uids: tuple[int | None, ...]


register_field_statuses(SquadPlannerSlot, unconfirmed=("season_offset", "slot", "player_uids"))
