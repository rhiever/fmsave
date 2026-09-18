"""fmsave: read Football Manager 26 save files."""

from fmsave._errors import (
    AmbiguousNameError,
    CorruptSaveError,
    FmsaveError,
    FmsaveWarning,
    NotAFmSaveError,
    ReaderCheckError,
    ReaderCheckWarning,
    SaveChangedError,
    SaveClosedError,
    UnknownBuildWarning,
    UnsupportedGameError,
)
from fmsave._package import __version__
from fmsave._save import Save
from fmsave._save import open_save as open
from fmsave._status import FieldStatus, field_status
from fmsave.checks import (
    GateCheckError,
    GateResult,
    ReaderCheck,
    ReaderStatus,
    ReaderValidation,
    ValidationReport,
    validate_save,
)
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
    MatchSide,
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
from fmsave.name_maps import read_competition_names
from fmsave.table import Table

OUTPUT_SCHEMA_VERSION = 2

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
    "FieldStatus",
    "FinanceMonth",
    "Fixture",
    "FmsaveError",
    "FmsaveWarning",
    "GateCheckError",
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
    "MatchSide",
    "Mentality",
    "MentoringGroup",
    "NotAFmSaveError",
    "Personality",
    "Player",
    "PlayerMatchStats",
    "PlayerSuspension",
    "Positions",
    "ReaderCheck",
    "ReaderCheckError",
    "ReaderCheckWarning",
    "ReaderStatus",
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
    "SuspensionScope",
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
    "TransferValueState",
    "TransferWindow",
    "UnknownBuildWarning",
    "UnsupportedGameError",
    "ValidationReport",
    "__version__",
    "field_status",
    "open",
    "read_competition_names",
    "validate_save",
]
