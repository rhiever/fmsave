"""Club money: one row per club per month, and the sponsor contracts a club holds.

Money is a whole number in the save's base currency, which is not necessarily the currency the
game displays: one save measured shows euros at about 1.157 times the stored value. No save says
which currency the base is, so nothing here is converted.

The weekly fields are weekly amounts; every other money field is one month's amount, or a
balance at the end of a month.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


class SponsorType(IntEnum):
    """What kind of sponsorship a contract is.

    Every code is UNKNOWN: the save groups its sponsorships into about twenty kinds, and no
    displayed label has pinned one of those codes yet.
    """

    UNKNOWN = -1


@dataclass(frozen=True, slots=True)
class FinanceMonth:
    """One club's money in one month.

    Attributes:
        club_uid: Uid of the club (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        month: First day of the month the row covers, worked out from the save's own date
            (unconfirmed): the last row of a club is the month before the save's month.
        balance: The club's balance at the end of the month.
        transfer_budget_allocated: The transfer budget the board set (unconfirmed); it is
            below transfer_budget_remaining on about a quarter of rows.
        transfer_budget_remaining: What is left of the transfer budget.
        wage_budget_weekly: The wage budget, per week.
        wage_payroll_weekly: The wages being paid, per week.
        income_excluding_transfers: The month's income other than transfer fees
            (unconfirmed).
        net_transfers: The month's transfer flow, **positive for a net spend** (unconfirmed).
        wage_bill: The month's wage expenditure (unconfirmed).
        net: The month's income less its expenditure.
        expenditure_excluding_transfers: The month's expenditure other than transfer fees
            (unconfirmed).
        total_income: The month's total income (unconfirmed).
        total_expenditure: The month's total expenditure (unconfirmed).
    """

    club_uid: int
    club_name: str
    month: date
    balance: int
    transfer_budget_allocated: int
    transfer_budget_remaining: int
    wage_budget_weekly: int
    wage_payroll_weekly: int
    income_excluding_transfers: int
    net_transfers: int
    wage_bill: int
    net: int
    expenditure_excluding_transfers: int
    total_income: int
    total_expenditure: int


@dataclass(frozen=True, slots=True)
class Sponsorship:
    """One sponsorship contract of one club, running or ended.

    Attributes:
        club_uid: Uid of the club (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        type: What kind of sponsorship it is; every code is UNKNOWN (unconfirmed).
        start: The day the contract starts.
        end: The day it ends.
        total_value: The contract's whole value, which is the annual value times its whole
            years on about 19 contracts in 20.
        annual_value: What it pays a year; zero on a contract that has ended.
        unknown: Numeric fields with no known meaning (unconfirmed).
    """

    club_uid: int
    club_name: str
    type: CodedValue[SponsorType]
    start: date | None
    end: date | None
    total_value: int
    annual_value: int
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("flag10", "u15", "b17", "enum18", "b19")


register_field_statuses(
    FinanceMonth,
    verified=(
        "balance",
        "transfer_budget_remaining",
        "wage_budget_weekly",
        "wage_payroll_weekly",
        "net",
    ),
    # The month label rests on the one-month lag between the last row and the save's clock,
    # which is supported indirectly; the rest are read from known offsets whose meaning no
    # displayed figure has pinned yet.
    unconfirmed=(
        "club_uid",
        "club_name",
        "month",
        "transfer_budget_allocated",
        "income_excluding_transfers",
        "net_transfers",
        "wage_bill",
        "expenditure_excluding_transfers",
        "total_income",
        "total_expenditure",
    ),
)
register_field_statuses(
    Sponsorship,
    verified=("start", "end", "total_value", "annual_value"),
    unconfirmed=("club_uid", "club_name", "type", "unknown"),
)
