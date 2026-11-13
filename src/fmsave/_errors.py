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

    report_reason: str | None = None


class SaveChangedError(FmsaveError):
    """The save file changed on disk after it was opened."""


class SaveClosedError(FmsaveError):
    """A reader was called on a closed save."""


class AmbiguousNameError(FmsaveError):
    """A name matched more than one record where exactly one was needed."""


class FmsaveWarning(UserWarning):
    """Base class for every warning fmsave issues on purpose."""


class UnknownBuildWarning(FmsaveWarning):
    """The save comes from an FM26 build fmsave has no full set of layout tables for, or from
    FM27, which fmsave reads only in part. For an FM27 build with no layouts registered, the
    message also explains how fmsave tries registered FM27 layouts."""


class ReaderCheckWarning(FmsaveWarning):
    """A reader's measured checks failed and it handed its table back anyway.

    Advisory checks warn in either mode. Failed blocking checks warn when the save is opened
    without `strict=True`. Structural failures raise `ReaderCheckError`.
    """
