"""fmsave: read Football Manager 26 save files."""

from fmsave._errors import (
    AmbiguousNameError,
    CorruptSaveError,
    FmsaveError,
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
from fmsave.models.clubs import Club, Team
from fmsave.models.common import CodedValue, ContractEndSource
from fmsave.models.contracts import (
    Clause,
    ClauseKind,
    Contract,
    ContractChainEntry,
    ContractType,
    SquadStatus,
)
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
from fmsave.models.suspensions import PlayerSuspension, Suspension
from fmsave.table import Table

OUTPUT_SCHEMA_VERSION = 1

__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "Ability",
    "AmbiguousNameError",
    "Attributes",
    "Clause",
    "ClauseKind",
    "Club",
    "CodedValue",
    "Contract",
    "ContractChainEntry",
    "ContractEndSource",
    "ContractType",
    "CorruptSaveError",
    "FmsaveError",
    "NotAFmSaveError",
    "Personality",
    "Player",
    "PlayerSuspension",
    "Positions",
    "ReaderCheckError",
    "Reputation",
    "Save",
    "SaveChangedError",
    "SaveClosedError",
    "SaveInfo",
    "SectionInfo",
    "SquadStatus",
    "Suspension",
    "Table",
    "Team",
    "Trait",
    "UnknownBuildWarning",
    "UnsupportedGameError",
    "__version__",
    "field_status",
    "open",
]
