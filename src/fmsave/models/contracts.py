"""Contract records: the chain of registrations, its tail fields and clauses.

A player's contract is assembled from a chain of registration records (one per club a
player has been registered to, oldest first), each carrying a wage and a start date, and
some of them a parsed "tail" of further fields (an end date, squad status, contract type
and clauses). When no chain record's tail parses, a separate fallback reader inside the
player's record can still supply a start or an end date. See `readers/contracts.py` for the
assembly rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue, ContractEndSource


class SquadStatus(IntEnum):
    """A player's squad-status code, as shown on the contract screen."""

    UNKNOWN = -1
    STAR_PLAYER = 1
    IMPORTANT_PLAYER = 2
    REGULAR_STARTER = 3
    SQUAD_PLAYER = 4
    IMPACT_SUB = 5
    FRINGE_PLAYER = 7
    BREAKTHROUGH_PROSPECT = 10
    FUTURE_PROSPECT = 11
    YOUNGSTER = 13
    CUP_GOALKEEPER = 16
    BACKUP = 20


class ContractType(IntEnum):
    """A player's contract type code."""

    UNKNOWN = -1
    FULL_TIME = 1
    YOUTH = 3


class ClauseKind(IntEnum):
    """A contract clause's kind.

    Only kinds whose meaning is confirmed are named; every other code is UNKNOWN and keeps its
    raw number. Each code is a distinct kind: MINIMUM_FEE_RELEASE_DOMESTIC is code 0x12 only.

    A clause's value is the release fee for MINIMUM_FEE_RELEASE, MINIMUM_FEE_RELEASE_FOREIGN
    and MINIMUM_FEE_RELEASE_DOMESTIC, and the amount paid for APPEARANCE_FEE, SHUTOUT_BONUS,
    INTERNATIONAL_CAP_BONUS, UNUSED_SUBSTITUTE_FEE and
    SEASONAL_LANDMARK_COMBINED_GOALS_AND_ASSISTS. A clause's parameter is a percentage for
    TOP_DIVISION_RELEGATION_SALARY_DROP, years for OPTIONAL_EXTENSION_BY_CLUB, the number of
    goals plus assists that earns the bonus for SEASONAL_LANDMARK_COMBINED_GOALS_AND_ASSISTS,
    and days to expiry from the contract start for MINIMUM_FEE_RELEASE_DOMESTIC (None means no
    expiry). RELEGATION_RELEASE and NON_PROMOTION_RELEASE carry no parameter meaning.
    """

    UNKNOWN = -1
    MINIMUM_FEE_RELEASE = 0x00
    RELEGATION_RELEASE = 0x01
    NON_PROMOTION_RELEASE = 0x02
    TOP_DIVISION_RELEGATION_SALARY_DROP = 0x0F
    MINIMUM_FEE_RELEASE_FOREIGN = 0x10
    MINIMUM_FEE_RELEASE_DOMESTIC = 0x12
    OPTIONAL_EXTENSION_BY_CLUB = 0x16
    APPEARANCE_FEE = 0x20
    SHUTOUT_BONUS = 0x22
    INTERNATIONAL_CAP_BONUS = 0x25
    UNUSED_SUBSTITUTE_FEE = 0x26
    SEASONAL_LANDMARK_COMBINED_GOALS_AND_ASSISTS = 0x29


@dataclass(frozen=True, slots=True)
class Clause:
    """One clause attached to a contract, such as a release fee, an extension option or a bonus.

    Attributes:
        kind: The clause's kind.
        parameter: The clause's parameter, whose meaning depends on kind; None when the
            save stores no parameter.
        value: The clause's money value; None when the save stores no value.
    """

    kind: CodedValue[ClauseKind]
    parameter: int | None
    value: int | None


