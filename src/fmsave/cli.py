"""Command line interface for fmsave."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath
from typing import NoReturn

import fmsave
from fmsave._errors import (
    ISSUES_URL,
    AmbiguousNameError,
    FmsaveError,
    NotAFmSaveError,
    ReaderCheckError,
    UnsupportedGameError,
)
from fmsave._package import __version__
from fmsave.models.meta import SaveInfo

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3

UNNAMED_PATH = "the given path"
PATH_SEPARATORS = "/\\"
UNNAMED_PATH_ARGUMENT = "path"
GENERIC_USAGE_MESSAGE = "invalid arguments; run 'fmsave --help' for usage"


def error_file_name(filename: object) -> str:
    """Return the file name, without its folder, of the path an OSError reports."""
    file_name = Path(str(filename)).name if filename else ""
    return file_name or UNNAMED_PATH


def is_path_like(argument_text: str) -> bool:
    """Whether an argument contains a path separator and is not made only of separators."""
    has_separator = any(separator in argument_text for separator in PATH_SEPARATORS)
    return has_separator and argument_text.strip(PATH_SEPARATORS) != ""


def redact_argument(argument_token: str) -> str:
    """Reduce a path-like argument to its last component, keeping any "--flag=" before the path.

    Text up to an "=" is kept only when the argument starts with "-", so a folder name that
    contains "=" is removed with the rest of the folder. The last component splits on both
    / and \\ on every system.
    """
    if not is_path_like(argument_token):
        return argument_token
    kept_prefix_length = 0
    if argument_token.startswith("-"):
        separator_indexes = [argument_token.find(separator) for separator in PATH_SEPARATORS]
        first_separator_index = min(index for index in separator_indexes if index >= 0)
        kept_prefix_length = argument_token.find("=", 0, first_separator_index) + 1
    path_name = PureWindowsPath(argument_token[kept_prefix_length:]).name
    return argument_token[:kept_prefix_length] + (path_name or UNNAMED_PATH_ARGUMENT)


def argument_folder_texts(argument_tokens: Sequence[str]) -> list[str]:
    """Return the text before the last separator of each path-like argument that names a folder.

    Trailing separators are ignored, so "extra/" names no folder.
    """
    folder_texts: list[str] = []
    for argument_token in argument_tokens:
        if not is_path_like(argument_token):
            continue
        trimmed_token = argument_token.rstrip(PATH_SEPARATORS)
        last_separator_index = max(trimmed_token.rfind(separator) for separator in PATH_SEPARATORS)
        if last_separator_index < 0:
            continue
        folder_text = trimmed_token[:last_separator_index]
        if len(folder_text) >= 2 and folder_text.strip(PATH_SEPARATORS):
            folder_texts.append(folder_text)
    return folder_texts


class UsageError(Exception):
    """A usage error the argument parser raises instead of printing it and exiting."""

    def __init__(self, parser: CommandLineParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser
        self.message = message


class CommandLineParser(argparse.ArgumentParser):
    """Argument parser that raises UsageError rather than printing a usage error."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(self, message)

    def exit_with_usage_error(self, message: str) -> NoReturn:
        """Print this parser's usage line and the message as argparse does, then exit with 2."""
        super().error(message)


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
    info_parser.add_argument("save_path", metavar="SAVE", help="path to a .fm save file")
    info_parser.add_argument(
        "--show-name", action="store_true", help="include the save's name (hidden by default)"
    )
    info_parser.add_argument("--json", action="store_true", help="print JSON instead of text")
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


def run_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "info":
        return run_info(arguments)
    return EXIT_USAGE


def run_guarded(arguments: argparse.Namespace) -> tuple[int, str | None]:
    """Run a command and turn any failure into an exit code and an error message."""
    try:
        return run_command(arguments), None
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
        print(f"fmsave: warning: {caught_warning.message}", file=sys.stderr)
    if error_message is not None:
        report_error(error_message)
    return exit_code
