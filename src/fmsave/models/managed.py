"""Clubs managed by the save's human managers."""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class ManagedClub:
    """A club run by one of the save's human managers.

    The link from a human manager to a club is proven only on saves with a single human
    manager. On a save with several human managers, only the first one may be listed. A
    manager with no current club, for example one between jobs, has no row.

    Attributes:
        club_uid: Uid of the managed club (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        club_short_name: Denormalised short name of club_uid (unconfirmed).
        manager_name: The human manager's name as the save summary stores it, or None when
            the summary does not name the manager next to the club (unconfirmed).
        manager_staff_uid: Uid of the human manager's own record, which is a `Staff.uid`
            and joins to the staff table; None when it cannot be identified exactly.
            manager_name is this person's name (unconfirmed).
        balance: The club's balance on the save's date, the finances screen's Overall
            Balance, in the same stored unit as `FinanceMonth`. It is not the last
            `FinanceMonth.balance`, which closes the previous month: this one also carries
            the current month's money so far. None on a build with no layout for it (every
            FM26 build so far) or when the club's finance record does not pass its checks.
        scouting_budget: The club's scouting budget for the season, in the same unit
            (unconfirmed). It is the season's total, **not** what is left to spend: it stays
            the same while `scouting_budget_remaining` falls. None on a build with no layout
            for it (every FM26 build so far), on a save with more than one human manager, or
            when it cannot be found exactly once.
        scouting_budget_remaining: What is left of scouting_budget (unconfirmed). None
            whenever scouting_budget is None.
    """

    club_uid: int
    club_name: str
    club_short_name: str
    manager_name: str | None
    manager_staff_uid: int | None
    balance: int | None = None
    scouting_budget: int | None = None
    scouting_budget_remaining: int | None = None


# The balance matched the Overall Balance on two careers' finances screens, each time equal to
# the previous month's closing balance less the month's expenditure the screen showed. The
# scouting pair matched the Scouting Budget on the same screens, but only on days when nothing
# had been spent, so neither screen tells the season's budget from what is left of it.
register_field_statuses(
    ManagedClub,
    verified=("balance",),
    unconfirmed=(
        "club_uid",
        "club_name",
        "club_short_name",
        "manager_name",
        "manager_staff_uid",
        "scouting_budget",
        "scouting_budget_remaining",
    ),
)
