"""Command line interface for fmsave.

`main` runs one command line and returns its exit code, which is what `python -m fmsave` and
the `fmsave` script do. The exit codes are named here so that a caller who runs `main` itself
can compare against them rather than against bare numbers.

Only the names in __all__ are public: the commands, their parsing, their messages and their
output are fmsave's to change, and none of them is part of the library's API.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import io
import json
import os
import sys
import unicodedata
import warnings
from collections.abc import Callable, Generator, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import NoReturn, TextIO

import fmsave
from fmsave import export
from fmsave._errors import (
    ISSUES_URL,
    AmbiguousNameError,
    FmsaveError,
    FmsaveWarning,
    NotAFmSaveError,
    ReaderCheckError,
    UnsupportedGameError,
)
from fmsave._package import __version__
from fmsave.checks import ValidationReport, validate_save
from fmsave.models.affiliates import AffiliateGroup
from fmsave.models.clubs import Club
from fmsave.models.competitions import Competition, Stage
from fmsave.models.contracts import Contract
from fmsave.models.facilities import ClubFacilities
from fmsave.models.finances import FinanceMonth, Sponsorship
from fmsave.models.fixtures import Fixture
from fmsave.models.injuries import InjuryRecord, InjuryType
from fmsave.models.jobs import JobVacancy
from fmsave.models.league_tables import LeagueTable
from fmsave.models.managed import ManagedClub
from fmsave.models.matches import PlayerMatchStats
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.models.rules import CompetitionRules, TransferWindow
from fmsave.models.stadiums import Stadium
from fmsave.models.staff import Staff, StaffList
from fmsave.models.suspensions import Suspension
from fmsave.models.tactics import SetPieceRoutine, Tactic
from fmsave.models.training import MentoringGroup, TeamTraining
from fmsave.table import Table

__all__ = ["EXIT_OK", "EXIT_UNEXPECTED", "EXIT_UNSUPPORTED", "EXIT_USAGE", "main"]

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3

_UNNAMED_PATH = "the given path"
_PATH_SEPARATORS = "/\\"
_UNNAMED_PATH_ARGUMENT = "path"
_GENERIC_USAGE_MESSAGE = "invalid arguments; run 'fmsave --help' for usage"

_OUTPUT_FORMATS = ("csv", "json", "jsonl")
_NATION_NAME_MESSAGE = "no save stores a nation name and fmsave ships none; pass a nation id"
_NO_MANAGED_CLUB_MESSAGE = "no managed club found in this save"
_NO_COMPETITION_NAMES_MESSAGE = (
    "competition names come from --competition-names, and the save stores none"
)
_COMPETITION_RULES_NOTE = (
    "a rules block's competition is read from the table stored after it, so --competition "
    "returns only the blocks that link to one"
)
_MANAGED_CLUB_ONLY_NOTE = "only the manager's own club has these, so any other club returns no rows"

_CLUB_SCOPE = "club"
_MANAGED_CLUB_SCOPE = "managed-club"
_COMPETITION_SCOPE = "competition"
_NATION_SCOPE = "nation"
_EVERY_ROW_SCOPE = "all"
# Every scope, in the order messages and the help text list them, with the option asking for it.
_SCOPE_OPTIONS: dict[str, str] = {
    _CLUB_SCOPE: "--club",
    _MANAGED_CLUB_SCOPE: "--managed-club",
    _COMPETITION_SCOPE: "--competition",
    _NATION_SCOPE: "--nation",
    _EVERY_ROW_SCOPE: "--all",
}
# What a message calls each scope it turns down. Every row is never turned down, so it has none.
_SCOPE_WORDS: dict[str, str] = {
    _CLUB_SCOPE: "club",
    _MANAGED_CLUB_SCOPE: "managed club",
    _COMPETITION_SCOPE: "competition",
    _NATION_SCOPE: "nation",
}


def _error_file_name(filename: object) -> str:
    """Return the file name, without its folder, of the path an OSError reports."""
    file_name = Path(str(filename)).name if filename else ""
    return file_name or _UNNAMED_PATH


def _is_path_like(argument_text: str) -> bool:
    """Whether an argument contains a path separator and is not made only of separators."""
    has_separator = any(separator in argument_text for separator in _PATH_SEPARATORS)
    return has_separator and argument_text.strip(_PATH_SEPARATORS) != ""


def _is_glued_short_option(argument_token: str) -> bool:
    """Whether an argument is a short option with its value attached, such as "-oPATH"."""
    return (
        len(argument_token) > 2
        and argument_token[0] == "-"
        and argument_token[1] not in "-" + _PATH_SEPARATORS
    )


def _redact_argument(argument_token: str) -> str:
    """Reduce a path-like argument to its last component, keeping any "--flag=" before the path.

    Text up to an "=" is kept only when the argument starts with "-", so a folder name that
    contains "=" is removed with the rest of the folder. A short option with its value attached,
    such as "-oPATH", keeps the option and any "-" or "=" that starts the value, and has the
    rest of the value reduced. The last component splits on both / and \\ on every system.
    """
    if not _is_path_like(argument_token):
        return argument_token
    if _is_glued_short_option(argument_token):
        attached_value = argument_token[2:]
        value_marker_length = len(attached_value) - len(attached_value.lstrip("-="))
        kept_text = argument_token[: 2 + value_marker_length]
        return kept_text + _redact_argument(attached_value[value_marker_length:])
    kept_prefix_length = 0
    if argument_token.startswith("-"):
        separator_indexes = [argument_token.find(separator) for separator in _PATH_SEPARATORS]
        first_separator_index = min(index for index in separator_indexes if index >= 0)
        kept_prefix_length = argument_token.find("=", 0, first_separator_index) + 1
    path_name = PureWindowsPath(argument_token[kept_prefix_length:]).name
    return argument_token[:kept_prefix_length] + (path_name or _UNNAMED_PATH_ARGUMENT)


def _argument_folder_texts(argument_tokens: Sequence[str]) -> list[str]:
    """Return the text before the last separator of each path-like argument that names a folder.

    Trailing separators are ignored, so "extra/" names no folder. The value of a short option
    with its value attached is checked on its own as well.
    """
    candidate_texts: list[str] = []
    for argument_token in argument_tokens:
        candidate_texts.append(argument_token)
        if _is_glued_short_option(argument_token):
            candidate_texts.append(argument_token[2:])
    folder_texts: list[str] = []
    for candidate_text in candidate_texts:
        if not _is_path_like(candidate_text):
            continue
        trimmed_text = candidate_text.rstrip(_PATH_SEPARATORS)
        last_separator_index = max(trimmed_text.rfind(separator) for separator in _PATH_SEPARATORS)
        if last_separator_index < 0:
            continue
        folder_text = trimmed_text[:last_separator_index]
        if len(folder_text) >= 2 and folder_text.strip(_PATH_SEPARATORS):
            folder_texts.append(folder_text)
    return folder_texts


class _UsageError(Exception):
    """A usage error the argument parser raises instead of printing it and exiting."""

    def __init__(self, parser: _CommandLineParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser
        self.message = message


class _CommandUsageError(Exception):
    """Arguments that parse but ask for something the save cannot give, such as an unknown club."""


class _OutputWriteError(Exception):
    """Opening, writing or flushing the command's output failed.

    Attributes:
        write_error: The OSError the output raised.
        to_standard_output: Whether the output was standard output rather than a file.
        while_opening: Whether the output file failed to open, before anything was written.
    """

    def __init__(
        self, write_error: OSError, *, to_standard_output: bool, while_opening: bool = False
    ) -> None:
        super().__init__(write_error.strerror or type(write_error).__name__)
        self.write_error = write_error
        self.to_standard_output = to_standard_output
        self.while_opening = while_opening


class _CommandLineParser(argparse.ArgumentParser):
    """Argument parser that raises _UsageError rather than printing a usage error."""

    def error(self, message: str) -> NoReturn:
        raise _UsageError(self, message)

    def exit_with_usage_error(self, message: str) -> NoReturn:
        """Print this parser's usage line and the message as argparse does, then exit with 2."""
        super().error(message)


