"""The user-supplied map from a competition's editor database id to its name.

No save holds a competition name: the game renders them from its own installed database. fmsave
therefore ships no names, reads no game install and makes no network call. What it does ship is
`Competition.database_id`, the competition's id in the game's editor database, which is the same
value in every save and is what every name source outside a save is keyed on. A reader who wants
names builds a map from that id once and passes it to `fmsave.open`, where it names competitions
in every save they own.

The map is keyed on the **database** id and never on the stage-space competition id, which
differs between saves and between databases.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from fmsave._frozen import FrozenMapping

__all__ = ["normalize_competition_names", "read_competition_names"]

DATABASE_ID_COLUMN = 0
NAME_COLUMN = 1
EXPECTED_COLUMNS = 2

# What an error calls a path with no file name of its own, which no readable file has.
UNNAMED_FILE = "the given file"

# The map of a save opened without one, shared because it is immutable and always empty.
EMPTY_COMPETITION_NAMES: FrozenMapping[int, str] = FrozenMapping({})


def _error_file_name(path: str | os.PathLike[str]) -> str:
    """The file's own name, never the folder holding it.

    An error a reader pastes into a bug report must not carry any part of their directory
    layout. This is the rule `fmsave.cli.error_file_name` applies to the paths an OSError
    reports, repeated here so this module stays independent of the command line.
    """
    return Path(os.fspath(path)).name or UNNAMED_FILE


def _is_blank(row: list[str]) -> bool:
    """Whether a row holds nothing: an empty line, or one of nothing but separators and spaces."""
    return all(not cell.strip() for cell in row)


def _parsed_database_id(cell: str) -> int | None:
    """The cell as a database id, or None when it is not a whole number."""
    try:
        return int(cell)
    except ValueError:
        return None


def read_competition_names(path: str | os.PathLike[str]) -> dict[int, str]:
    """Read a two-column UTF-8 CSV of `database_id,name` into a competition name map.

    The first column is the competition's editor database id, which is what
    `Competition.database_id` carries. A first row whose first cell is not a whole number is
    taken for a header and skipped. Blank lines are skipped, and surrounding whitespace is
    stripped from both cells.

    One id may be listed twice with the same name. Two different names for one id are a
    contradiction and raise, because neither is more likely to be the one meant.

    Every error names the file and never the folder holding it, so a message a reader pastes
    into a bug report carries no part of their directory layout.

    Raises:
        OSError: The file cannot be opened or read. It is left to the caller, which knows the
            path it passed.
        ValueError: A row has other than two columns, an id is not a whole number, a name is
            empty, or one id is listed twice under two names.
    """
    file_name = _error_file_name(path)
    names: dict[int, str] = {}
    with open(path, encoding="utf-8", newline="") as name_file:
        rows = csv.reader(name_file)
        header_row_allowed = True
        for row in rows:
            # line_num counts physical lines, so a quoted name holding a newline still points
            # at the line the row started on.
            line_number = rows.line_num
            if _is_blank(row):
                continue
            first_cell = row[DATABASE_ID_COLUMN].strip()
            if header_row_allowed:
                header_row_allowed = False
                if _parsed_database_id(first_cell) is None:
                    continue
            if len(row) != EXPECTED_COLUMNS:
                raise ValueError(
                    f"{file_name} line {line_number}: expected {EXPECTED_COLUMNS} columns, "
                    f"found {len(row)}"
                )
            database_id = _parsed_database_id(first_cell)
            if database_id is None:
                raise ValueError(
                    f"{file_name} line {line_number}: {first_cell!r} is not a competition "
                    "database id"
                )
            name = row[NAME_COLUMN].strip()
            if not name:
                raise ValueError(f"{file_name} line {line_number}: the name is empty")
            listed_name = names.get(database_id)
            if listed_name is not None and listed_name != name:
                raise ValueError(
                    f"{file_name} line {line_number}: database id {database_id} is listed twice"
                )
            names[database_id] = name
    return names


def normalize_competition_names(
    names: Mapping[int, str] | str | os.PathLike[str] | None,
) -> FrozenMapping[int, str]:
    """Turn whatever `fmsave.open` was given into one immutable map keyed on the database id.

    None gives an empty map, a path is read through `read_competition_names`, and a mapping is
    copied and checked. A name from a mapping is stored as it was given; a name read from a CSV
    has its surrounding whitespace stripped.

    Raises:
        OSError: A path was given and the file cannot be opened or read.
        TypeError: A key is not an int, or a name is not a str.
        ValueError: A name is empty, or a CSV was given and is malformed (see
            `read_competition_names`).
    """
    if names is None:
        return EMPTY_COMPETITION_NAMES
    if isinstance(names, (str, os.PathLike)):
        return FrozenMapping(read_competition_names(names))
    checked_names: dict[int, str] = {}
    # The declared type says what a caller should pass; these checks are what happens when one
    # passes something else, so the items are read back as plain objects to check them at all.
    for database_id, name in cast("Mapping[object, object]", names).items():
        if not isinstance(database_id, int) or isinstance(database_id, bool):
            raise TypeError(f"competition name key {database_id!r} is not a database id")
        if not isinstance(name, str):
            raise TypeError(f"the competition name for database id {database_id} is not a string")
        if not name:
            raise ValueError(f"the competition name for database id {database_id} is empty")
        checked_names[database_id] = name
    return FrozenMapping(checked_names)
