"""Command line interface for fmsave."""

from __future__ import annotations

import argparse
import contextlib
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
from fmsave.models.clubs import Club
from fmsave.models.contracts import Contract
from fmsave.models.managed import ManagedClub
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.models.suspensions import Suspension
from fmsave.table import Table

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3

UNNAMED_PATH = "the given path"
PATH_SEPARATORS = "/\\"
UNNAMED_PATH_ARGUMENT = "path"
GENERIC_USAGE_MESSAGE = "invalid arguments; run 'fmsave --help' for usage"

TABLE_RECORD_TYPES: dict[str, type[object]] = {
    "players": Player,
    "contracts": Contract,
    "suspensions": Suspension,
    "clubs": Club,
    "managed-clubs": ManagedClub,
}
OUTPUT_FORMATS = ("csv", "json", "jsonl")
NATION_NAME_MESSAGE = "nation names arrive in a later release; pass a nation id"
COMPETITION_SCOPE_MESSAGE = "competition scopes arrive with competition tables in a later release"
MANAGED_CLUBS_NATION_MESSAGE = (
    "managed-clubs cannot be exported by nation; use --club, --managed-club or --all"
)
NO_MANAGED_CLUB_MESSAGE = "no managed club found in this save"


def error_file_name(filename: object) -> str:
    """Return the file name, without its folder, of the path an OSError reports."""
    file_name = Path(str(filename)).name if filename else ""
    return file_name or UNNAMED_PATH


def is_path_like(argument_text: str) -> bool:
    """Whether an argument contains a path separator and is not made only of separators."""
    has_separator = any(separator in argument_text for separator in PATH_SEPARATORS)
    return has_separator and argument_text.strip(PATH_SEPARATORS) != ""


def is_glued_short_option(argument_token: str) -> bool:
    """Whether an argument is a short option with its value attached, such as "-oPATH"."""
    return (
        len(argument_token) > 2
        and argument_token[0] == "-"
        and argument_token[1] not in "-" + PATH_SEPARATORS
    )


def redact_argument(argument_token: str) -> str:
    """Reduce a path-like argument to its last component, keeping any "--flag=" before the path.

    Text up to an "=" is kept only when the argument starts with "-", so a folder name that
    contains "=" is removed with the rest of the folder. A short option with its value attached,
    such as "-oPATH", keeps the option and any "-" or "=" that starts the value, and has the
    rest of the value reduced. The last component splits on both / and \\ on every system.
    """
    if not is_path_like(argument_token):
        return argument_token
    if is_glued_short_option(argument_token):
        attached_value = argument_token[2:]
        value_marker_length = len(attached_value) - len(attached_value.lstrip("-="))
        kept_text = argument_token[: 2 + value_marker_length]
        return kept_text + redact_argument(attached_value[value_marker_length:])
    kept_prefix_length = 0
    if argument_token.startswith("-"):
        separator_indexes = [argument_token.find(separator) for separator in PATH_SEPARATORS]
        first_separator_index = min(index for index in separator_indexes if index >= 0)
        kept_prefix_length = argument_token.find("=", 0, first_separator_index) + 1
    path_name = PureWindowsPath(argument_token[kept_prefix_length:]).name
    return argument_token[:kept_prefix_length] + (path_name or UNNAMED_PATH_ARGUMENT)


def argument_folder_texts(argument_tokens: Sequence[str]) -> list[str]:
    """Return the text before the last separator of each path-like argument that names a folder.

    Trailing separators are ignored, so "extra/" names no folder. The value of a short option
    with its value attached is checked on its own as well.
    """
    candidate_texts: list[str] = []
    for argument_token in argument_tokens:
        candidate_texts.append(argument_token)
        if is_glued_short_option(argument_token):
            candidate_texts.append(argument_token[2:])
    folder_texts: list[str] = []
    for candidate_text in candidate_texts:
        if not is_path_like(candidate_text):
            continue
        trimmed_text = candidate_text.rstrip(PATH_SEPARATORS)
        last_separator_index = max(trimmed_text.rfind(separator) for separator in PATH_SEPARATORS)
        if last_separator_index < 0:
            continue
        folder_text = trimmed_text[:last_separator_index]
        if len(folder_text) >= 2 and folder_text.strip(PATH_SEPARATORS):
            folder_texts.append(folder_text)
    return folder_texts