def _add_save_argument(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("save_path", metavar="SAVE", help="path to a .fm save file")


def _table_argument_help() -> str:
    """The tables to choose from, and the note each of them carries about its own scopes.

    A note belongs to the tables it is true of and is printed beside each of their names. On
    the shared --club or --competition help it would tell every table what is true of a few of
    them.
    """
    table_notes = [
        f"{table_name} ({export_table.note})"
        for table_name, export_table in _EXPORT_TABLES.items()
        if export_table.note
    ]
    listed_tables = ", ".join(_EXPORT_TABLES)
    noted_tables = f"; {'; '.join(table_notes)}" if table_notes else ""
    return f"the table to write: {listed_tables}{noted_tables}"


def _build_parser() -> _CommandLineParser:
    parser = _CommandLineParser(
        prog="fmsave",
        description="Read Football Manager 26 save files. fmsave never modifies a save.",
    )
    parser.add_argument("--version", action="version", version=f"fmsave {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    info_parser = subcommands.add_parser(
        "info",
        help="show the game, build and in-game date of a save",
        description="Show save metadata.",
    )
    _add_save_argument(info_parser)
    info_parser.add_argument(
        "--show-name",
        action="store_true",
        help="include the save's name, and with --json the save summary texts, which hold "
        "names (hidden by default)",
    )
    info_parser.add_argument("--json", action="store_true", help="print JSON instead of text")

    export_parser = subcommands.add_parser(
        "export",
        help="write one table of a save as CSV, JSON or JSON Lines",
        description="Write one table of a save. Choose exactly one scope: --club, "
        "--managed-club, --competition, --nation or --all.",
    )
    _add_save_argument(export_parser)
    export_parser.add_argument(
        "table",
        metavar="TABLE",
        choices=tuple(_EXPORT_TABLES),
        help=_table_argument_help(),
    )
    scope_group = export_parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument(
        "--club",
        metavar="VALUE",
        help="rows of one club, given as a club uid or a club name or short name (any case)",
    )
    scope_group.add_argument(
        "--managed-club", action="store_true", help="rows of the club the human manager runs"
    )
    scope_group.add_argument(
        "--competition",
        metavar="VALUE",
        help="rows of one competition, given as a competition id, or as a name once "
        "--competition-names supplies one",
    )
    scope_group.add_argument("--nation", metavar="VALUE", help="rows of one nation, by nation id")
    scope_group.add_argument("--all", action="store_true", help="every row")
    export_parser.add_argument(
        "--format", choices=_OUTPUT_FORMATS, default="csv", help="output format (default: csv)"
    )
    export_parser.add_argument(
        "--columns",
        metavar="NAMES",
        help="comma-separated flat column names to write, in this order",
    )
    export_parser.add_argument(
        "--competition-names",
        metavar="PATH",
        help="a UTF-8 CSV of database_id,name naming competitions, which no save stores",
    )
    export_parser.add_argument(
        "-o", "--output", metavar="PATH", help="write to this file instead of standard output"
    )
    export_parser.add_argument(
        "--strict",
        action="store_true",
        help="stop rather than write when a reader's checks fail (they warn by default)",
    )

    validate_parser = subcommands.add_parser(
        "validate",
        help="report how each reader fares on a save, without any names or uids",
        description="Run every reader and report its checks, counts and coverage. The report "
        "holds no names, uids or text from the save.",
    )
    _add_save_argument(validate_parser)
    validate_parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser


def _redacted_usage_error(argument_tokens: Sequence[str]) -> tuple[_CommandLineParser, str]:
    """Return the parser and message to show for arguments the parser rejected.

    Usage errors quote only parser vocabulary and argument text, so the message comes from parsing
    the arguments again with every path reduced to its last component. When that parse does not
    fail, or its message still shows a folder, a generic message is used instead.
    """
    parser = _build_parser()
    redacted_tokens = [_redact_argument(argument_token) for argument_token in argument_tokens]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(redacted_tokens)
    except _UsageError as usage_error:
        folder_texts = _argument_folder_texts(argument_tokens)
        if not any(folder_text in usage_error.message for folder_text in folder_texts):
            return usage_error.parser, usage_error.message
    except SystemExit:
        pass  # The redacted arguments asked for help or the version.
    return parser, _GENERIC_USAGE_MESSAGE


def _info_record(save_info: SaveInfo, show_name: bool) -> dict[str, object]:
    record: dict[str, object] = {
        "fmsave_version": __version__,
        "game": save_info.game,
        "build": save_info.build,
        "known_build": save_info.known_build,
        "db_version": save_info.db_version,
        "game_date": save_info.game_date.isoformat() if save_info.game_date else None,
        "time_slot": save_info.time_slot,
        "section_count": len(save_info.section_schemas),
        "section_schemas": dict(sorted(save_info.section_schemas.items())),
    }
    if show_name:
        record["save_name"] = save_info.save_name
        record["summary_strings"] = list(save_info.summary_strings)
    return record


def _render_info_text(save_info: SaveInfo, show_name: bool) -> str:
    build_text = save_info.build if save_info.known_build else f"{save_info.build} (unknown build)"
    rows = [
        ("Game", save_info.game),
        ("Build", build_text),
        ("Database", save_info.db_version),
        ("In-game date", save_info.game_date.isoformat() if save_info.game_date else "unreadable"),
        ("Save name", save_info.save_name if show_name else "hidden (use --show-name)"),
        ("Sections", str(len(save_info.section_schemas))),
    ]
    label_width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{label_width}}  {value}" for label, value in rows)


