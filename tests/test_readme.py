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
# What the page must not be SOLD on. Not a vocabulary ban: "current ability", "potential
# ability" and "hidden attribute" are ordinary Football Manager words, fmsave reads those
# fields, and the page says so where saying so helps a reader. The rule is about the pitch.
PITCH_CLAIMS = (
    "hidden",
    "every player in the database",
    "the whole database",
    "the entire database",
    "full database",
)
PYTHON_BLOCK_PATTERN = re.compile(r"^```python[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
CONSOLE_BLOCK_PATTERN = re.compile(r"^```console[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
SAVE_CALL_PATTERN = re.compile(r"\bcareer_save\.([A-Za-z_]\w*)\s*\(")
READER_RESULT_CALL_PATTERN = re.compile(r"\bcareer_save\.[A-Za-z_]\w*\(\)\.([A-Za-z_]\w*)\s*\(")
PACKAGE_REFERENCE_PATTERN = re.compile(r"(?<![\w.])fmsave\.([A-Za-z_]\w*)")
LONG_OPTION_PATTERN = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
SHORT_OPTION_PATTERN = re.compile(r"(?<![\w-])-[A-Za-z](?![\w-])")
CONSOLE_COMMAND_PATTERN = re.compile(r"(?<![\w-])fmsave[ \t]+([a-z][a-z-]*)")
COMMAND_BULLET_PATTERN = re.compile(r"^- `([a-z][a-z-]*)`", re.MULTILINE)
BACKTICK_SPAN_PATTERN = re.compile(r"`([^`]+)`")
LEADING_NAME_PATTERN = re.compile(r"[A-Za-z_]\w*(?:/\w+)*")
COMMAND_LINE_HEADING = "## Command line"
EXPORT_TABLES_LINE_PREFIX = "- `export` writes one table"
TABLE_METHODS_LINE_PREFIX = "Each reader returns a `Table`"
TABLE_VARIABLE_NAMES = ("squad", "managed_clubs")
RECORD_VARIABLE_TYPES: dict[str, type] = {
    "my_club": fmsave.ManagedClub,
    "player": fmsave.Player,
    "competition": fmsave.Competition,
}
READER_HEADING = "## What else it reads"
READER_NAME_PATTERN = re.compile(r"`([a-z_]\w*)\(\)`")


def python_blocks() -> list[str]:
    return PYTHON_BLOCK_PATTERN.findall(README_TEXT)


def console_blocks() -> list[str]:
    return CONSOLE_BLOCK_PATTERN.findall(README_TEXT)


def cli_option_strings() -> set[str]:
    """Every option string of the fmsave parser and its command parsers."""
    option_strings: set[str] = set()
    pending_parsers: list[argparse.ArgumentParser] = [cli._build_parser()]
    while pending_parsers:
        parser = pending_parsers.pop()
        for action in parser._actions:
            option_strings.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                pending_parsers.extend(action.choices.values())
    return option_strings


def cli_command_parsers() -> dict[str, argparse.ArgumentParser]:
    """The command parsers of the fmsave parser, by command name."""
    for action in cli._build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the fmsave parser has no commands")


def export_table_choices_as_methods() -> set[str]:
    """The export table names as the reader methods they name, hyphens being underscores."""
    return {table_name.replace("-", "_") for table_name in export_table_choices()}


def export_table_choices() -> set[str]:
    """The table names the export command accepts."""
    for action in cli_command_parsers()["export"]._actions:
        if action.dest == "table":
            assert action.choices is not None
            return {str(table_name) for table_name in action.choices}
    raise AssertionError("the export command has no table argument")


def readme_line(line_prefix: str) -> str:
    """The one README line that starts with the prefix."""
    matching_lines = [line for line in README_TEXT.splitlines() if line.startswith(line_prefix)]
    assert len(matching_lines) == 1, f"expected one README line starting {line_prefix!r}"
    return matching_lines[0]


def readme_section(heading: str) -> str:
    """The README text under a level-two heading, up to the next level-two heading."""
    heading_match = re.search(rf"^{re.escape(heading)}[ \t]*$", README_TEXT, re.MULTILINE)
    assert heading_match, f"README has no {heading!r} heading"
    section_text = README_TEXT[heading_match.end() :]
    next_heading_match = re.search(r"^## ", section_text, re.MULTILINE)
    return section_text[: next_heading_match.start()] if next_heading_match else section_text


def backticked_names(line: str) -> list[str]:
    """The leading name of each backticked span; `write_csv/json` gives write_csv and write_json."""
    names: list[str] = []
    for span_text in BACKTICK_SPAN_PATTERN.findall(line):
        name_match = LEADING_NAME_PATTERN.match(span_text)
        if not name_match:
            continue
        first_name, *suffixes = name_match.group().split("/")
        names.append(first_name)
        shared_prefix = first_name[: first_name.rfind("_") + 1]
        names.extend(shared_prefix + suffix for suffix in suffixes)
    return names


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


def test_table_methods_line_names_public_table_attributes() -> None:
    public_names = {
        member_name for member_name in dir(fmsave.Table) if not member_name.startswith("_")
    }
    listed_names = set(backticked_names(readme_line(TABLE_METHODS_LINE_PREFIX))) - {"Table"}
    assert listed_names, "the Table methods line names no methods"
    assert listed_names <= public_names, sorted(listed_names - public_names)


def test_readme_long_options_exist() -> None:
    used_options = set(LONG_OPTION_PATTERN.findall(README_TEXT))
    assert used_options
    unknown_options = used_options - cli_option_strings()
    assert not unknown_options, sorted(unknown_options)


def test_readme_short_options_exist() -> None:
    used_options = set(SHORT_OPTION_PATTERN.findall(README_TEXT))
    assert "-o" in used_options
    unknown_options = used_options - cli_option_strings()
    assert not unknown_options, sorted(unknown_options)


def test_readme_commands_exist() -> None:
    console_commands = set(CONSOLE_COMMAND_PATTERN.findall("\n".join(console_blocks())))
    bullet_commands = set(COMMAND_BULLET_PATTERN.findall(readme_section(COMMAND_LINE_HEADING)))
    assert console_commands, "no fmsave commands in README console blocks"
    unknown_commands = (console_commands | bullet_commands) - set(cli_command_parsers())
    assert not unknown_commands, sorted(unknown_commands)


def test_readme_reader_list_names_every_reader() -> None:
    """The reader list is the README's inventory, so it has to be the whole of one."""
    listed_readers = set(READER_NAME_PATTERN.findall(readme_section(READER_HEADING)))
    assert (
        listed_readers | set(SAVE_CALL_PATTERN.findall(README_TEXT))
        == export_table_choices_as_methods()
    )


def test_disclaimer_appears_verbatim() -> None:
    assert DISCLAIMER in " ".join(README_TEXT.split())


def test_the_pitch_is_not_hidden_data_or_a_database_dump() -> None:
    """What this library is offered as, checked on the lines that do the offering.

    A headline promising hidden data on every player in the database is the pitch of a cheating
    tool, whatever the code underneath it does, and that framing is what would make this project
    somebody else's problem. The words themselves are fine and are used further down, where they
    tell a reader something true about what they get.

    This is the whole of what a test can honestly check here. The rest is a judgement about tone
    that belongs to whoever writes the page.
    """
    pitch_text = README_TEXT[: README_TEXT.index("\n## ")].casefold()
    claimed = [claim for claim in PITCH_CLAIMS if claim in pitch_text]
    assert not claimed, claimed


def test_whole_save_analysis_keeps_the_explicit_gate_and_online_warning() -> None:
    safety_text = readme_section("## Safety")
    command_line_text = readme_section(COMMAND_LINE_HEADING)

    assert "single-player" in safety_text
    assert "shared online career" in safety_text
    assert "--all" in command_line_text
    assert "`--all` is explicit" in command_line_text


def test_support_never_requests_or_accepts_save_files() -> None:
    support_text = readme_section("## Support")
    assert "not request or accept one" in support_text
