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

OUTPUT_SCHEMA_VERSION = 1

__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "AmbiguousNameError",
    "CorruptSaveError",
    "FmsaveError",
    "NotAFmSaveError",
    "ReaderCheckError",
    "SaveChangedError",
    "SaveClosedError",
    "UnknownBuildWarning",
    "UnsupportedGameError",
    "__version__",
]