def _run_info(arguments: argparse.Namespace) -> int:
    save_path = Path(arguments.save_path)
    with fmsave.open(save_path) as career_save:
        save_info = career_save.info
    if arguments.json:
        info_text = json.dumps(
            _info_record(save_info, arguments.show_name), indent=2, ensure_ascii=True
        )
    else:
        info_text = _render_info_text(save_info, arguments.show_name)
    with _output_write_errors(to_standard_output=True):
        print(info_text)
    return EXIT_OK


def _is_ascii_digits(text: str) -> bool:
    return text.isascii() and text.isdigit()


def _normalized_name(text: str) -> str:
    """The form Table.find compares names in: NFKC-normalized, casefolded and stripped."""
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _ambiguous_club_message(club_value: str, candidates: Iterable[Club]) -> str:
    candidate_lines = [
        f"  uid {club.uid}  {club.name} ({club.short_name}), nation id {club.nation_id}"
        for club in candidates
    ]
    return "\n".join(
        [
            f'more than one club matches "{_redact_argument(club_value)}":',
            *candidate_lines,
            "no save stores a league name and fmsave ships none, so use the uid to choose one",
        ]
    )


def _resolve_club(clubs: Table[Club], club_value: str) -> Club:
    """Find the one club a --club value names: a uid, else a full name, else a short name.

    Raises:
        _CommandUsageError: No club has the uid or the name.
        AmbiguousNameError: More than one club has the name.
    """
    if _is_ascii_digits(club_value):
        club_uid = int(club_value)
        uid_match = clubs.get_by_uid(club_uid)
        if uid_match is None:
            raise _CommandUsageError(f"no club with uid {club_uid}")
        return uid_match
    name_matches = clubs.find(name=club_value)
    if not name_matches:
        wanted_name = _normalized_name(club_value)
        name_matches = clubs.filter(lambda club: _normalized_name(club.short_name) == wanted_name)
    if not name_matches:
        raise _CommandUsageError(f'no club named "{_redact_argument(club_value)}"')
    if len(name_matches) > 1:
        raise AmbiguousNameError(_ambiguous_club_message(club_value, name_matches))
    return name_matches[0]


def _ambiguous_competition_message(
    competition_value: str, candidates: Iterable[Competition]
) -> str:
    return "\n".join(
        [
            f'more than one competition matches "{_redact_argument(competition_value)}":',
            *(
                f"  id {competition.id}  {competition.name} (database id {competition.database_id})"
                for competition in candidates
            ),
            "use the id to choose one",
        ]
    )


def _resolve_competition(competitions: Table[Competition], competition_value: str) -> Competition:
    """Find the one competition a --competition value names: an id, else a supplied name.

    A name matches only when the save was opened with a name map, since no save stores a
    competition name of its own.

    Raises:
        _CommandUsageError: No competition has the id or the name.
        AmbiguousNameError: More than one competition has the name.
    """
    if _is_ascii_digits(competition_value):
        competition_id = int(competition_value)
        id_matches = competitions.where(id=competition_id)
        if not id_matches:
            raise _CommandUsageError(f"no competition with id {competition_id}")
        return id_matches[0]
    name_matches = competitions.find(name=competition_value)
    if not name_matches:
        raise _CommandUsageError(
            f'no competition named "{_redact_argument(competition_value)}"; '
            f"{_NO_COMPETITION_NAMES_MESSAGE}"
        )
    if len(name_matches) > 1:
        raise AmbiguousNameError(_ambiguous_competition_message(competition_value, name_matches))
    return name_matches[0]


@dataclass(frozen=True, slots=True)
class _ExportScope:
    """The rows an export keeps: rows of these clubs, this nation, this competition, or every row.

    Attributes:
        club_uids: Keep rows of these clubs, or None to not scope by club.
        nation_id: Keep rows of this nation, or None to not scope by nation.
        competition_id: Keep rows of this competition, or None to not scope by competition.
    """

    club_uids: frozenset[int] | None = None
    nation_id: int | None = None
    competition_id: int | None = None


