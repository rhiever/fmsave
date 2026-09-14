"""Command line interface for fmsave."""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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


def report_error(message: str) -> None:
    print(f"fmsave: error: {message}", file=sys.stderr)


def configure_output_streams() -> None:
    """Never crash on characters the console encoding cannot show."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_streams()
    arguments = build_parser().parse_args(argv)
    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            exit_code = run_command(arguments)
    except FileNotFoundError as error:
        missing_name = Path(str(error.filename)).name if error.filename else "the given path"
        report_error(f"file not found: {missing_name}")
        return EXIT_USAGE
    except OSError as error:
        unreadable_name = Path(str(error.filename)).name if error.filename else "the given path"
        report_error(f"cannot read {unreadable_name}: {error.strerror}")
        return EXIT_UNEXPECTED
    except (NotAFmSaveError, UnsupportedGameError, ReaderCheckError) as error:
        report_error(str(error))
        return EXIT_UNSUPPORTED
    except AmbiguousNameError as error:
        report_error(str(error))
        return EXIT_USAGE
    except FmsaveError as error:
        report_error(str(error))
        return EXIT_UNEXPECTED
    except Exception as error:  # noqa: BLE001 - last-resort handler for the CLI boundary
        report_error(f"unexpected {type(error).__name__}; please report it at {ISSUES_URL}")
        return EXIT_UNEXPECTED
    for caught_warning in caught_warnings:
        print(f"fmsave: warning: {caught_warning.message}", file=sys.stderr)
    return exit_code
