"""Reference docs checks: every public name is documented, once, on the right page."""

from __future__ import annotations

import argparse
import inspect
import re
from pathlib import Path

import fmsave
from fmsave import cli

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "docs" / "reference"
REFERENCE_PAGE_NAMES = ("save.md", "records.md", "enums.md", "table.md", "errors.md", "cli.md")

# A directive that documents one fmsave name, for example ".. autoclass:: fmsave.Player" or
# ".. autofunction:: fmsave.open". This is what "documented" means throughout this file: not
# any mention of a name in prose, but the directive that generates its entry from its docstring.
DIRECTIVE_TARGET_PATTERN = re.compile(r"^\s*\.\.\s+auto\w+::\s+fmsave\.(\w+)\s*$", re.MULTILINE)
# The comma-separated ":members:" option following an ".. autoclass:: fmsave.Save" directive,
# which is where save.md names Save's reader methods.
SAVE_MEMBERS_PATTERN = re.compile(
    r"autoclass::\s+fmsave\.Save\s*\n\s*:members:\s*((?:.+\n(?:\s+\S.*\n)*))"
)


def reference_page_text(page_name: str) -> str:
    """The raw source of one reference page this module owns."""
    return (REFERENCE_DIR / page_name).read_text(encoding="utf-8")


def documented_names_by_page() -> dict[str, set[str]]:
    """Every fmsave.<Name> an autodoc directive documents, per reference page."""
    return {
        page_name: set(DIRECTIVE_TARGET_PATTERN.findall(reference_page_text(page_name)))
        for page_name in REFERENCE_PAGE_NAMES
    }


def documented_names() -> set[str]:
    """Every fmsave.<Name> an autodoc directive documents, across every reference page."""
    return set().union(*documented_names_by_page().values())


def save_reader_method_names() -> set[str]:
    """The public methods of fmsave.Save that return a Table: its reader methods.

    close() and the info/closed properties are deliberately excluded: a reader method is one
    that hands back a Table, and those three do not.
    """
    reader_names: set[str] = set()
    for member_name, member in inspect.getmembers(fmsave.Save):
        if member_name.startswith("_") or not callable(member):
            continue
        try:
            return_annotation = inspect.signature(member).return_annotation
        except (TypeError, ValueError):
            continue
        if isinstance(return_annotation, str) and return_annotation.startswith("Table["):
            reader_names.add(member_name)
    return reader_names


def save_documented_members() -> set[str]:
    """The names listed in save.md's ":members:" option for the Save autoclass directive."""
    members_match = SAVE_MEMBERS_PATTERN.search(reference_page_text("save.md"))
    assert members_match, "save.md has no '.. autoclass:: fmsave.Save' with a ':members:' option"
    return {name.strip() for name in members_match.group(1).replace("\n", " ").split(",")}


def cli_command_parsers() -> dict[str, argparse.ArgumentParser]:
    """The command parsers of the fmsave parser, by command name."""
    for action in cli._build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the fmsave parser has no commands")


def export_table_choices() -> set[str]:
    """The table names the export command accepts, exactly as the CLI presents them."""
    for action in cli_command_parsers()["export"]._actions:
        if action.dest == "table":
            assert action.choices is not None
            return {str(table_name) for table_name in action.choices}
    raise AssertionError("the export command has no table argument")


def test_every_public_name_is_documented() -> None:
    missing_names = set(fmsave.__all__) - documented_names()
    assert not missing_names, sorted(missing_names)


def test_no_public_name_is_documented_on_more_than_one_page() -> None:
    names_by_page = documented_names_by_page()
    page_count_by_name: dict[str, list[str]] = {}
    for page_name, names in names_by_page.items():
        for name in names:
            page_count_by_name.setdefault(name, []).append(page_name)
    duplicated = {name: pages for name, pages in page_count_by_name.items() if len(pages) > 1}
    assert not duplicated, duplicated


def test_every_documented_name_is_public() -> None:
    """Guards the pages themselves: a directive naming something fmsave no longer exports.

    Autodoc would already fail the build for a name that does not exist at all; this catches
    the narrower case of a name that exists but was quietly dropped from __all__.
    """
    undocumented_but_present = documented_names() - set(fmsave.__all__)
    assert not undocumented_but_present, sorted(undocumented_but_present)


def test_save_reference_names_every_reader_method() -> None:
    reader_method_names = save_reader_method_names()
    assert reader_method_names
    documented_members = save_documented_members()
    missing_names = reader_method_names - documented_members
    assert not missing_names, sorted(missing_names)


def test_save_reference_members_are_real_save_members() -> None:
    """The other side of the coverage check: nothing listed that Save does not have.

    dir() rather than a callable filter, because the list legitimately includes the info and
    closed properties alongside the callable reader methods and close().
    """
    public_save_members = {
        member_name for member_name in dir(fmsave.Save) if not member_name.startswith("_")
    }
    unknown_members = save_documented_members() - public_save_members
    assert not unknown_members, sorted(unknown_members)


def normalized_cli_text() -> str:
    """cli.md with --help's line-wrapping undone, so a wrapped table name reads as one word."""
    dehyphenated = re.sub(r"-\n\s*", "-", reference_page_text("cli.md"))
    return re.sub(r"\s+", " ", dehyphenated)


def test_cli_reference_names_every_export_table() -> None:
    table_choices = export_table_choices()
    assert table_choices
    cli_text = normalized_cli_text()
    missing_tables = {table_name for table_name in table_choices if table_name not in cli_text}
    assert not missing_tables, sorted(missing_tables)


def test_cli_reference_is_real_help_output() -> None:
    """The console blocks are pasted --help output, not paraphrased prose."""
    cli_text = reference_page_text("cli.md")
    for command_name in ("fmsave --help", "fmsave info --help", "fmsave export --help"):
        assert f"$ {command_name}" in cli_text, command_name
    parser = cli._build_parser()
    assert parser.prog in cli_text