def _chosen_scope(arguments: argparse.Namespace) -> str:
    """Which scope the arguments ask for; the parser has already required exactly one."""
    if arguments.club is not None:
        return _CLUB_SCOPE
    if arguments.managed_club:
        return _MANAGED_CLUB_SCOPE
    if arguments.competition is not None:
        return _COMPETITION_SCOPE
    if arguments.nation is not None:
        return _NATION_SCOPE
    return _EVERY_ROW_SCOPE


def _scope_offer(scopes: frozenset[str]) -> str:
    """ "use --competition or --all": the scopes a table does take, in the options' own order."""
    options = [_SCOPE_OPTIONS[scope_name] for scope_name in _SCOPE_OPTIONS if scope_name in scopes]
    if len(options) == 1:
        return f"use {options[0]}"
    return f"use {', '.join(options[:-1])} or {options[-1]}"


def _unscoped_message(table_name: str, scope_name: str, table: _ExportTable) -> str:
    """Why a table takes no such scope, which scopes it does take, and any note it carries."""
    table_words = table_name.replace("-", " ")
    note = f" ({table.note})" if table.note else ""
    if table.scopes == _EVERY_ROW_ONLY:
        reason = f"{table_words} are not scoped to a club, competition or nation"
    else:
        reason = f"{table_words} cannot be scoped by {_SCOPE_WORDS[scope_name]}"
    return f"{reason}; {_scope_offer(table.scopes)}{note}"


def _check_scope_arguments(arguments: argparse.Namespace) -> None:
    """Reject a scope the table does not take, or one no save can answer, before it is read.

    Raises:
        _CommandUsageError: The table takes no such scope, or the nation is given as a name.
    """
    table_name: str = arguments.table
    export_table = _EXPORT_TABLES[table_name]
    scope_name = _chosen_scope(arguments)
    if scope_name not in export_table.scopes:
        raise _CommandUsageError(_unscoped_message(table_name, scope_name, export_table))
    if scope_name == _NATION_SCOPE and not _is_ascii_digits(arguments.nation):
        raise _CommandUsageError(_NATION_NAME_MESSAGE)


def _resolve_scope(career_save: fmsave.Save, arguments: argparse.Namespace) -> _ExportScope:
    """Turn the scope arguments into the clubs, nation or competition whose rows are kept.

    Raises:
        _CommandUsageError: The club or competition does not exist, or the save has no managed
            club.
        AmbiguousNameError: More than one club, or more than one competition, has the name.
    """
    if arguments.managed_club:
        managed_club_uids = frozenset(row.club_uid for row in career_save.managed_clubs())
        if not managed_club_uids:
            raise _CommandUsageError(_NO_MANAGED_CLUB_MESSAGE)
        return _ExportScope(club_uids=managed_club_uids)
    if arguments.club is not None:
        club = _resolve_club(career_save.clubs(), arguments.club)
        return _ExportScope(club_uids=frozenset((club.uid,)))
    if arguments.competition is not None:
        competition = _resolve_competition(career_save.competitions(), arguments.competition)
        return _ExportScope(competition_id=competition.id)
    if arguments.nation is not None:
        return _ExportScope(nation_id=int(arguments.nation))
    return _ExportScope()


def _player_filter(scope: _ExportScope) -> Callable[[Player], bool] | None:
    """Whether a player is in the scope, or None when the scope keeps every player."""
    club_uids = scope.club_uids
    if club_uids is not None:
        return lambda player: player.club_uid in club_uids
    nation_id = scope.nation_id
    if nation_id is not None:
        return lambda player: player.nation_id == nation_id
    return None


def _scoped_player_uids(
    career_save: fmsave.Save, keeps_player: Callable[[Player], bool]
) -> set[int]:
    return {player.uid for player in career_save.players() if keeps_player(player)}


def _club_uid_filter(career_save: fmsave.Save, scope: _ExportScope) -> Callable[[int | None], bool]:
    """Whether a club uid is in the scope: one of its clubs, or a club of its nation.

    A club's nation comes from the club table, read through the reader that enforces the club
    checks, so no nation reaches a row from an index whose checks have not run. A row naming no
    club is in no club's scope.
    """
    club_uids = scope.club_uids
    if club_uids is not None:
        return lambda club_uid: club_uid in club_uids
    nation_id = scope.nation_id
    if nation_id is None:
        return lambda club_uid: True
    nation_by_club_uid = {club.uid: club.nation_id for club in career_save.clubs()}
    return lambda club_uid: club_uid is not None and nation_by_club_uid.get(club_uid) == nation_id


def _club_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    clubs = career_save.clubs()
    club_uids = scope.club_uids
    if club_uids is not None:
        return (club for club in clubs if club.uid in club_uids)
    nation_id = scope.nation_id
    if nation_id is not None:
        return (club for club in clubs if club.nation_id == nation_id)
    return clubs


def _managed_club_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    managed_clubs = career_save.managed_clubs()
    club_uids = scope.club_uids
    if club_uids is not None:
        return (row for row in managed_clubs if row.club_uid in club_uids)
    return managed_clubs


def _player_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    players = career_save.players()
    keeps_player = _player_filter(scope)
    return players if keeps_player is None else filter(keeps_player, players)


def _contract_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    contracts = career_save.contracts()
    keeps_player = _player_filter(scope)
    if keeps_player is None:
        return contracts
    player_uids = _scoped_player_uids(career_save, keeps_player)
    return (contract for contract in contracts if contract.player_uid in player_uids)


def _suspension_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    suspensions = career_save.suspensions()
    club_uids = scope.club_uids
    if club_uids is not None:
        return (suspension for suspension in suspensions if suspension.club_uid in club_uids)
    keeps_player = _player_filter(scope)
    if keeps_player is None:
        return suspensions
    player_uids = _scoped_player_uids(career_save, keeps_player)
    return (suspension for suspension in suspensions if suspension.player_uid in player_uids)


