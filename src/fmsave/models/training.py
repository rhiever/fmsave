"""Training calendars, saved schedules and mentoring groups of the club a manager runs.

The save keeps one calendar per **team**, not one per club: the first team, the reserves, the
youth side and the teams the club fields at the clubs it controls each have their own, and no
club but the managed one has any at all. So the rows here are the teams of one club, and each
carries the team it belongs to.

**Which week runs which schedule is not confirmed.** The save writes each week as its start
date followed by a schedule name, and this reads the name as belonging to the date written
before it. That is what the bytes say, and it is the opposite of what one earlier reader of
this format did, so `TrainingWeek.schedule_name` stays `unconfirmed` until a Training screen
settles it. The week's own start date is not in doubt: consecutive weeks step exactly seven
days on every pair of every calendar measured.

What a week's sessions actually are is not read: each day holds three codes with no known
meaning, and nothing here presents them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class TrainingWeek:
    """One week of a team's training calendar.

    Attributes:
        week_start: The day the week starts, None when the stored date does not decode.
        schedule_name: Name of the schedule the save stores with that week, exactly as the
            save holds it. A schedule is a user's own file, so this is whatever it was called
            (unconfirmed).
    """

    week_start: date | None
    schedule_name: str


@dataclass(frozen=True, slots=True)
class TrainingSchedule:
    """One schedule the save keeps in the manager's own library of saved schedules.

    Attributes:
        folder: The folder the schedule is filed under (unconfirmed).
        name: The schedule's name (unconfirmed).
        unknown: Numeric fields with no known meaning: the id the save stores with the
            schedule, which is not the key a week's name is matched on (unconfirmed).
    """

    folder: str
    name: str
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("schedule_id",)


@dataclass(frozen=True, slots=True)
class TeamTraining:
    """One team's training calendar, with the library of schedules the save holds beside it.

    Attributes:
        team_id: The team whose calendar this is, as the save stores it.
        club_uid: Uid of the club that fields `team_id`, None for a team no club lists. For a
            team the managed club fields at a club it controls, this is the managed club.
        club_name: Denormalised full name of club_uid.
        team_slot: The team's place in that club's own team list, 0 for its first team; None
            when the team resolves to no club. Which side each slot is, such as a reserve or
            a youth team, is not known (unconfirmed).
        weeks: Every week of the calendar, in stored order, running from before the save's
            date to well after it.
        schedule_library: The schedules the manager has saved, in stored order. It is one
            library per save rather than per team, so every row carries the same one, and it
            holds only saved schedules: the game's own built-in ones are not in it, although a
            week may well name one (unconfirmed).
    """

    team_id: int
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    weeks: tuple[TrainingWeek, ...]
    schedule_library: tuple[TrainingSchedule, ...]


@dataclass(frozen=True, slots=True)
class MentoringGroup:
    """One mentoring group of one team of the managed club.

    Attributes:
        team_id: The team the group belongs to, as the save stores it.
        club_uid: Uid of the club that fields `team_id`, None for a team no club lists.
        club_name: Denormalised full name of club_uid.
        team_slot: The team's place in that club's own team list, 0 for its first team; None
            when the team resolves to no club (unconfirmed).
        group_number: The number the save stores with the group, which runs from one up
            within a team (unconfirmed).
        label: The group's label as the save stores it. Every group of every save measured
            carries the game's default wording with its number, and whether renaming a group
            in game changes the stored text has not been checked.
        member_uids: Uid of each member, in stored order, None for a member whose stored
            selector names no player record.
        member_names: Denormalised name of each entry of `member_uids`, aligned with it and
            None wherever that uid is.
    """

    team_id: int
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    group_number: int
    label: str
    member_uids: tuple[int | None, ...]
    member_names: tuple[str | None, ...]


# The date is pinned by the seven-day step holding on every pair of every calendar; the name
# beside it is not, because only a Training screen can say which week a name belongs to. The
# team key and its club join are structural: every block's team is a team of the managed club
# and each appears once. The slot is the club record's own order, which no screen has named.
register_field_statuses(
    TrainingWeek,
    verified=("week_start",),
    unconfirmed=("schedule_name",),
)
register_field_statuses(
    TrainingSchedule,
    unconfirmed=("folder", "name", "unknown"),
)
register_field_statuses(
    TeamTraining,
    verified=("team_id", "club_uid", "club_name", "weeks"),
    unconfirmed=("team_slot", "schedule_library"),
)
register_field_statuses(
    MentoringGroup,
    verified=(
        "team_id",
        "club_uid",
        "club_name",
        "label",
        "member_uids",
        "member_names",
    ),
    unconfirmed=("team_slot", "group_number"),
)
