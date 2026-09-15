"""README checks: its code compiles, its API names exist and its required notices hold."""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import re
from pathlib import Path

import fmsave
from fmsave import cli

README_PATH = Path(__file__).resolve().parent.parent / "README.md"
README_TEXT = README_PATH.read_text(encoding="utf-8")
DISCLAIMER = (
    "fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored "
    "by Sports Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks "
    "or registered trademarks of their respective owners."
)
FORBIDDEN_PHRASES = ("hidden", "potential ability", "CA/PA")
PYTHON_BLOCK_PATTERN = re.compile(r"^```python[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
CONSOLE_BLOCK_PATTERN = re.compile(r"^```console[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
SAVE_CALL_PATTERN = re.compile(r"\bcareer_save\.([A-Za-z_]\w*)\s*\(")
READER_RESULT_CALL_PATTERN = re.compile(r"\bcareer_save\.[A-Za-z_]\w*\(\)\.([A-Za-z_]\w*)\s*\(")
PACKAGE_REFERENCE_PATTERN = re.compile(r"(?<![\w.])fmsave\.([A-Za-z_]\w*)")
LONG_OPTION_PATTERN = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
TABLE_VARIABLE_NAMES = ("squad_players", "managed_clubs")
RECORD_VARIABLE_TYPES: dict[str, type] = {
    "save_info": fmsave.SaveInfo,
    "my_club": fmsave.ManagedClub,
    "squad_player": fmsave.Player,
    "contract": fmsave.Contract,
}


def python_blocks() -> list[str]:
    return PYTHON_BLOCK_PATTERN.findall(README_TEXT)


def console_blocks() -> list[str]:
    return CONSOLE_BLOCK_PATTERN.findall(README_TEXT)


def cli_option_strings() -> set[str]:
    """Every option string of the fmsave parser and its command parsers."""
    option_strings: set[str] = set()
    pending_parsers: list[argparse.ArgumentParser] = [cli.build_parser()]
    while pending_parsers:
        parser = pending_parsers.pop()
        for action in parser._actions:
            option_strings.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                pending_parsers.extend(action.choices.values())
    return option_strings


def test_readme_has_python_blocks() -> None:
    assert python_blocks()


def test_python_blocks_compile() -> None:
    for block_number, block_source in enumerate(python_blocks(), start=1):
        compile(block_source, f"README.md python block {block_number}", "exec")


def test_save_calls_name_public_save_methods() -> None:
    public_methods = {
        member_name
        for member_name, member in inspect.getmembers(fmsave.Save)
        if not member_name.startswith("_") and callable(member)
    }
    called_names = set(SAVE_CALL_PATTERN.findall(README_TEXT))
    assert called_names
    assert called_names <= public_methods, sorted(called_names - public_methods)


def test_table_calls_name_public_table_attributes() -> None:
    python_source = "\n".join(python_blocks())
    public_names = {
        member_name for member_name in dir(fmsave.Table) if not member_name.startswith("_")
    }
    called_names = set(READER_RESULT_CALL_PATTERN.findall(python_source))
    for variable_name in TABLE_VARIABLE_NAMES:
        call_pattern = re.compile(rf"(?<![\w.]){variable_name}\.([A-Za-z_]\w*)\s*\(")
        called_names.update(call_pattern.findall(python_source))
    assert called_names
    assert called_names <= public_names, sorted(called_names - public_names)


def test_package_references_are_exported() -> None:
    referenced_names = set(PACKAGE_REFERENCE_PATTERN.findall(README_TEXT))
    assert referenced_names
    unexported_names = referenced_names - set(fmsave.__all__)
    assert not unexported_names, sorted(unexported_names)


def test_record_attributes_in_python_blocks_are_fields() -> None:
    python_source = "\n".join(python_blocks())
    for variable_name, record_type in RECORD_VARIABLE_TYPES.items():
        attribute_pattern = re.compile(rf"(?<![\w.]){variable_name}\.([A-Za-z_]\w*)")
        field_names = {record_field.name for record_field in dataclasses.fields(record_type)}
        used_names = set(attribute_pattern.findall(python_source))
        assert used_names <= field_names, (variable_name, sorted(used_names - field_names))


def test_console_block_options_exist() -> None:
    used_options = set(LONG_OPTION_PATTERN.findall("\n".join(console_blocks())))
    assert used_options
    unknown_options = used_options - cli_option_strings()
    assert not unknown_options, sorted(unknown_options)


def test_disclaimer_appears_verbatim() -> None:
    assert DISCLAIMER in " ".join(README_TEXT.split())


def test_readme_avoids_forbidden_phrases() -> None:
    folded_text = README_TEXT.casefold()
    present_phrases = [phrase for phrase in FORBIDDEN_PHRASES if phrase.casefold() in folded_text]
    assert not present_phrases
