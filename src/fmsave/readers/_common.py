"""Values and error-context helpers shared by the readers."""

from __future__ import annotations

from fmsave._errors import ISSUES_URL, ReaderCheckError

# The value the save stores in a u32 id or index field that refers to nothing.
MISSING_REFERENCE = 0xFFFFFFFF

# The one section every game_db reader (names, clubs, players) works from.
GAME_DB_SECTION = "game_db"


def section_label(file_name: str, section_name: str = GAME_DB_SECTION) -> str:
    """ "<file name>: section '<section name>'", the common prefix of a reader's error text."""
    return f"{file_name}: section {section_name!r}"


def layout_mismatch(
    file_name: str, detail: str, section_name: str = GAME_DB_SECTION
) -> ReaderCheckError:
    """A ReaderCheckError saying the save layout differs from what fmsave expects."""
    return ReaderCheckError(
        f"{section_label(file_name, section_name)}: {detail}, so the save layout differs from "
        f"what fmsave expects. Please report it at {ISSUES_URL}"
    )
