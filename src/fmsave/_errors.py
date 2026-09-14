"""Exceptions and warnings raised by fmsave."""

ISSUES_URL = "https://github.com/rhiever/fmsave/issues"


class FmsaveError(Exception):
    """Base class for every error fmsave raises on purpose."""


class NotAFmSaveError(FmsaveError):
    """The file is not a Football Manager save."""


class CorruptSaveError(FmsaveError):
    """The save is damaged, truncated, or was being written while it was read."""


class UnsupportedGameError(FmsaveError):
    """The save comes from a Football Manager version fmsave cannot read."""


class ReaderCheckError(FmsaveError):
    """A reader's checks failed, so its output would not be trustworthy."""


class SaveChangedError(FmsaveError):
    """The save file changed on disk after it was opened."""


class SaveClosedError(FmsaveError):
    """A reader was called on a closed save."""


class AmbiguousNameError(FmsaveError):
    """A name matched more than one record where exactly one was needed."""


class UnknownBuildWarning(UserWarning):
    """The save comes from an FM26 build fmsave has no layout tables for."""
