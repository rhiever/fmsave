"""Command line interface: `fmsave info`, `fmsave export`, `fmsave validate`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from fmsave._package import __version__

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fmsave", description="Read Football Manager 26 save files."
    )
    parser.add_argument("--version", action="version", version=f"fmsave {__version__}")
    parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return EXIT_OK