def _stage_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    stages = career_save.stages()
    competition_id = scope.competition_id
    if competition_id is None:
        return stages
    return (stage for stage in stages if stage.competition_id == competition_id)


def _competition_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    competitions = career_save.competitions()
    competition_id = scope.competition_id
    if competition_id is None:
        return competitions
    return (competition for competition in competitions if competition.id == competition_id)


def _fixture_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps a match either side of which is in it."""
    fixtures = career_save.fixtures()
    competition_id = scope.competition_id
    if competition_id is not None:
        return (fixture for fixture in fixtures if fixture.competition_id == competition_id)
    if scope.club_uids is None and scope.nation_id is None:
        return fixtures
    keeps_club = _club_uid_filter(career_save, scope)
    return (
        fixture
        for fixture in fixtures
        if keeps_club(fixture.home_club_uid) or keeps_club(fixture.away_club_uid)
    )


def _league_table_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps a whole table holding a row of such a club.

    A table is one record with its rows nested inside it, so there is no half a table to
    write: a scope either keeps the standings a club sits in or it does not.
    """
    league_tables = career_save.league_tables()
    competition_id = scope.competition_id
    if competition_id is not None:
        return (
            league_table
            for league_table in league_tables
            if league_table.competition_id == competition_id
        )
    if scope.club_uids is None and scope.nation_id is None:
        return league_tables
    keeps_club = _club_uid_filter(career_save, scope)
    return (
        league_table
        for league_table in league_tables
        if any(keeps_club(row.club_uid) for row in league_table.rows)
    )


def _transfer_window_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """Every window the save holds. A window belongs to no club, competition or nation fmsave
    can read, so the table takes no scope of its own.
    """
    return career_save.transfer_windows()


def _competition_rules_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """Every rules block, or the blocks whose competition is the one asked for.

    A block's competition comes from the league table the save stores after it, and is empty on
    32% to 45% of rows, so a competition scope writes the blocks that resolved to it and leaves
    the rest out rather than guessing which of them might belong.
    """
    competition_rules = career_save.competition_rules()
    competition_id = scope.competition_id
    if competition_id is None:
        return competition_rules
    return (block for block in competition_rules if block.competition_id == competition_id)


def _player_match_stats_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps the matches of the players in it, as suspensions does."""
    match_stats = career_save.player_match_stats()
    competition_id = scope.competition_id
    if competition_id is not None:
        return (row for row in match_stats if row.competition_id == competition_id)
    keeps_player = _player_filter(scope)
    if keeps_player is None:
        return match_stats
    player_uids = _scoped_player_uids(career_save, keeps_player)
    return (row for row in match_stats if row.player_uid in player_uids)


def _stadium_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps a ground the scope's clubs own or play their home games at.

    A ground belongs to a club two ways round, and both count: the club that owns it, and the
    clubs the calendar shows playing at home there. The two differ often enough to matter,
    since a club can own a ground it no longer plays at and can ground-share at one it does not
    own.
    """
    stadiums = career_save.stadiums()
    if scope.club_uids is None and scope.nation_id is None:
        return stadiums
    keeps_club = _club_uid_filter(career_save, scope)
    return (
        stadium
        for stadium in stadiums
        if keeps_club(stadium.owner_club_uid)
        or any(keeps_club(club_uid) for club_uid in stadium.home_club_uids)
    )


def _finance_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The months of the scope's clubs. Most clubs have no series at all, which is ordinary."""
    finances = career_save.finances()
    if scope.club_uids is None and scope.nation_id is None:
        return finances
    keeps_club = _club_uid_filter(career_save, scope)
    return (month for month in finances if keeps_club(month.club_uid))


def _facility_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The facilities of the scope's clubs. Only clubs with a finance series have a row."""
    facilities = career_save.facilities()
    if scope.club_uids is None and scope.nation_id is None:
        return facilities
    keeps_club = _club_uid_filter(career_save, scope)
    return (club for club in facilities if keeps_club(club.club_uid))


def _sponsorship_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The sponsorship contracts of the scope's clubs, ended ones included."""
    sponsorships = career_save.sponsorships()
    if scope.club_uids is None and scope.nation_id is None:
        return sponsorships
    keeps_club = _club_uid_filter(career_save, scope)
    return (sponsorship for sponsorship in sponsorships if keeps_club(sponsorship.club_uid))


def _affiliate_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps a whole group one of the scope's clubs belongs to.

    A group is one record with its members nested inside it, as a league table is, so a scope
    either keeps the group a club sits in or it does not.
    """
    affiliates = career_save.affiliates()
    if scope.club_uids is None and scope.nation_id is None:
        return affiliates
    keeps_club = _club_uid_filter(career_save, scope)
    return (
        group for group in affiliates if any(keeps_club(club_uid) for club_uid in group.club_uids)
    )


def _job_vacancy_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The vacancies at the scope's clubs, or those of one competition.

    A vacancy names a team, so a club scope keeps the vacancies of the teams that club fields,
    and a vacancy whose team no club lists is kept only by --all.
    """
    vacancies = career_save.job_vacancies()
    competition_id = scope.competition_id
    if competition_id is not None:
        return (vacancy for vacancy in vacancies if vacancy.competition_id == competition_id)
    if scope.club_uids is None and scope.nation_id is None:
        return vacancies
    keeps_club = _club_uid_filter(career_save, scope)
    return (vacancy for vacancy in vacancies if keeps_club(vacancy.club_uid))


def _staff_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The people the scope's clubs employ. A person is scoped by the club that pays him."""
    staff = career_save.staff()
    if scope.club_uids is None and scope.nation_id is None:
        return staff
    keeps_club = _club_uid_filter(career_save, scope)
    return (person for person in staff if keeps_club(person.club_uid))


def _staff_list_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The staff lists the scope's clubs keep, empty lists included."""
    staff_lists = career_save.staff_lists()
    if scope.club_uids is None and scope.nation_id is None:
        return staff_lists
    keeps_club = _club_uid_filter(career_save, scope)
    return (club_list for club_list in staff_lists if keeps_club(club_list.club_uid))


