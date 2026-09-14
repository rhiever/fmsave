"""Command line interface for fmsave."""

from __future__ import annotations

import argparse
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


def argument_display_name(path_argument: str) -> str:
    """Return the last component of a path argument, splitting on both / and \\."""
    return PureWindowsPath(path_argument).name or UNNAMED_PATH


def error_file_name(filename: object) -> str:
    """Return the file name, without its folder, of the path an OSError reports."""
    file_name = Path(str(filename)).name if filename else ""
    return file_name or UNNAMED_PATH


def is_path_like(argument_text: str) -> bool:
    """Whether an argument contains a path separator and is not made only of separators."""
    has_separator = "/" in argument_text or "\\" in argument_text
    return has_separator and argument_text.strip("/\\") != ""


def redaction_candidates(argument_tokens: Sequence[str]) -> list[str]:
    """Return the path-like argument texts to redact, longest first.

    A candidate is a whole argument, or the text after the first "=" of an argument such as
    --flag=value, because usage errors can quote either one.
    """
    candidates: set[str] = set()
    for token in argument_tokens:
        candidates.add(token)
        if "=" in token:
            candidates.add(token.partition("=")[2])
    path_like_candidates = [candidate for candidate in candidates if is_path_like(candidate)]
    return sorted(path_like_candidates, key=lambda candidate: (-len(candidate), candidate))


def redact_path_arguments(message: str, argument_tokens: Sequence[str]) -> str:
    """Replace every path-like argument in a message with its last component."""
    redacted_message = message
    for candidate in redaction_candidates(argument_tokens):
        candidate_name = argument_display_name(candidate)
        redacted_message = redacted_message.replace(repr(candidate), repr(candidate_name))
        redacted_message = redacted_message.replace(candidate, candidate_name)
    return redacted_message


class PathRedactingParser(argparse.ArgumentParser):
    """Argument parser whose usage errors never show the folders of a path argument."""

    argument_tokens: tuple[str, ...] = ()

    def error(self, message: str) -> NoReturn:
        super().error(redact_path_arguments(message, self.argument_tokens))


def build_parser(argument_tokens: Sequence[str] = ()) -> argparse.ArgumentParser:
    parser = PathRedactingParser(
        prog="fmsave",
        description="Read Football Manager 26 save files. fmsave never modifies a save.",
    )
    parser.argument_tokens = tuple(argument_tokens)
    parser.add_argument("--version", action="version", version=f"fmsave {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    info_parser = subcommands.add_parser(
        "info",
        help="show the game, build and in-game date of a save",
        description="Show save metadata.",
    )
    info_parser.argument_tokens = tuple(argument_tokens)
    info_parser.add_argument("save_path", metavar="SAVE", help="path to a .fm save file")
    info_parser.add_argument(
        "--show-name", action="store_true", help="include the save's name (hidden by default)"
    )
    info_parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser


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
        print(json.dumps(info_record(save_info, arguments.show_name), indent=2, ensure_ascii=False))
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
    arguments = build_parser(argument_tokens).parse_args(argument_tokens)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        exit_code, error_message = run_guarded(arguments)
    for caught_warning in caught_warnings:
        print(f"fmsave: warning: {caught_warning.message}", file=sys.stderr)
    if error_message is not None:
        report_error(error_message)
    return exit_code
