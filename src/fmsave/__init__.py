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
from fmsave.models.meta import SaveInfo, SectionInfo

OUTPUT_SCHEMA_VERSION = 1

__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "AmbiguousNameError",
    "CorruptSaveError",
    "FmsaveError",
    "NotAFmSaveError",
    "ReaderCheckError",
    "Save",
    "SaveChangedError",
    "SaveClosedError",
    "SaveInfo",
    "SectionInfo",
    "UnknownBuildWarning",
    "UnsupportedGameError",
    "__version__",
    "open",
]