def _injury_type_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """Every injury the game can hand out. The table belongs to the game, not to a club."""
    return career_save.injury_types()


def _injury_history_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """A club or nation scope keeps the rows of the players now in it, wherever they happened.

    An injury row carries the club the person was registered with when it happened, which for
    an old row is often a club he has since left. Scoping on where he is now is what a squad's
    medical history means, so the scope is the scope's current players, as suspensions is. A
    row whose person the save no longer keeps as a player is kept only by --all.
    """
    injuries = career_save.injury_history()
    keeps_player = _player_filter(scope)
    if keeps_player is None:
        return injuries
    player_uids = _scoped_player_uids(career_save, keeps_player)
    return (row for row in injuries if row.player_uid in player_uids)


def _training_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The training calendars of the scope's clubs, which only the managed club has."""
    training = career_save.training()
    if scope.club_uids is None:
        return training
    keeps_club = _club_uid_filter(career_save, scope)
    return (team for team in training if keeps_club(team.club_uid))


def _mentoring_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The mentoring groups of the scope's clubs, which only the managed club has."""
    mentoring = career_save.mentoring()
    if scope.club_uids is None:
        return mentoring
    keeps_club = _club_uid_filter(career_save, scope)
    return (group for group in mentoring if keeps_club(group.club_uid))


def _tactic_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The tactics of the scope's clubs, which only the managed club has."""
    tactics = career_save.tactics()
    if scope.club_uids is None:
        return tactics
    keeps_club = _club_uid_filter(career_save, scope)
    return (tactic for tactic in tactics if keeps_club(tactic.club_uid))


def _set_piece_rows(career_save: fmsave.Save, scope: _ExportScope) -> Iterable[object]:
    """The set-piece routines of the scope's clubs, which only the managed club has."""
    set_pieces = career_save.set_pieces()
    if scope.club_uids is None:
        return set_pieces
    keeps_club = _club_uid_filter(career_save, scope)
    return (routine for routine in set_pieces if keeps_club(routine.club_uid))


@dataclass(frozen=True, slots=True)
class _ExportTable:
    """One table `export` writes: its record type, the scopes it takes and how it reads rows.

    Attributes:
        record_type: The record dataclass, whose flat columns are the table's columns.
        scopes: The scopes this table takes; every other scope is a usage error.
        rows: Reads the table and returns the rows the scope keeps, in table order. Every
            table the rows depend on is read there, so the rows can be written after the save
            is closed, and every one of them is read through the reader that enforces its own
            checks.
        note: A fact about this table's scopes that both its message and its help text carry.
    """

    record_type: type[object]
    scopes: frozenset[str]
    rows: Callable[[fmsave.Save, _ExportScope], Iterable[object]]
    note: str = ""


_EVERY_SCOPE = frozenset(_SCOPE_OPTIONS)
_EVERY_ROW_ONLY = frozenset({_EVERY_ROW_SCOPE})
# A competition names no club and a club table names no competition, so each takes the scopes
# its rows can answer and turns the others down rather than writing every row regardless.
_CLUB_AND_NATION_SCOPES = frozenset(
    {_CLUB_SCOPE, _MANAGED_CLUB_SCOPE, _NATION_SCOPE, _EVERY_ROW_SCOPE}
)
_CLUB_SCOPES = frozenset({_CLUB_SCOPE, _MANAGED_CLUB_SCOPE, _EVERY_ROW_SCOPE})
_COMPETITION_SCOPES = frozenset({_COMPETITION_SCOPE, _EVERY_ROW_SCOPE})

_EXPORT_TABLES: dict[str, _ExportTable] = {
    "players": _ExportTable(Player, _CLUB_AND_NATION_SCOPES, _player_rows),
    "contracts": _ExportTable(Contract, _CLUB_AND_NATION_SCOPES, _contract_rows),
    "suspensions": _ExportTable(Suspension, _CLUB_AND_NATION_SCOPES, _suspension_rows),
    "clubs": _ExportTable(Club, _CLUB_AND_NATION_SCOPES, _club_rows),
    "managed-clubs": _ExportTable(ManagedClub, _CLUB_SCOPES, _managed_club_rows),
    "stages": _ExportTable(Stage, _COMPETITION_SCOPES, _stage_rows),
    "competitions": _ExportTable(Competition, _COMPETITION_SCOPES, _competition_rows),
    "fixtures": _ExportTable(Fixture, _EVERY_SCOPE, _fixture_rows),
    "league-tables": _ExportTable(LeagueTable, _EVERY_SCOPE, _league_table_rows),
    "transfer-windows": _ExportTable(TransferWindow, _EVERY_ROW_ONLY, _transfer_window_rows),
    "competition-rules": _ExportTable(
        CompetitionRules, _COMPETITION_SCOPES, _competition_rules_rows, note=_COMPETITION_RULES_NOTE
    ),
    "player-match-stats": _ExportTable(PlayerMatchStats, _EVERY_SCOPE, _player_match_stats_rows),
    "stadiums": _ExportTable(Stadium, _CLUB_AND_NATION_SCOPES, _stadium_rows),
    "finances": _ExportTable(FinanceMonth, _CLUB_AND_NATION_SCOPES, _finance_rows),
    "sponsorships": _ExportTable(Sponsorship, _CLUB_AND_NATION_SCOPES, _sponsorship_rows),
    "facilities": _ExportTable(ClubFacilities, _CLUB_AND_NATION_SCOPES, _facility_rows),
    "affiliates": _ExportTable(AffiliateGroup, _CLUB_AND_NATION_SCOPES, _affiliate_rows),
    "job-vacancies": _ExportTable(JobVacancy, _EVERY_SCOPE, _job_vacancy_rows),
    "staff": _ExportTable(Staff, _CLUB_AND_NATION_SCOPES, _staff_rows),
    "staff-lists": _ExportTable(StaffList, _CLUB_AND_NATION_SCOPES, _staff_list_rows),
    "injury-types": _ExportTable(InjuryType, _EVERY_ROW_ONLY, _injury_type_rows),
    "injury-history": _ExportTable(InjuryRecord, _CLUB_AND_NATION_SCOPES, _injury_history_rows),
    "training": _ExportTable(
        TeamTraining, _CLUB_SCOPES, _training_rows, note=_MANAGED_CLUB_ONLY_NOTE
    ),
    "mentoring": _ExportTable(
        MentoringGroup, _CLUB_SCOPES, _mentoring_rows, note=_MANAGED_CLUB_ONLY_NOTE
    ),
    "tactics": _ExportTable(Tactic, _CLUB_SCOPES, _tactic_rows, note=_MANAGED_CLUB_ONLY_NOTE),
    "set-pieces": _ExportTable(
        SetPieceRoutine, _CLUB_SCOPES, _set_piece_rows, note=_MANAGED_CLUB_ONLY_NOTE
    ),
}


