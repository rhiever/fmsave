"""Training calendars, saved schedules and mentoring groups of the club a manager runs.

The save keeps one calendar per **team**, not one per club: the first team, the reserves, the
youth side and the teams the club fields at the clubs it controls each have their own, and no
club but the managed one has any at all. So the rows here are the teams of one club, and each
carries the team it belongs to.

**Which week runs which schedule is settled.** The save writes each week as its start date
followed by a schedule name, and the name belongs to the date written before it: a manager's
own Training screen showed the same schedule against the same week for four consecutive weeks,
where pairing each name with the following week -- what one earlier reader of this format did
-- would have been a week out on every one of them. The week's own start date is not in doubt
either: consecutive weeks step exactly seven days on every pair of every calendar measured.

**Each week also holds its seven days, three sessions a day**, in the order the Training
screen lists them. A session is a stored code: FM27's codes are named where a Training screen
showed the session's full name against them, and every other code, including every FM26 code,
reads as `TrainingSession.UNKNOWN` with its raw number kept.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


class TrainingSession(IntEnum):
    """What a training session is, as an FM27 save numbers it.

    A member's value is the code the save stores. **Eleven codes are named by a screen**: an
    FM27 manager's Training screen showed each of these names in full against the code stored
    for that slot, on every day of three weeks. MATCH is the slot the screen fills with the
    day's fixture rather than a word.

    **Every other code is UNKNOWN** and keeps its raw number. Codes 3, 4, 7, 200 to 203 and 304
    were on the same screen with their names cut short, so they are not completed by guesswork;
    the codes other teams and later weeks use have not been seen named on a screen this project
    has checked.

    **An FM26 save numbers its sessions differently**: its calendars hold neither the FM27
    code for rest nor the one for a match, although its match days carry a code of their own.
    So no FM26 session is labelled: each reads UNKNOWN with its raw number.
    """

    UNKNOWN = -1
    PASSING_STYLE = 0
    BUILD_UP = 1
    CHANCE_CREATION = 2
    PRESSING_INTENSITY = 5
    PRESSING_TRAP = 6
    REST = 300
    RECOVERY = 301
    LIGHT_CONDITIONING = 302
    CONDITIONING = 303
    TRAVEL = 402
    MATCH = 500


@dataclass(frozen=True, slots=True)
class TrainingDay:
    """One day of a week of a team's training calendar.

    Attributes:
        day: The date, which is the week's start plus the day's place in the week; None when
            the week's start does not decode.
        sessions: The day's three sessions in the order the Training screen lists them, top to
            bottom. On an FM26 save every session is UNKNOWN with its raw code (unconfirmed).
    """

    day: date | None
    sessions: tuple[CodedValue[TrainingSession], ...]


@dataclass(frozen=True, slots=True)
class TrainingWeek:
    """One week of a team's training calendar.

    Attributes:
        week_start: The day the week starts, None when the stored date does not decode.
        schedule_name: Name of the schedule the week runs, exactly as the save holds it. A
            schedule is a user's own file, so this is whatever it was called.
        days: The week's seven days in calendar order, starting on `week_start`. Empty when a
            week is built from only its start and name.
    """

    week_start: date | None
    schedule_name: str
    days: tuple[TrainingDay, ...] = ()


@dataclass(frozen=True, slots=True)
class TrainingSchedule:
    """One schedule the save keeps in the manager's own library of saved schedules.

    Attributes:
        folder: The folder the schedule is filed under (unconfirmed).
        name: The schedule's name (unconfirmed).
        unknown: Numeric fields with no known meaning: the id the save stores with the
            schedule, which is not the key a week's name is matched on. Where the save stores
            the same schedule twice, the copies differ only in this id (unconfirmed).
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
        schedule_library: The schedules the manager has saved, in stored order, or None when
            reading the library is unsupported. An empty tuple means an observed empty library.
            One library is stored per save rather than per team, so every row carries the same
            one. It holds only saved schedules: the game's own built-in ones are not in it, although a
            week may well name one. **The save may store a schedule more than once**: most
            saves measured hold twice as many entries as the Schedules screen lists, the same
            schedules over under two runs of ids, so count the distinct `(folder, name)` pairs
            rather than the entries to compare with a screen (unconfirmed).
    """

    team_id: int
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    weeks: tuple[TrainingWeek, ...]
    schedule_library: tuple[TrainingSchedule, ...] | None


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
        label: The group's label as the save stores it: the game's default wording with its
            number, or the name the group was given in game.
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


# The date is pinned by the seven-day step holding on every pair of every calendar, and the
# name beside it by a Training screen: four consecutive weeks showed the schedule this pairing
# gives them and not the one the other pairing would. The team key and its club join are
# structural: every block's team is a team of the managed club and each appears once. The slot
# is the club record's own order, which no screen has named.
register_field_statuses(
    TrainingWeek,
    verified=("week_start", "schedule_name", "days"),
)
# Where each day falls is pinned on both editions: an FM27 Training screen showed every session
# of three consecutive weeks on the day this places it, and on two FM26 careers the code that
# marks a match sits on exactly the dates of the team's fixtures and on no other date. What an
# FM26 code means is not known, so the sessions stay unconfirmed.
register_field_statuses(
    TrainingDay,
    verified=("day",),
    unconfirmed=("sessions",),
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
