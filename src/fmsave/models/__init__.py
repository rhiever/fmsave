"""Public record types."""

from fmsave.models.affiliates import AffiliateGroup
from fmsave.models.clubs import Club, Team
from fmsave.models.common import CodedValue, ContractEndSource, TransferValueState
from fmsave.models.competitions import Competition, CompetitionRound, Stage
from fmsave.models.contracts import (
    Clause,
    ClauseKind,
    Contract,
    ContractChainEntry,
    ContractType,
    SquadStatus,
)
from fmsave.models.facilities import ClubFacilities, CorporateFacilities
from fmsave.models.finances import FinanceMonth, Sponsorship, SponsorType
from fmsave.models.fixtures import Fixture
from fmsave.models.injuries import (
    InjuryCause,
    InjuryRecord,
    InjuryRecordKind,
    InjurySeverity,
    InjuryType,
)
from fmsave.models.jobs import JobVacancy
from fmsave.models.league_tables import (
    LeagueTable,
    LeagueTableMatch,
    LeagueTableRow,
    LeagueTableSplit,
    MatchOutcome,
    Venue,
)
from fmsave.models.managed import ManagedClub
from fmsave.models.matches import MatchPosition, PlayerMatchStats
from fmsave.models.meta import SaveInfo, SectionInfo
from fmsave.models.players import (
    Ability,
    Attributes,
    Personality,
    Player,
    Positions,
    Reputation,
    Trait,
)
from fmsave.models.rules import (
    CompetitionRules,
    RulesBlockKind,
    RulesRound,
    TransferWindow,
)
from fmsave.models.stadiums import Stadium
from fmsave.models.staff import Staff, StaffAttributes, StaffList, StaffPreferences
from fmsave.models.suspensions import PlayerSuspension, Suspension, SuspensionScope
from fmsave.models.tactics import (
    Mentality,
    SetPieceRoutine,
    Tactic,
    TacticPosition,
    TacticSettingUnit,
    TacticSlot,
)
from fmsave.models.training import (
    MentoringGroup,
    TeamTraining,
    TrainingSchedule,
    TrainingWeek,
)

__all__ = [
    "Ability",
    "AffiliateGroup",
    "Attributes",
    "Clause",
    "ClauseKind",
    "Club",
    "ClubFacilities",
    "CodedValue",
    "Competition",
    "CompetitionRound",
    "CompetitionRules",
    "Contract",
    "ContractChainEntry",
    "ContractEndSource",
    "ContractType",
    "CorporateFacilities",
    "FinanceMonth",
    "Fixture",
    "InjuryCause",
    "InjuryRecord",
    "InjuryRecordKind",
    "InjurySeverity",
    "InjuryType",
    "JobVacancy",
    "LeagueTable",
    "LeagueTableMatch",
    "LeagueTableRow",
    "LeagueTableSplit",
    "ManagedClub",
    "MatchOutcome",
    "MatchPosition",
    "Mentality",
    "MentoringGroup",
    "Personality",
    "Player",
    "PlayerMatchStats",
    "PlayerSuspension",
    "Positions",
    "Reputation",
    "RulesBlockKind",
    "RulesRound",
    "SaveInfo",
    "SectionInfo",
    "SetPieceRoutine",
    "SponsorType",
    "Sponsorship",
    "SquadStatus",
    "Stadium",
    "Staff",
    "StaffAttributes",
    "StaffList",
    "StaffPreferences",
    "Stage",
    "Suspension",
    "SuspensionScope",
    "Tactic",
    "TacticPosition",
    "TacticSettingUnit",
    "TacticSlot",
    "Team",
    "TeamTraining",
    "TrainingSchedule",
    "TrainingWeek",
    "Trait",
    "TransferValueState",
    "TransferWindow",
    "Venue",
]