def _selected_column_names(columns_text: str | None, record_type: type[object]) -> list[str] | None:
    """The --columns names in order without repeats, or None when every column is written.

    Raises:
        _CommandUsageError: No name is given, or a name is not a column of the table.
    """
    if columns_text is None:
        return None
    stripped_names = (column_name.strip() for column_name in columns_text.split(","))
    column_names = list(dict.fromkeys(column_name for column_name in stripped_names if column_name))
    if not column_names:
        raise _CommandUsageError("--columns needs at least one column name")
    known_names = frozenset(export.column_names(record_type))
    unknown_names = [column_name for column_name in column_names if column_name not in known_names]
    if unknown_names:
        shown_names = ", ".join(_redact_argument(column_name) for column_name in unknown_names)
        raise _CommandUsageError(f"unknown columns: {shown_names}")
    return column_names


def _check_output_path(output_path: Path, save_path: Path) -> None:
    """Reject an output file whose folder is missing or that is the save itself.

    Raises:
        _CommandUsageError: The output folder does not exist, or the output file is the save.
    """
    output_folder = output_path.parent
    if not output_folder.is_dir():
        raise _CommandUsageError(f"folder does not exist: {output_folder.name or _UNNAMED_PATH}")
    try:
        is_the_save = output_path.samefile(save_path)
    except OSError:
        is_the_save = False
    if is_the_save:
        raise _CommandUsageError("the output file is the save file; choose another output path")


@contextlib.contextmanager
def _output_write_errors(*, to_standard_output: bool) -> Generator[None]:
    """Raise an OSError from writing, flushing or closing output as an _OutputWriteError.

    Only output is written inside the block, so a failure there is never a failure to read the
    save.
    """
    try:
        yield
    except OSError as error:
        raise _OutputWriteError(error, to_standard_output=to_standard_output) from error


def _is_closed_pipe_error(write_error: OSError) -> bool:
    """Whether a write failed because the reader of a pipe has gone away.

    Windows reports a write to a closed pipe as EINVAL rather than EPIPE.
    """
    if isinstance(write_error, BrokenPipeError) or write_error.errno == errno.EPIPE:
        return True
    return write_error.errno == errno.EINVAL and sys.platform == "win32"


@contextlib.contextmanager
def _output_stream(output_path: Path | None) -> Generator[TextIO]:
    """Yield the output file opened as UTF-8, or standard output reconfigured to UTF-8.

    Raises:
        _OutputWriteError: The output file cannot be opened. Failures while writing to it or
            closing it are raised as they are.
    """
    if output_path is None:
        standard_output = sys.stdout
        if isinstance(standard_output, io.TextIOWrapper):
            standard_output.reconfigure(encoding="utf-8", newline="")
        yield standard_output
        return
    try:
        file_stream = open(output_path, "w", encoding="utf-8", newline="")  # noqa: SIM115
    except OSError as error:
        raise _OutputWriteError(error, to_standard_output=False, while_opening=True) from error
    with file_stream:
        yield file_stream


def _write_records(
    records: Iterable[object],
    record_type: type[object],
    output_format: str,
    column_names: list[str] | None,
    stream: TextIO,
) -> None:
    """Write records one at a time as CSV, a JSON array or JSON Lines.

    CSV rows are flat, and keep only the chosen columns. JSON rows are nested, or flat with
    only the chosen columns.
    """
    if output_format == "csv":
        export._write_records_csv(  # pyright: ignore[reportPrivateUsage]
            records, record_type, stream, columns=column_names, operation_name="write_records"
        )
        return
    if column_names is None:
        json_rows: Iterable[dict[str, object]] = (
            export.record_to_dict(record, json_ready=True) for record in records
        )
    else:
        json_rows = (
            export.select_columns(row, column_names)
            for row in export.flat_rows(records, record_type, json_ready=True)
        )
    if output_format == "json":
        export.write_json(json_rows, stream)
    else:
        export.write_jsonl(json_rows, stream)


def _competition_name_map(names_path: str | None) -> dict[int, str] | None:
    """The names a --competition-names file holds, or None when the option was not given.

    The file is read before the save is opened, so a mistake in it costs none of that work.

    Raises:
        _CommandUsageError: The file is malformed. The message names the file and not its folder.
        OSError: The file cannot be opened or read.
    """
    if names_path is None:
        return None
    try:
        return fmsave.read_competition_names(names_path)
    except ValueError as error:
        raise _CommandUsageError(str(error)) from error