class UsageError(Exception):
    """A usage error the argument parser raises instead of printing it and exiting."""

    def __init__(self, parser: CommandLineParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser
        self.message = message


class CommandUsageError(Exception):
    """Arguments that parse but ask for something the save cannot give, such as an unknown club."""


class OutputWriteError(Exception):
    """The output file could not be opened for writing."""


class CommandLineParser(argparse.ArgumentParser):
    """Argument parser that raises UsageError rather than printing a usage error."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(self, message)

    def exit_with_usage_error(self, message: str) -> NoReturn:
        """Print this parser's usage line and the message as argparse does, then exit with 2."""
        super().error(message)


def add_save_argument(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("save_path", metavar="SAVE", help="path to a .fm save file")


def build_parser() -> CommandLineParser:
    parser = CommandLineParser(
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
    add_save_argument(info_parser)
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
    add_save_argument(export_parser)
    export_parser.add_argument(
        "table",
        metavar="TABLE",
        choices=tuple(TABLE_RECORD_TYPES),
        help=f"the table to write: {', '.join(TABLE_RECORD_TYPES)}",
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
        help="rows of one competition (arrives with competition tables in a later release)",
    )
    scope_group.add_argument("--nation", metavar="VALUE", help="rows of one nation, by nation id")
    scope_group.add_argument("--all", action="store_true", help="every row")
    export_parser.add_argument(
        "--format", choices=OUTPUT_FORMATS, default="csv", help="output format (default: csv)"
    )
    export_parser.add_argument(
        "--columns",
        metavar="NAMES",
        help="comma-separated flat column names to write, in this order",
    )
    export_parser.add_argument(
        "-o", "--output", metavar="PATH", help="write to this file instead of standard output"
    )

    validate_parser = subcommands.add_parser(
        "validate",
        help="report how each reader fares on a save, without any names or uids",
        description="Run every reader and report its checks, counts and coverage. The report "
        "holds no names, uids or other values from the save.",
    )
    add_save_argument(validate_parser)
    validate_parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser


def redacted_usage_error(argument_tokens: Sequence[str]) -> tuple[CommandLineParser, str]:
    """Return the parser and message to show for arguments the parser rejected.

    Usage errors quote only parser vocabulary and argument text, so the message comes from parsing
    the arguments again with every path reduced to its last component. When that parse does not
    fail, or its message still shows a folder, a generic message is used instead.
    """
    parser = build_parser()
    redacted_tokens = [redact_argument(argument_token) for argument_token in argument_tokens]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(redacted_tokens)
    except UsageError as usage_error:
        folder_texts = argument_folder_texts(argument_tokens)
        if not any(folder_text in usage_error.message for folder_text in folder_texts):
            return usage_error.parser, usage_error.message
    except SystemExit:
        pass  # The redacted arguments asked for help or the version.
    return parser, GENERIC_USAGE_MESSAGE


def info_record(save_info: SaveInfo, show_name: bool) -> dict[str, object]:
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


def render_info_text(save_info: SaveInfo, show_name: bool) -> str:
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


def run_info(arguments: argparse.Namespace) -> int:
    save_path = Path(arguments.save_path)
    with fmsave.open(save_path) as career_save:
        save_info = career_save.info
    if arguments.json:
        print(json.dumps(info_record(save_info, arguments.show_name), indent=2, ensure_ascii=True))
    else:
        print(render_info_text(save_info, arguments.show_name))
    return EXIT_OK


def is_ascii_digits(text: str) -> bool:
    return text.isascii() and text.isdigit()


def normalized_name(text: str) -> str:
    """The form Table.find compares names in: NFKC-normalized, casefolded and stripped."""
    return unicodedata.normalize("NFKC", text).casefold().strip()


def ambiguous_club_message(club_value: str, candidates: Iterable[Club]) -> str:
    candidate_lines = [
        f"  uid {club.uid}  {club.name} ({club.short_name}), nation id {club.nation_id}"
        for club in candidates
    ]
    return "\n".join(
        [
            f'more than one club matches "{redact_argument(club_value)}":',
            *candidate_lines,
            "league names arrive in a later release, so use the uid to choose one",
        ]
    )


def resolve_club(clubs: Table[Club], club_value: str) -> Club:
    """Find the one club a --club value names: a uid, else a full name, else a short name.

    Raises:
        CommandUsageError: No club has the uid or the name.
        AmbiguousNameError: More than one club has the name.
    """
    if is_ascii_digits(club_value):
        club_uid = int(club_value)
        uid_match = clubs.get_by_uid(club_uid)
        if uid_match is None:
            raise CommandUsageError(f"no club with uid {club_uid}")
        return uid_match
    name_matches = clubs.find(name=club_value)
    if not name_matches:
        wanted_name = normalized_name(club_value)
        name_matches = clubs.filter(lambda club: normalized_name(club.short_name) == wanted_name)
    if not name_matches:
        raise CommandUsageError(f'no club named "{redact_argument(club_value)}"')
    if len(name_matches) > 1:
        raise AmbiguousNameError(ambiguous_club_message(club_value, name_matches))
    return name_matches[0]


@dataclass(frozen=True, slots=True)
class ExportScope:
    """The rows an export keeps: rows of these clubs, rows of this nation, or every row.

    Attributes:
        club_uids: Keep rows of these clubs, or None to not scope by club.
        nation_id: Keep rows of this nation, or None to not scope by nation.
    """

    club_uids: frozenset[int] | None = None
    nation_id: int | None = None


def check_scope_arguments(arguments: argparse.Namespace) -> None:
    """Reject scopes that no save can answer, before the save is read.

    Raises:
        CommandUsageError: The scope is a competition, a nation name, or a nation for the
            managed-clubs table.
    """
    if arguments.competition is not None:
        raise CommandUsageError(COMPETITION_SCOPE_MESSAGE)
    if arguments.nation is not None:
        if arguments.table == "managed-clubs":
            raise CommandUsageError(MANAGED_CLUBS_NATION_MESSAGE)
        if not is_ascii_digits(arguments.nation):
            raise CommandUsageError(NATION_NAME_MESSAGE)


def resolve_scope(career_save: fmsave.Save, arguments: argparse.Namespace) -> ExportScope:
    """Turn the scope arguments into the clubs or nation whose rows are kept.

    Raises:
        CommandUsageError: The club does not exist, or the save has no managed club.
        AmbiguousNameError: More than one club has the given name.
    """
    if arguments.managed_club:
        managed_club_uids = frozenset(row.club_uid for row in career_save.managed_clubs())
        if not managed_club_uids:
            raise CommandUsageError(NO_MANAGED_CLUB_MESSAGE)
        return ExportScope(club_uids=managed_club_uids)
    if arguments.club is not None:
        club = resolve_club(career_save.clubs(), arguments.club)
        return ExportScope(club_uids=frozenset((club.uid,)))
    if arguments.nation is not None:
        return ExportScope(nation_id=int(arguments.nation))
    return ExportScope()


def player_filter(scope: ExportScope) -> Callable[[Player], bool] | None:
    """Whether a player is in the scope, or None when the scope keeps every player."""
    club_uids = scope.club_uids
    if club_uids is not None:
        return lambda player: player.club_uid in club_uids
    nation_id = scope.nation_id
    if nation_id is not None:
        return lambda player: player.nation_id == nation_id
    return None


def scoped_player_uids(
    career_save: fmsave.Save, keeps_player: Callable[[Player], bool]
) -> set[int]:
    return {player.uid for player in career_save.players() if keeps_player(player)}


def scoped_records(
    career_save: fmsave.Save, table_name: str, scope: ExportScope
) -> Iterable[object]:
    """Read a table and return the rows the scope keeps, filtered lazily, in table order.

    Every table the rows depend on is read here, so the rows can be written after the save
    is closed.
    """
    club_uids = scope.club_uids
    nation_id = scope.nation_id
    if table_name == "clubs":
        clubs = career_save.clubs()
        if club_uids is not None:
            return (club for club in clubs if club.uid in club_uids)
        if nation_id is not None:
            return (club for club in clubs if club.nation_id == nation_id)
        return clubs
    if table_name == "managed-clubs":
        managed_clubs = career_save.managed_clubs()
        if club_uids is not None:
            return (row for row in managed_clubs if row.club_uid in club_uids)
        return managed_clubs
    keeps_player = player_filter(scope)
    if table_name == "players":
        players = career_save.players()
        return players if keeps_player is None else filter(keeps_player, players)
    if table_name == "contracts":
        contracts = career_save.contracts()
        if keeps_player is None:
            return contracts
        player_uids = scoped_player_uids(career_save, keeps_player)
        return (contract for contract in contracts if contract.player_uid in player_uids)
    suspensions = career_save.suspensions()
    if club_uids is not None:
        return (suspension for suspension in suspensions if suspension.club_uid in club_uids)
    if keeps_player is None:
        return suspensions
    player_uids = scoped_player_uids(career_save, keeps_player)
    return (suspension for suspension in suspensions if suspension.player_uid in player_uids)


def selected_column_names(columns_text: str | None, record_type: type[object]) -> list[str] | None:
    """The --columns names in order without repeats, or None when every column is written.

    Raises:
        CommandUsageError: No name is given, or a name is not a column of the table.
    """
    if columns_text is None:
        return None
    stripped_names = (column_name.strip() for column_name in columns_text.split(","))
    column_names = list(dict.fromkeys(column_name for column_name in stripped_names if column_name))
    if not column_names:
        raise CommandUsageError("--columns needs at least one column name")
    known_names = frozenset(export.column_names(record_type))
    unknown_names = [column_name for column_name in column_names if column_name not in known_names]
    if unknown_names:
        shown_names = ", ".join(redact_argument(column_name) for column_name in unknown_names)
        raise CommandUsageError(f"unknown columns: {shown_names}")
    return column_names


def check_output_path(output_path: Path, save_path: Path) -> None:
    """Reject an output file whose folder is missing or that is the save itself.

    Raises:
        CommandUsageError: The output folder does not exist, or the output file is the save.
    """
    output_folder = output_path.parent
    if not output_folder.is_dir():
        raise CommandUsageError(f"folder does not exist: {output_folder.name or UNNAMED_PATH}")
    try:
        is_the_save = output_path.samefile(save_path)
    except OSError:
        is_the_save = False
    if is_the_save:
        raise CommandUsageError("the output file is the save file; choose another output path")


@contextlib.contextmanager
def output_stream(output_path: Path | None) -> Generator[TextIO]:
    """Yield the output file opened as UTF-8, or standard output reconfigured to UTF-8.

    Raises:
        OutputWriteError: The output file cannot be opened.
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
        reason = error.strerror or type(error).__name__
        raise OutputWriteError(
            f"cannot write {error_file_name(error.filename)}: {reason}"
        ) from error
    with file_stream:
        yield file_stream


def write_records(
    records: Iterable[object],
    record_type: type[object],
    output_format: str,
    column_names: list[str] | None,
    stream: TextIO,
) -> None:
    """Write records one at a time as CSV, a JSON array or JSON Lines.

    CSV rows are flat. JSON rows are nested, or flat with only the chosen columns.
    """
    if output_format == "csv":
        flat_rows = export.flat_rows(records, record_type)
        if column_names is None:
            export.write_csv(flat_rows, export.column_names(record_type), stream)
        else:
            selected_rows = (export.select_columns(row, column_names) for row in flat_rows)
            export.write_csv(selected_rows, column_names, stream)
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


def run_export(arguments: argparse.Namespace) -> int:
    table_name: str = arguments.table
    record_type = TABLE_RECORD_TYPES[table_name]
    column_names = selected_column_names(arguments.columns, record_type)
    check_scope_arguments(arguments)
    save_path = Path(arguments.save_path)
    output_path = None if arguments.output is None else Path(arguments.output)
    if output_path is not None:
        check_output_path(output_path, save_path)
    with fmsave.open(save_path) as career_save:
        scope = resolve_scope(career_save, arguments)
        records = scoped_records(career_save, table_name, scope)
    with output_stream(output_path) as stream:
        write_records(records, record_type, arguments.format, column_names, stream)
    return EXIT_OK


def format_check_number(value: float | None, missing_text: str) -> str:
    if value is None:
        return missing_text
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return repr(rounded)


def render_validation_text(report: ValidationReport) -> str:
    lines: list[str] = []
    for reader in report.readers:
        count_text = "" if reader.record_count is None else f" ({reader.record_count} records)"
        lines.append(f"{reader.reader}: {reader.status}{count_text}")
        if reader.status != "failed":
            continue
        lines.extend(
            f"  {gate.name} = {format_check_number(gate.observed, 'none')} expected "
            f"{format_check_number(gate.minimum, '')}..{format_check_number(gate.maximum, '')}"
            for gate in reader.gates
            if gate.applied and not gate.passed
        )
    lines.append(f"game {report.game}, build {report.build}")
    return "\n".join(lines)


def validation_exit_code(report: ValidationReport) -> int:
    statuses = {reader.status for reader in report.readers}
    if "failed" in statuses:
        return EXIT_UNSUPPORTED
    if "error" in statuses:
        return EXIT_UNEXPECTED
    return EXIT_OK


def run_validate(arguments: argparse.Namespace) -> int:
    with fmsave.open(Path(arguments.save_path)) as career_save:
        report = validate_save(career_save)
    if arguments.json:
        print(json.dumps(report.to_json_dict(), indent=2, ensure_ascii=True))
    else:
        print(render_validation_text(report))
    return validation_exit_code(report)


def run_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "info":
        return run_info(arguments)
    if arguments.command == "export":
        return run_export(arguments)
    if arguments.command == "validate":
        return run_validate(arguments)
    return EXIT_USAGE


def silence_standard_output() -> None:
    """Point the process's standard output at the null device after its reader has gone away.

    Without this, flushing standard output at exit fails again and prints an error. A replaced
    sys.stdout, such as a test capture, is left alone.
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


def run_guarded(arguments: argparse.Namespace) -> tuple[int, str | None]:
    """Run a command and turn any failure into an exit code and an error message."""
    try:
        exit_code = run_command(arguments)
        sys.stdout.flush()
        return exit_code, None
    except BrokenPipeError:
        silence_standard_output()
        return EXIT_UNEXPECTED, None
    except CommandUsageError as error:
        return EXIT_USAGE, str(error)
    except OutputWriteError as error:
        return EXIT_UNEXPECTED, str(error)
    except FileNotFoundError as error:
        return EXIT_USAGE, f"file not found: {error_file_name(error.filename)}"
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return EXIT_UNEXPECTED, f"cannot read {error_file_name(error.filename)}: {reason}"
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


def report_error(message: str) -> None:
    print(f"fmsave: error: {message}", file=sys.stderr)


def configure_output_streams() -> None:
    """Never crash on characters the console encoding cannot show."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_streams()
    argument_tokens = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = build_parser().parse_args(argument_tokens)
    except UsageError:
        usage_parser, usage_message = redacted_usage_error(argument_tokens)
        usage_parser.exit_with_usage_error(usage_message)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        exit_code, error_message = run_guarded(arguments)
    for caught_warning in caught_warnings:
        if issubclass(caught_warning.category, FmsaveWarning):
            print(f"fmsave: warning: {caught_warning.message}", file=sys.stderr)
        else:
            warnings.warn_explicit(
                caught_warning.message,
                caught_warning.category,
                caught_warning.filename,
                caught_warning.lineno,
                source=caught_warning.source,
            )
    if error_message is not None:
        report_error(error_message)
    return exit_code