@dataclass(frozen=True, slots=True)
class ContractChainEntry:
    """One record in a player's registration chain.

    Attributes:
        club_uid: Uid of the contracting club, or None when the team does not resolve
            (unconfirmed).
        club_name: Denormalised name of club_uid (unconfirmed).
        team_id: Id of the contracting team, exactly as stored (unconfirmed).
        wage: Weekly wage, in the save's base currency (unconfirmed).
        start: Start date of this spell (unconfirmed).
        end: End date from this record's tail, or None when its tail did not parse or
            stores no end (unconfirmed).
        has_tail: Whether this record's tail parsed (unconfirmed).
    """

    club_uid: int | None
    club_name: str | None
    team_id: int
    wage: int
    start: date | None
    end: date | None
    has_tail: bool


@dataclass(frozen=True, slots=True)
class Contract:
    """A player's assembled contract.

    Attributes:
        player_uid: Uid of the player this contract belongs to (unconfirmed).
        player_name: Denormalised name of player_uid (unconfirmed).
        club_uid: Uid of the contracting club of the live chain record, or None
            (unconfirmed).
        club_name: Denormalised name of club_uid (unconfirmed).
        team_id: Id of the contracting team of the live chain record, or None
            (unconfirmed).
        wage: Weekly wage from the first chain record, in the save's base currency
            (unconfirmed).
        start: Contract start date.
        end: Contract end date.
        end_source: Where end was read from.
        squad_status: Squad status from the live chain record's tail, or None when it has
            no parsed tail.
        type: Contract type from the live chain record's tail, or None when it has no
            parsed tail.
        clauses: Clauses from the live chain record's tail, or () when it has no parsed
            tail.
        on_loan: Whether the player is on loan: True or False when both the player's team
            and the first chain record's team resolve to clubs, else None.
        loan_parent_club_uid: Uid of the loaning-out club when on_loan is True, else None.
        loan_parent_club_name: Denormalised name of loan_parent_club_uid.
        event_count: Contract event count from the live chain record's tail, or None
            (unconfirmed).
        chain: Every chain record, oldest first (unconfirmed).
        chain_club_uids: Uid of the contracting club for each chain record, in the same
            order as chain; None where the team does not resolve (unconfirmed).
        chain_club_names: Denormalised names for chain_club_uids, in the same order
            (unconfirmed).
        tailed_chain_club_uids: Uids of the clubs of chain records whose tail parsed and
            whose team resolves, in chain order (unconfirmed).
        unknown: Numeric fields with no known meaning, from the live chain record's tail;
            a key is present only when its value was read (unconfirmed).
    """

    player_uid: int
    player_name: str | None
    club_uid: int | None
    club_name: str | None
    team_id: int | None
    wage: int | None
    start: date | None
    end: date | None
    end_source: ContractEndSource
    squad_status: CodedValue[SquadStatus] | None
    type: CodedValue[ContractType] | None
    clauses: tuple[Clause, ...]
    on_loan: bool | None
    loan_parent_club_uid: int | None
    loan_parent_club_name: str | None
    event_count: int | None
    chain: tuple[ContractChainEntry, ...]
    chain_club_uids: tuple[int | None, ...]
    chain_club_names: tuple[str | None, ...]
    tailed_chain_club_uids: tuple[int, ...]
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = (
        "money_a",
        "money_b",
        "money_c",
        "e2",
        "e8",
        "e12",
        "e16",
        "e20",
        "e24",
        "e37",
        "e38",
        "e39",
    )


register_field_statuses(
    Clause,
    verified=("kind", "parameter", "value"),
)
register_field_statuses(
    ContractChainEntry,
    unconfirmed=("club_uid", "club_name", "team_id", "wage", "start", "end", "has_tail"),
)
register_field_statuses(
    Contract,
    verified=(
        "start",
        "end",
        "end_source",
        "squad_status",
        "type",
        "clauses",
        "on_loan",
        "loan_parent_club_uid",
        "loan_parent_club_name",
    ),
    unconfirmed=(
        "player_uid",
        "player_name",
        "club_uid",
        "club_name",
        "team_id",
        "wage",
        "event_count",
        "chain",
        "chain_club_uids",
        "chain_club_names",
        "tailed_chain_club_uids",
        "unknown",
    ),
)