def _run_export(arguments: argparse.Namespace) -> int:
    export_table = _EXPORT_TABLES[arguments.table]
    record_type = export_table.record_type
    column_names = _selected_column_names(arguments.columns, record_type)
    _check_scope_arguments(arguments)
    competition_names = _competition_name_map(arguments.competition_names)
    save_path = Path(arguments.save_path)
    output_path = None if arguments.output is None else Path(arguments.output)
    if output_path is not None:
        _check_output_path(output_path, save_path)
    # A failed check warns, and the rows it judged are written anyway; --strict stops instead.
    with fmsave.open(
        save_path, strict=arguments.strict, competition_names=competition_names
    ) as career_save:
        scope = _resolve_scope(career_save, arguments)
        records = export_table.rows(career_save, scope)
    with (
        _output_write_errors(to_standard_output=output_path is None),
        _output_stream(output_path) as stream,
    ):
        _write_records(records, record_type, arguments.format, column_names, stream)
    return EXIT_OK


def _format_check_number(value: float | None, missing_text: str) -> str:
    if value is None:
        return missing_text
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return repr(rounded)


def _render_validation_text(report: ValidationReport) -> str:
    lines: list[str] = []
    for reader in report.readers:
        count_text = "" if reader.record_count is None else f" ({reader.record_count} records)"
        lines.append(f"{reader.reader}: {reader.status}{count_text}")
        if reader.status != "failed":
            continue
        lines.extend(
            f"  {gate.name} = {_format_check_number(gate.observed, 'none')} expected "
            f"{_format_check_number(gate.minimum, '')}..{_format_check_number(gate.maximum, '')}"
            for gate in reader.gates
            if gate.applied and not gate.passed
        )
    lines.append(f"game {report.game}, build {report.build}")
    return "\n".join(lines)


def _validation_exit_code(report: ValidationReport) -> int:
    statuses = {reader.status for reader in report.readers}
    if "failed" in statuses:
        return EXIT_UNSUPPORTED
    if "error" in statuses:
        return EXIT_UNEXPECTED
    return EXIT_OK


def _run_validate(arguments: argparse.Namespace) -> int:
    with fmsave.open(Path(arguments.save_path)) as career_save:
        report = validate_save(career_save)
    if arguments.json:
        report_text = json.dumps(report.to_json_dict(), indent=2, ensure_ascii=True)
    else:
        report_text = _render_validation_text(report)
    with _output_write_errors(to_standard_output=True):
        print(report_text)
    return _validation_exit_code(report)


def _run_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "info":
        return _run_info(arguments)
    if arguments.command == "export":
        return _run_export(arguments)
    if arguments.command == "validate":
        return _run_validate(arguments)
    return EXIT_USAGE


def _silence_standard_output() -> None:
    """Point the process's standard output at the null device after a write to it failed.

    Text that could not be written stays buffered, and flushing it again at exit would fail and
    print an error. A replaced sys.stdout, such as a test capture, is left alone.
    """
    process_output = sys.__stdout__
    if process_output is None or sys.stdout is not process_output:
        return
    try:
        output_descriptor = process_output.fileno()
    except (OSError, ValueError):
        return
    null_descriptor = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_descriptor, output_descriptor)
    finally:
        os.close(null_descriptor)


def _run_guarded(arguments: argparse.Namespace) -> tuple[int, str | None]:
    """Run a command and turn any failure into an exit code and an error message."""
    try:
        exit_code = _run_command(arguments)
        with _output_write_errors(to_standard_output=True):
            sys.stdout.flush()
        return exit_code, None
    except _OutputWriteError as error:
        if error.to_standard_output:
            # Standard output still holds unwritten text, which would fail again at exit.
            _silence_standard_output()
        if not error.while_opening and _is_closed_pipe_error(error.write_error):
            return EXIT_UNEXPECTED, None
        return EXIT_UNEXPECTED, f"cannot write the output: {error}"
    except _CommandUsageError as error:
        return EXIT_USAGE, str(error)
    except FileNotFoundError as error:
        return EXIT_USAGE, f"file not found: {_error_file_name(error.filename)}"
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return EXIT_UNEXPECTED, f"cannot read {_error_file_name(error.filename)}: {reason}"
    except (NotAFmSaveError, UnsupportedGameError, ReaderCheckError) as error:
        return EXIT_UNSUPPORTED, str(error)
    except AmbiguousNameError as error:
        return EXIT_USAGE, str(error)
    except FmsaveError as error:
        return EXIT_UNEXPECTED, str(error)
    except Exception as error:  # noqa: BLE001 - last-resort handler for the CLI boundary
        return (
            EXIT_UNEXPECTED,
            f"unexpected {type(error).__name__}; please report it at {ISSUES_URL}",
        )


def _report_error(message: str) -> None:
    print(f"fmsave: error: {message}", file=sys.stderr)


def _configure_output_streams() -> None:
    """Never crash on characters the console encoding cannot show."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def _warning_module_name(filename: str) -> str:
    """The module name warnings filters match for a warning raised in this file.

    It is the name of the loaded module with that file, or else the file name without ".py",
    which is what the warnings module itself falls back to.
    """
    for module_name, loaded_module in list(sys.modules.items()):
        if getattr(loaded_module, "__file__", None) == filename:
            return module_name
    return filename[:-3] if filename.lower().endswith(".py") else filename


def main(argv: Sequence[str] | None = None) -> int:
    _configure_output_streams()
    argument_tokens = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = _build_parser().parse_args(argument_tokens)
    except _UsageError:
        usage_parser, usage_message = _redacted_usage_error(argument_tokens)
        usage_parser.exit_with_usage_error(usage_message)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        exit_code, error_message = _run_guarded(arguments)
    shown_warnings_registry: dict[str | tuple[str, type[Warning], int], int] = {}
    for caught_warning in caught_warnings:
        if issubclass(caught_warning.category, FmsaveWarning):
            print(f"fmsave: warning: {caught_warning.message}", file=sys.stderr)
        else:
            warnings.warn_explicit(
                caught_warning.message,
                caught_warning.category,
                caught_warning.filename,
                caught_warning.lineno,
                module=_warning_module_name(caught_warning.filename),
                registry=shown_warnings_registry,
                source=caught_warning.source,
            )
    if error_message is not None:
        _report_error(error_message)
    return exit_code
