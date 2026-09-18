"""fmsave: read Football Manager 26 save files."""

from fmsave._errors import (
    AmbiguousNameError,
    CorruptSaveError,
    FmsaveError,
    FmsaveWarning,
    NotAFmSaveError,
    ReaderCheckError,
    SaveChangedError,
    SaveClosedError,
    UnknownBuildWarning,
    UnsupportedGameError,
)
from fmsave._package import __version__
from fmsave._save import Save
from fmsave._save import open_save as open
from fmsave._status import field_status
from fmsave.checks import GateResult, ReaderValidation, ValidationReport, validate_save
from fmsave.models.affiliates import AffiliateGroup
from fmsave.models.clubs import Club, Team
from fmsave.models.common import CodedValue, ContractEndSource
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
from fmsave.models.suspensions import PlayerSuspension, Suspension
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
from fmsave.name_maps import read_competition_names
from fmsave.table import Table

OUTPUT_SCHEMA_VERSION = 1

__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "Ability",
    "AffiliateGroup",
    "AmbiguousNameError",
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
    "CorruptSaveError",
    "FinanceMonth",
    "Fixture",
    "FmsaveError",
    "FmsaveWarning",
    "GateResult",
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
    "NotAFmSaveError",
    "Personality",
    "Player",
    "PlayerMatchStats",
    "PlayerSuspension",
    "Positions",
    "ReaderCheckError",
    "ReaderValidation",
    "Reputation",
    "RulesBlockKind",
    "RulesRound",
    "Save",
    "SaveChangedError",
    "SaveClosedError",
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
    "Table",
    "Tactic",
    "TacticPosition",
    "TacticSettingUnit",
    "TacticSlot",
    "Team",
    "TeamTraining",
    "TrainingSchedule",
    "TrainingWeek",
    "Trait",
    "TransferWindow",
    "UnknownBuildWarning",
    "UnsupportedGameError",
    "ValidationReport",
    "Venue",
    "__version__",
    "field_status",
    "open",
    "read_competition_names",
    "validate_save",
]
