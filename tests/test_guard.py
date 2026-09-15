"""Tests for scripts/guard.py, run against throwaway git repositories."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "guard.py"


def load_guard_module() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("fmsave_guard", GUARD_PATH)
    assert module_spec is not None and module_spec.loader is not None
    guard_module = importlib.util.module_from_spec(module_spec)
    sys.modules["fmsave_guard"] = guard_module
    module_spec.loader.exec_module(guard_module)
    return guard_module


guard = load_guard_module()


def run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Example Tester",
            "-c",
            "user.email=tester@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *arguments,
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repository_path = tmp_path / "example repo"
    repository_path.mkdir()
    run_git(repository_path, "init", "-q", "-b", "main")
    return repository_path


def stage(repository: Path, relative_path: str, content: bytes | str) -> None:
    file_path = repository / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        file_path.write_text(content, encoding="utf-8")
    else:
        file_path.write_bytes(content)
    run_git(repository, "add", "-f", relative_path)


def write_object(repository: Path, content: bytes) -> str:
    """Write a blob to the object database without touching the index; return its id."""
    return (
        subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=repository,
            input=content,
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )


def stage_symbolic_link_entry(repository: Path, relative_path: str, target: str) -> str:
    """Stage a symbolic link entry through the index alone, so no platform link support is needed."""
    object_id = write_object(repository, target.encode("utf-8"))
    run_git(
        repository, "update-index", "--add", "--cacheinfo", f"120000,{object_id},{relative_path}"
    )
    return object_id


def run_guard(repository: Path, *arguments: str) -> int:
    return guard.main([*arguments, "--root", str(repository)])


def write_private(repository: Path, relative_path: str, content: str) -> None:
    private_path = repository / ".local" / relative_path
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(content, encoding="utf-8")


PRIVATE_PARAGRAPH = "\n".join(
    f"line {index}: the example ledger records a fictional transfer for Northbridge FC"
    for index in range(1, 8)
)
TRIVIAL_LINES = ["pass", "else:", "pass", "return", "end", "done", "ok"]
OUTPUT_CELL = {"cell_type": "code", "outputs": [{"text": "x"}], "source": []}


# Structural checks


def test_clean_text_file_passes(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repository, "src/example.py", "print('hello')\n")
    assert run_guard(repository, "--staged") == 0
    assert "structural checks only" in capsys.readouterr().err


def test_private_folder_path_is_blocked(repository: Path) -> None:
    stage(repository, ".local/example.md", "private\n")
    assert run_guard(repository, "--staged") == 1


def test_private_folder_path_is_blocked_in_any_case(repository: Path) -> None:
    stage(repository, ".LOCAL/note.md", "note\n")
    assert run_guard(repository, "--staged") == 1


def test_save_file_extension_is_blocked(repository: Path) -> None:
    stage(repository, "data/example.FM", "text\n")
    assert run_guard(repository, "--staged") == 1


def test_save_magic_and_binary_are_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "data/blob.bin", bytes.fromhex("0201666d662e0800") + b"\x00" * 8)
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err
    assert "magic" in error_output
    assert "binary" in error_output


def test_oversized_file_is_blocked(repository: Path) -> None:
    stage(repository, "data/large.txt", "a" * 1_000_001)
    assert run_guard(repository, "--staged") == 1


def test_oversized_file_is_not_scanned_for_encoded_runs(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "data/large.txt", encoded_run(HEX_ALPHABET, 1_000_001))
    assert run_guard(repository, "--staged") == 1
    assert capsys.readouterr().err.splitlines() == [
        "guard: data/large.txt: is larger than 1000000 bytes",
        blocked_line(1),
    ]


def test_notebook_outputs_are_blocked(repository: Path) -> None:
    with_outputs = {"cells": [OUTPUT_CELL]}
    without_outputs = {
        "cells": [{"cell_type": "code", "outputs": [], "execution_count": None, "source": []}]
    }
    stage(repository, "clean.ipynb", json.dumps(without_outputs))
    assert run_guard(repository, "--staged") == 0
    stage(repository, "dirty.ipynb", json.dumps(with_outputs))
    assert run_guard(repository, "--staged") == 1


@pytest.mark.parametrize(
    ("notebook_path", "notebook"),
    [
        ("DIRTY.IPYNB", {"cells": [OUTPUT_CELL]}),
        ("legacy.ipynb", {"nbformat": 3, "worksheets": [{"cells": [OUTPUT_CELL]}]}),
    ],
    ids=["uppercase-suffix", "nbformat-3"],
)
def test_notebook_outputs_are_blocked_in_other_forms(
    repository: Path, notebook_path: str, notebook: dict[str, object]
) -> None:
    stage(repository, notebook_path, json.dumps(notebook))
    assert run_guard(repository, "--staged") == 1


def test_clean_nbformat_3_notebook_passes(repository: Path) -> None:
    clean_cell = {"cell_type": "code", "outputs": [], "input": []}
    stage(
        repository,
        "legacy.ipynb",
        json.dumps({"nbformat": 3, "worksheets": [{"cells": [clean_cell]}]}),
    )
    assert run_guard(repository, "--staged") == 0


# Symbolic links

SYMBOLIC_LINK_REASON = "is a symbolic link"


@pytest.mark.skipif(sys.platform == "win32", reason="creating symbolic links needs extra rights")
def test_staged_symbolic_link_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link_path = repository / "docs" / "data"
    link_path.parent.mkdir()
    link_path.symlink_to("../elsewhere/corpus")
    run_git(repository, "add", "docs/data")
    assert run_guard(repository, "--staged") == 1
    assert f"docs/data: {SYMBOLIC_LINK_REASON}" in capsys.readouterr().err


def test_staged_symbolic_link_entry_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_symbolic_link_entry(repository, "docs/data", "../elsewhere/corpus")
    assert run_guard(repository, "--staged") == 1
    assert f"docs/data: {SYMBOLIC_LINK_REASON}" in capsys.readouterr().err


def test_tracked_symbolic_link_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "ok.txt", "fine\n")
    stage_symbolic_link_entry(repository, "docs/data", "../elsewhere/corpus")
    run_git(repository, "commit", "-q", "-m", "add link")
    stage(repository, "more.txt", "fine\n")
    assert run_guard(repository, "--staged") == 0
    assert run_guard(repository, "--tracked") == 1
    assert f"docs/data: {SYMBOLIC_LINK_REASON}" in capsys.readouterr().err


def test_symbolic_link_in_history_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_symbolic_link_entry(repository, "docs/data", "../elsewhere/corpus")
    run_git(repository, "commit", "-q", "-m", "add link")
    run_git(repository, "rm", "-q", "--cached", "docs/data")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "remove link")
    assert run_guard(repository, "--tracked") == 0
    capsys.readouterr()
    assert run_guard(repository, "--history") == 1
    assert SYMBOLIC_LINK_REASON in capsys.readouterr().err


def test_symbolic_link_with_the_content_of_a_history_file_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "target.txt", "shared text")
    stage_symbolic_link_entry(repository, "docs/link", "shared text")
    run_git(repository, "commit", "-q", "-m", "add file and link")
    assert run_guard(repository, "--history") == 1
    error_output = capsys.readouterr().err
    assert SYMBOLIC_LINK_REASON in error_output
    assert error_output.count(SYMBOLIC_LINK_REASON) == 1
    assert "target.txt" not in error_output


def test_symbolic_link_reachable_only_from_a_tag_is_blocked_in_history(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    stage_symbolic_link_entry(repository, "docs/data", "../elsewhere/corpus")
    tree_id = (
        subprocess.run(["git", "write-tree"], cwd=repository, check=True, capture_output=True)
        .stdout.decode("ascii")
        .strip()
    )
    run_git(repository, "tag", "tree-only", tree_id)
    run_git(repository, "rm", "-q", "--cached", "docs/data")
    assert run_guard(repository, "--tracked") == 0
    capsys.readouterr()
    assert run_guard(repository, "--history") == 1
    assert SYMBOLIC_LINK_REASON in capsys.readouterr().err


def test_regular_and_executable_files_are_not_symbolic_links(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repository, "docs/data", "../elsewhere/corpus")
    stage(repository, "scripts/run.sh", "echo ok\n")
    run_git(repository, "update-index", "--chmod=+x", "scripts/run.sh")
    assert run_guard(repository, "--staged") == 0
    run_git(repository, "commit", "-q", "-m", "add files")
    assert run_guard(repository, "--tracked") == 0
    assert run_guard(repository, "--history") == 0
    assert SYMBOLIC_LINK_REASON not in capsys.readouterr().err


# Submodules

SUBMODULE_REASON = "is a submodule"
SUBMODULE_COMMIT_ID = "1" * 40


def stage_submodule_entry(repository: Path, relative_path: str) -> None:
    """Stage a submodule entry through the index alone; its commit need not exist anywhere."""
    run_git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{SUBMODULE_COMMIT_ID},{relative_path}",
    )


def test_staged_submodule_is_blocked(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repository, "ok.txt", "fine\n")
    stage_submodule_entry(repository, "vendor/library")
    assert run_guard(repository, "--staged") == 1
    assert capsys.readouterr().err.splitlines() == [
        f"guard: vendor/library: {SUBMODULE_REASON}",
        blocked_line(1),
    ]


def test_tracked_submodule_is_blocked(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage_submodule_entry(repository, "vendor/library")
    run_git(repository, "commit", "-q", "-m", "add submodule")
    stage(repository, "ok.txt", "fine\n")
    assert run_guard(repository, "--staged") == 0
    capsys.readouterr()
    assert run_guard(repository, "--tracked") == 1
    assert capsys.readouterr().err.splitlines() == [
        f"guard: vendor/library: {SUBMODULE_REASON}",
        blocked_line(1),
    ]


def test_submodule_in_history_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_submodule_entry(repository, "vendor/library")
    run_git(repository, "commit", "-q", "-m", "add submodule")
    run_git(repository, "rm", "-q", "--cached", "vendor/library")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "remove submodule")
    assert run_guard(repository, "--tracked") == 0
    capsys.readouterr()
    assert run_guard(repository, "--history") == 1
    assert capsys.readouterr().err.splitlines() == [
        f"guard: vendor/library@{SUBMODULE_COMMIT_ID[:12]}: {SUBMODULE_REASON}",
        blocked_line(1),
    ]


# Long encoded runs

HEX_ALPHABET = "0123456789abcdefABCDEF"
BASE64_ALPHABET = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo+/_-="
STRUCTURAL_OK_LINE = "guard: ok (structural checks only)"
# A lookbehind for the repeated unit, then that unit (bare or in a group) repeated at least N times.
LOOKBEHIND_RUN_SHAPE = re.compile(r"\(\?<!(?P<unit>.+)\)(?:(?P=unit)|\(\?:(?P=unit)\))\{\d+,\}\+?")


def encoded_run(alphabet: str, length: int) -> str:
    return (alphabet * (length // len(alphabet) + 1))[:length]


def blocked_line(problem_count: int) -> str:
    return f"guard: {problem_count} problem(s) found; blocked"


def encoded_run_line(line_number: int, kind: str, length: int) -> str:
    reason = f"contains a long encoded run ({kind}, {length} characters)"
    return f"guard: data/payload.txt:{line_number}: {reason}"


@pytest.mark.parametrize(
    ("alphabet", "length", "kind", "expected_exit"),
    [
        (HEX_ALPHABET, 512, "hex", 1),
        (HEX_ALPHABET, 511, "hex", 0),
        (BASE64_ALPHABET, 1024, "base64", 1),
        (BASE64_ALPHABET, 1023, "base64", 0),
    ],
    ids=["hex-512", "hex-511", "base64-1024", "base64-1023"],
)
def test_long_encoded_run_is_blocked_at_its_threshold(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    alphabet: str,
    length: int,
    kind: str,
    expected_exit: int,
) -> None:
    run_text = encoded_run(alphabet, length)
    stage(repository, "data/payload.txt", f"first line\npayload = '{run_text}'\nlast line\n")
    assert run_guard(repository, "--staged") == expected_exit
    error_lines = capsys.readouterr().err.splitlines()
    reason = f"contains a long encoded run ({kind}, {length} characters)"
    if expected_exit:
        assert error_lines == [f"guard: data/payload.txt:2: {reason}", blocked_line(1)]
    else:
        assert error_lines == [STRUCTURAL_OK_LINE]


def test_long_hex_run_is_reported_once_as_hex(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_text = encoded_run(HEX_ALPHABET, 2048)
    stage(repository, "data/payload.txt", run_text + "\n")
    assert run_guard(repository, "--staged") == 1
    assert capsys.readouterr().err.splitlines() == [
        "guard: data/payload.txt:1: contains a long encoded run (hex, 2048 characters)",
        blocked_line(1),
    ]


@pytest.mark.parametrize(
    "pattern_name",
    [
        "HEX_RUN_PATTERN",
        "BASE64_RUN_PATTERN",
        "WRAPPED_BASE64_LINE_PATTERN",
        "URLSAFE_BASE64_LINE_PATTERN",
        "ESCAPED_BYTE_RUN_PATTERN",
    ],
)
def test_encoded_run_pattern_starts_only_where_no_run_character_precedes(pattern_name: str) -> None:
    """Without the leading lookbehind, every position inside a short run would be rescanned."""
    pattern_text = getattr(guard, pattern_name).pattern
    assert LOOKBEHIND_RUN_SHAPE.fullmatch(pattern_text) is not None, pattern_text


def test_hex_pair_pattern_repeats_possessively_without_a_minimum_count() -> None:
    """Each sequence is matched once, whole, and its pairs are counted afterwards."""
    pattern_text = guard.HEX_PAIR_SEQUENCE_PATTERN.pattern
    assert pattern_text.startswith("(?<![0-9A-Za-z])"), pattern_text
    assert pattern_text.endswith(")*+"), pattern_text
    assert "[\\s,:]++" in pattern_text, pattern_text
    assert re.search(r"\{\d*,?\d*\}", pattern_text.replace("{2}", "")) is None, pattern_text


def wrap_columns(text: str, width: int) -> list[str]:
    return [text[start : start + width] for start in range(0, len(text), width)]


def standard_base64(byte_count: int) -> str:
    return base64.b64encode(bytes(value % 256 for value in range(byte_count))).decode("ascii")


def encodebytes_text(byte_count: int) -> str:
    """Output of `base64.encodebytes`: 76-column lines."""
    encoded = base64.encodebytes(bytes(value % 256 for value in range(byte_count)))
    return encoded.decode("ascii").rstrip("\n")


def hex_pairs(count: int) -> list[str]:
    return [f"{value:02x}" for value in range(count)]


def escaped_bytes(count: int) -> str:
    return "".join(f"\\x{value:02x}" for value in range(count))


def sample_bytes(byte_count: int, seed: int = 0) -> bytes:
    """Deterministic bytes whose hex form holds a-f digits."""
    blocks = b"".join(
        hashlib.sha256(f"{seed}:{index}".encode("ascii")).digest()
        for index in range(byte_count // 32 + 1)
    )
    return blocks[:byte_count]


def urlsafe_base64_line(width: int, seed: int, padded: bool = False) -> str:
    """One URL-safe base64 line with `-_-_` in its middle, so no standard base64 run fills it."""
    byte_count = width * 3 // 4 - int(padded)
    middle = byte_count // 2 // 3 * 3
    chunk = bytearray(sample_bytes(byte_count, seed))
    chunk[middle : middle + 3] = b"\xfb\xff\xbf"
    return base64.urlsafe_b64encode(bytes(chunk)).decode("ascii")


def urlsafe_base64_lines(width: int, template: str = "{line}") -> str:
    return "\n".join(template.format(line=urlsafe_base64_line(width, seed)) for seed in range(4))


def hyphenated_lines(alphabet: str, width: int = 76) -> str:
    """Four lines cycled from `alphabet`, each with one hyphen in its middle."""
    line = encoded_run(alphabet, width - 1)
    return "\n".join([line[: width // 2] + "-" + line[width // 2 :]] * 4)


def hex_lines(line_count: int, width: int = 64) -> str:
    return "\n".join(wrap_columns(sample_bytes(line_count * width // 2).hex(), width))


WRAPPED_BASE64_CASES = {
    "encodebytes-4-lines": (encodebytes_text(228), (2, "wrapped base64", 304)),
    "encodebytes-3-lines": (encodebytes_text(171), None),
    "encodebytes-short-last-line": (encodebytes_text(520), (2, "wrapped base64", 684)),
    "pem-64-columns": (
        "\n".join(
            [
                "-----BEGIN EXAMPLE DATA-----",
                *wrap_columns(standard_base64(192), 64),
                "-----END EXAMPLE DATA-----",
            ]
        ),
        (3, "wrapped base64", 256),
    ),
    "quoted-source-lines": (
        "\n".join(f'    "{line}"' for line in wrap_columns(standard_base64(228), 76)),
        (2, "wrapped base64", 304),
    ),
    "bytes-literal-lines": (
        "\n".join(f'    b"{line}\\n"' for line in wrap_columns(standard_base64(228), 76)),
        (2, "wrapped base64", 304),
    ),
    "eight-other-characters": (
        "\n".join(f"(((({line}))))" for line in wrap_columns(standard_base64(228), 76)),
        (2, "wrapped base64", 304),
    ),
    "nine-other-characters": (
        "\n".join(f"((((({line}))))" for line in wrap_columns(standard_base64(228), 76)),
        None,
    ),
    "40-column-lines": (
        "\n".join(wrap_columns(standard_base64(120), 40)),
        (2, "wrapped base64", 160),
    ),
    "39-column-lines": ("\n".join(wrap_columns(standard_base64(117), 39)), None),
    "keyword-argument-lines": (
        "\n".join(
            ["        example_total_with_a_long_descriptive_name=example_total_with_a_long_name,"]
            * 6
        ),
        None,
    ),
    "hex-digest-list": (
        "\n".join(f'    "{sample_bytes(32, seed).hex()}",' for seed in range(6)),
        None,
    ),
    "hex-commit-list": ("\n".join(sample_bytes(20, seed).hex() for seed in range(4)), None),
    "hex-wrapped-448-characters": (hex_lines(7), None),
    "hex-wrapped-512-characters": (hex_lines(8), (2, "wrapped hex", 512)),
    "hex-lines-and-one-base64-line": (
        "\n".join([hex_lines(3), standard_base64(57)]),
        (2, "wrapped base64", 268),
    ),
    "urlsafe-76-columns": (urlsafe_base64_lines(76), (2, "wrapped base64", 304)),
    "urlsafe-64-columns": (urlsafe_base64_lines(64), (2, "wrapped base64", 256)),
    "urlsafe-quoted-76-columns": (
        urlsafe_base64_lines(76, '    "{line}"'),
        (2, "wrapped base64", 304),
    ),
    "urlsafe-quoted-64-columns": (
        urlsafe_base64_lines(64, '    "{line}",'),
        (2, "wrapped base64", 256),
    ),
    "urlsafe-bytes-literal-76-columns": (
        urlsafe_base64_lines(76, '    b"{line}"'),
        (2, "wrapped base64", 304),
    ),
    "urlsafe-bytes-literal-64-columns": (
        urlsafe_base64_lines(64, '    b"{line}"'),
        (2, "wrapped base64", 256),
    ),
    "urlsafe-padded-last-line": (
        "\n".join(
            [
                *(urlsafe_base64_line(76, seed) for seed in range(3)),
                urlsafe_base64_line(76, 3, padded=True),
            ]
        ),
        (2, "wrapped base64", 304),
    ),
    "urlsafe-eight-other-characters": (
        urlsafe_base64_lines(76, "(((({line}))))"),
        (2, "wrapped base64", 304),
    ),
    "urlsafe-nine-other-characters": (urlsafe_base64_lines(76, "((((({line}))))"), None),
    "urlsafe-without-uppercase": (hyphenated_lines("abcdefghijklmnopqrstuvwxyz0123456789"), None),
    "urlsafe-without-lowercase": (hyphenated_lines("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"), None),
    "urlsafe-without-digits": (
        hyphenated_lines("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),
        None,
    ),
    "snake-case-names-with-digits": (
        "\n".join(
            f"    test_reads_Example_contract_clause_bonus_v{index}_layout_bytes_2026,"
            for index in range(5)
        ),
        None,
    ),
}


@pytest.mark.parametrize(
    ("payload", "expected"), WRAPPED_BASE64_CASES.values(), ids=WRAPPED_BASE64_CASES.keys()
)
def test_wrapped_base64_is_blocked_from_four_lines(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    payload: str,
    expected: tuple[int, str, int] | None,
) -> None:
    stage(repository, "data/payload.txt", f"first line\n{payload}\nlast line\n")
    if expected is None:
        assert run_guard(repository, "--staged") == 0
        assert capsys.readouterr().err.splitlines() == [STRUCTURAL_OK_LINE]
        return
    line_number, kind, length = expected
    assert run_guard(repository, "--staged") == 1
    assert capsys.readouterr().err.splitlines() == [
        encoded_run_line(line_number, kind, length),
        blocked_line(1),
    ]


HEX_PAIR_CASES = {
    "spaces-64": (" ".join(hex_pairs(64)), True),
    "spaces-63": (" ".join(hex_pairs(63)), False),
    "prefixed-commas-64": (", ".join(f"0x{pair.upper()}" for pair in hex_pairs(64)), True),
    "prefixed-commas-63": (", ".join(f"0x{pair}" for pair in hex_pairs(63)), False),
    "colons-64": (":".join(hex_pairs(64)), True),
    "wrapped-16-per-line": (
        ",\n    ".join(
            ", ".join(f"0x{pair}" for pair in hex_pairs(64)[start : start + 16])
            for start in range(0, 64, 16)
        ),
        True,
    ),
    "prefixed-decimal-digits-64": (", ".join(f"0x{10 + index}" for index in range(64)), True),
    "decimal-digits-64": (" ".join(str(10 + index) for index in range(64)), False),
    "decimal-values-70": (", ".join(str(10 + index % 30) for index in range(70)), False),
    "timestamps-22": (
        "\n".join(f"{10 + index % 14}:{10 + index % 50}:{59 - index}" for index in range(22)),
        False,
    ),
}


@pytest.mark.parametrize(
    ("pairs_text", "reported"), HEX_PAIR_CASES.values(), ids=HEX_PAIR_CASES.keys()
)
def test_separated_hex_byte_pairs_are_blocked_from_64_pairs(
    repository: Path, capsys: pytest.CaptureFixture[str], pairs_text: str, reported: bool
) -> None:
    stage(repository, "data/payload.txt", f"first line\npayload = [{pairs_text}]\nlast line\n")
    assert run_guard(repository, "--staged") == int(reported)
    expected_lines = (
        [encoded_run_line(2, "hex byte pairs", len(pairs_text)), blocked_line(1)]
        if reported
        else [STRUCTURAL_OK_LINE]
    )
    assert capsys.readouterr().err.splitlines() == expected_lines


@pytest.mark.parametrize(("escape_count", "reported"), [(32, True), (31, False)])
def test_escaped_bytes_are_blocked_from_32_escapes(
    repository: Path, capsys: pytest.CaptureFixture[str], escape_count: int, reported: bool
) -> None:
    stage(
        repository,
        "data/payload.txt",
        f'first line\npayload = b"{escaped_bytes(escape_count)}"\nlast line\n',
    )
    assert run_guard(repository, "--staged") == int(reported)
    expected_lines = (
        [encoded_run_line(2, "escaped bytes", 4 * escape_count), blocked_line(1)]
        if reported
        else [STRUCTURAL_OK_LINE]
    )
    assert capsys.readouterr().err.splitlines() == expected_lines


def printable_column(row: bytes) -> str:
    return "".join(chr(value) if 32 <= value < 127 else "." for value in row)


def xxd_dump(data: bytes, group_bytes: int = 2) -> str:
    """The layout of `xxd` (two-byte groups) or `xxd -g1` (single bytes)."""
    width = 32 + 16 // group_bytes - 1
    lines: list[str] = []
    for offset in range(0, len(data), 16):
        row = data[offset : offset + 16]
        groups = " ".join(
            row[start : start + group_bytes].hex() for start in range(0, 16, group_bytes)
        )
        lines.append(f"{offset:08x}: {groups:<{width}}  {printable_column(row)}")
    return "\n".join(lines)


def hexdump_canonical_row(offset: int, row: bytes) -> str:
    """One row of `hexdump -C`."""
    pairs = [f"{value:02x}" for value in row]
    hex_column = f"{' '.join(pairs[:8]):<23}  {' '.join(pairs[8:]):<23}"
    return f"{offset:08x}  {hex_column}  |{printable_column(row)}|"


def bsd_od_row(offset: int, row: bytes) -> str:
    """One row of BSD `od -Ax -tx1`."""
    return f"{offset:07x}  " + "".join(f"  {value:02x}" for value in row)


def gnu_od_row(offset: int, row: bytes) -> str:
    """One row of GNU `od -Ax -tx1`."""
    return f"{offset:06x}" + "".join(f" {value:02x}" for value in row)


def collapsed_dump(data: bytes, format_row: Callable[[int, bytes], str], offset_width: int) -> str:
    """Rows as `hexdump` and `od` print them: repeated rows become one `*`, then the length."""
    lines: list[str] = []
    previous_row: bytes | None = None
    for offset in range(0, len(data), 16):
        row = data[offset : offset + 16]
        if row == previous_row:
            if lines[-1] != "*":
                lines.append("*")
            continue
        previous_row = row
        lines.append(format_row(offset, row))
    lines.append(f"{len(data):0{offset_width}x}")
    return "\n".join(lines)


DUMP_DATA = sample_bytes(256)
REPEATED_ROW_DUMP_DATA = sample_bytes(64) + bytes(48) + sample_bytes(32, seed=1)
DECIMAL_DIGIT_DUMP_DATA = bytes(
    value for value in range(256) if value >> 4 < 10 and value & 15 < 10
)[:96]
HEX_DUMP_CASES = {
    "xxd": (xxd_dump(DUMP_DATA), ("hex dump", 512)),
    "xxd-single-bytes": (xxd_dump(DUMP_DATA, group_bytes=1), ("hex dump", 512)),
    "xxd-64-bytes": (xxd_dump(DUMP_DATA[:64]), ("hex dump", 128)),
    "xxd-48-bytes": (xxd_dump(DUMP_DATA[:48]), None),
    "hexdump-canonical": (collapsed_dump(DUMP_DATA, hexdump_canonical_row, 8), ("hex dump", 512)),
    "hexdump-canonical-with-repeated-rows": (
        collapsed_dump(REPEATED_ROW_DUMP_DATA, hexdump_canonical_row, 8),
        ("hex dump", 224),
    ),
    "bsd-od": (collapsed_dump(DUMP_DATA, bsd_od_row, 7), ("hex dump", 512)),
    "gnu-od": (collapsed_dump(DUMP_DATA, gnu_od_row, 6), ("hex dump", 512)),
    "four-byte-groups-without-offsets": (
        "\n".join(DUMP_DATA[offset : offset + 16].hex(" ", 4) for offset in range(0, 256, 16)),
        ("hex dump", 512),
    ),
    "byte-pairs-without-offsets": (
        "\n".join(" " + DUMP_DATA[offset : offset + 16].hex(" ") for offset in range(0, 256, 16)),
        ("hex byte pairs", 16 * 47 + 15 * 2),
    ),
    "decimal-digits-only": (
        collapsed_dump(DECIMAL_DIGIT_DUMP_DATA, hexdump_canonical_row, 8),
        None,
    ),
    "three-groups-per-line": (
        "\n".join(
            f"{offset:08x}: " + DUMP_DATA[offset : offset + 6].hex(" ", 2)
            for offset in range(0, 240, 6)
        ),
        None,
    ),
}


@pytest.mark.parametrize(
    ("dump_text", "expected"), HEX_DUMP_CASES.values(), ids=HEX_DUMP_CASES.keys()
)
def test_hex_dumps_are_blocked_from_64_bytes(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    dump_text: str,
    expected: tuple[str, int] | None,
) -> None:
    stage(repository, "data/payload.txt", f"first line\n{dump_text}\nlast line\n")
    if expected is None:
        assert run_guard(repository, "--staged") == 0
        assert capsys.readouterr().err.splitlines() == [STRUCTURAL_OK_LINE]
        return
    kind, length = expected
    assert run_guard(repository, "--staged") == 1
    assert capsys.readouterr().err.splitlines() == [
        encoded_run_line(2, kind, length),
        blocked_line(1),
    ]


LONG_LINE_CASES = {
    "four-digit-groups": ("a1b2 " * 20_000, [("hex dump", 80_000)]),
    "eight-digit-groups": ("a1b2c3d4 " * 11_112, [("hex dump", 88_896)]),
    "pairs-then-a-word": ("ab " * 33_334 + "x", [("hex byte pairs", 100_001)]),
    "offset-pairs-and-text-column": (
        "00000000: " + "ab " * 33_330 + "|x|",
        [("hex byte pairs", 99_989)],
    ),
    "nine-digit-tokens": ("a1b2c3d4e " * 10_000, []),
    "odd-three-digit-groups": ("a1b " * 25_000, []),
    "single-hex-digits": ("a " * 50_000, []),
    "decimal-digit-groups": ("1234 " * 20_000, []),
    "offset-long-blanks-then-four-groups": (
        "00000000:" + " " * 100_000 + "a1b2 c3d4 e5f6 a7b8",
        [],
    ),
}


@pytest.mark.parametrize(("line", "expected"), LONG_LINE_CASES.values(), ids=LONG_LINE_CASES.keys())
def test_hundred_thousand_character_lines_are_scanned_exactly(
    line: str, expected: list[tuple[str, int]]
) -> None:
    assert len(line) >= 100_000
    findings = guard.encoded_run_findings("data/payload.txt", line)
    assert [(finding.location, finding.reason) for finding in findings] == [
        ("data/payload.txt:1", f"contains a long encoded run ({kind}, {length} characters)")
        for kind, length in expected
    ]


def test_repeated_runs_just_under_every_threshold_are_not_reported() -> None:
    near_miss_blocks = [
        encoded_run(HEX_ALPHABET, 511) + "g",
        encoded_run(BASE64_ALPHABET, 1023) + ".",
        "\n".join(wrap_columns(standard_base64(171), 76)),
        " ".join(hex_pairs(63)) + " .",
        escaped_bytes(31) + ".",
        xxd_dump(DUMP_DATA[:48]),
    ]
    text = ("\n--\n".join(near_miss_blocks) + "\n--\n") * 50
    assert guard.encoded_run_findings("data/payload.txt", text) == []


def test_lock_file_with_many_hashes_passes(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hashes = [f"{index:064x}"[::-1] for index in range(1, 301)]
    wheel_lines = [
        f'    {{ url = "https://files.example.org/packages/{sha[:2]}/{sha[2:4]}/{sha[4:]}'
        f'/example_package-1.{index}.0-py3-none-any.whl", hash = "sha256:{sha}", size = 1024 }},'
        for index, sha in enumerate(hashes)
    ]
    joined_hashes = '","'.join(f"sha256:{sha}" for sha in hashes)
    lock_text = "\n".join(
        ["version = 1", "[[package]]", 'name = "example-package"', "wheels = [", *wheel_lines, "]"]
    )
    stage(repository, "uv.lock", f'{lock_text}\nhashes = ["{joined_hashes}"]\n')
    assert run_guard(repository, "--staged") == 0
    assert "long encoded run" not in capsys.readouterr().err


# Staged changes


def test_staged_rename_is_checked(repository: Path) -> None:
    stage(repository, "notes.txt", "text\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    (repository / "data").mkdir()
    run_git(repository, "mv", "notes.txt", "data/example.fm")
    assert run_guard(repository, "--staged") == 1


def test_staged_typechange_from_symlink_is_checked(repository: Path) -> None:
    link_path = repository / "notes.txt"
    link_path.symlink_to("missing-target.txt")
    run_git(repository, "add", "notes.txt")
    run_git(repository, "commit", "-q", "-m", "add link")
    link_path.unlink()
    stage(repository, "notes.txt", bytes.fromhex("0201666d662e"))
    assert run_guard(repository, "--staged") == 1


# Text copied from the private folder


def test_six_lines_copied_from_private_folder_are_blocked(repository: Path) -> None:
    write_private(repository, "research/example.md", PRIVATE_PARAGRAPH)
    copied_lines = PRIVATE_PARAGRAPH.splitlines()[:6]
    stage(repository, "docs/copied.md", "\n\n".join(copied_lines) + "\n")
    assert run_guard(repository, "--staged") == 1


def test_five_copied_lines_pass(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_private(repository, "research/example.md", PRIVATE_PARAGRAPH)
    stage(repository, "docs/copied.md", "\n".join(PRIVATE_PARAGRAPH.splitlines()[:5]) + "\n")
    assert run_guard(repository, "--staged") == 0
    assert "private references" in capsys.readouterr().err


def test_copied_trivial_lines_below_alphanumeric_minimum_pass(repository: Path) -> None:
    write_private(repository, "research/example.md", "\n".join(TRIVIAL_LINES))
    stage(repository, "src/copied.py", "\n".join(TRIVIAL_LINES[:6]) + "\n")
    assert run_guard(repository, "--staged") == 0


def test_exempt_code_fences_may_be_reused_but_prose_may_not(repository: Path) -> None:
    fenced_code = "\n".join(
        f"example_value_{index} = compute_example_total({index}, 'Northbridge FC')"
        for index in range(8)
    )
    write_private(repository, "guard.json", json.dumps({"overlap_exempt_code_fences": ["notes/*"]}))
    write_private(
        repository, "notes/plan.md", f"{PRIVATE_PARAGRAPH}\n```python\n{fenced_code}\n```\n"
    )
    stage(repository, "src/reused.py", fenced_code + "\n")
    assert run_guard(repository, "--staged") == 0
    stage(repository, "docs/prose.md", PRIVATE_PARAGRAPH + "\n")
    assert run_guard(repository, "--staged") == 1


@pytest.mark.parametrize(
    "private_document",
    [
        f"```text\nexample code\n~~~\nexample code\n```\n{PRIVATE_PARAGRAPH}\n",
        f"````text\nexample code\n```\nexample code\n````\n{PRIVATE_PARAGRAPH}\n",
        f"```text\n{PRIVATE_PARAGRAPH}\n",
        f"    ```\n{PRIVATE_PARAGRAPH}\n    ```\n",
    ],
    ids=[
        "tilde-does-not-close-backticks",
        "shorter-fence-does-not-close",
        "unclosed-fence",
        "four-space-indent-is-not-a-fence",
    ],
)
def test_prose_outside_closed_code_fences_is_not_exempt(
    repository: Path, private_document: str
) -> None:
    write_private(repository, "guard.json", json.dumps({"overlap_exempt_code_fences": ["notes/*"]}))
    write_private(repository, "notes/plan.md", private_document)
    stage(repository, "docs/prose.md", PRIVATE_PARAGRAPH + "\n")
    assert run_guard(repository, "--staged") == 1


# Denylisted names and uids, and denied terms


def test_denylisted_name_is_blocked_without_printing_it(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", "# test list\nAlex Example\n")
    stage(repository, "ok.txt", "Alex went home.\n")
    assert run_guard(repository, "--staged") == 0
    stage(repository, "name.txt", "Signed: alex   EXAMPLE\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err
    assert "Alex" not in error_output
    assert "EXAMPLE" not in error_output


def test_denylisted_uid_is_blocked_without_printing_it(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", "# test list\n12345678\n")
    stage(repository, "ok.txt", "123456789 is a different number.\n")
    assert run_guard(repository, "--staged") == 0
    stage(repository, "uid.txt", "uid=12345678\n")
    assert run_guard(repository, "--staged") == 1
    assert "12345678" not in capsys.readouterr().err


def test_denylisted_uid_inside_hash_like_token_passes(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "12345678\n")
    stage(repository, "hashes.txt", "sha256:ab12345678cd\n")
    assert run_guard(repository, "--staged") == 0


@pytest.mark.parametrize("uid_text", ["12345678", "uid_12345678", "(12345678)"])
def test_delimited_denylisted_uid_is_blocked(repository: Path, uid_text: str) -> None:
    write_private(repository, "corpus/denylist.txt", "12345678\n")
    stage(repository, "uid.txt", f"{uid_text}\n")
    assert run_guard(repository, "--staged") == 1


def test_denylisted_name_across_a_line_break_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "wrapped.md", "Thanks to Alex\nExample for the fixtures.\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err
    assert "wrapped.md:1: contains a denylisted name" in error_output
    assert "alex" not in error_output.casefold()
    assert "example" not in error_output.casefold()


def test_denied_term_across_a_line_break_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "guard.json", json.dumps({"denied_terms": ["example codename"]}))
    stage(repository, "wrapped.md", "Plans for the example\n   codename rollout.\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err
    assert "wrapped.md:1: contains a denied internal term" in error_output
    assert "codename" not in error_output.casefold()


@pytest.mark.parametrize(
    "staged_path",
    ["tests/fixtures/alex_example.json", "docs/internal-codename.md", "data/12345678.json"],
    ids=["name", "term", "uid"],
)
def test_denylisted_path_is_blocked_without_printing_it(
    repository: Path, capsys: pytest.CaptureFixture[str], staged_path: str
) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n12345678\n")
    write_private(repository, "guard.json", json.dumps({"denied_terms": ["internal-codename"]}))
    stage(repository, staged_path, "{}\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err.casefold()
    assert "path withheld" in error_output
    for matched_text in ("alex", "example", "codename", "12345678"):
        assert matched_text not in error_output


PUNCTUATED_DENYLIST = "Jean-Luc Example\nJ.R. Example\n"
PUNCTUATED_NAME_PARTS = ("example", "jean", "j.r", "luc")


@pytest.mark.parametrize(
    "staged_path",
    [
        "tests/fixtures/jean-luc_example.json",
        "tests/fixtures/jean-luc-example.json",
        "docs/j.r._example.md",
    ],
    ids=["hyphen-then-underscore", "hyphens-only", "dotted-initials"],
)
def test_hyphenated_or_dotted_denylisted_name_in_path_is_blocked(
    repository: Path, capsys: pytest.CaptureFixture[str], staged_path: str
) -> None:
    write_private(repository, "corpus/denylist.txt", PUNCTUATED_DENYLIST)
    stage(repository, staged_path, "{}\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err.casefold()
    assert "path withheld" in error_output
    for matched_text in PUNCTUATED_NAME_PARTS:
        assert matched_text not in error_output


def test_save_file_named_after_hyphenated_denylisted_name_does_not_print_it(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", PUNCTUATED_DENYLIST)
    stage(repository, "data/jean-luc_example.fm", "text\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err.casefold()
    assert "save file" in error_output
    for matched_text in PUNCTUATED_NAME_PARTS:
        assert matched_text not in error_output


@pytest.mark.parametrize("signed_name", ["Jean-Luc Example", "J.R. Example"])
def test_hyphenated_or_dotted_denylisted_name_in_content_is_blocked(
    repository: Path, signed_name: str
) -> None:
    write_private(repository, "corpus/denylist.txt", PUNCTUATED_DENYLIST)
    stage(repository, "signed.txt", f"Signed: {signed_name}\n")
    assert run_guard(repository, "--staged") == 1


def test_denylisted_path_is_blocked_in_tracked_and_history_modes(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "tests/fixtures/alex_example.json", "{}\n")
    run_git(repository, "commit", "-q", "-m", "add fixture")
    assert run_guard(repository, "--tracked") == 1
    run_git(repository, "rm", "-q", "tests/fixtures/alex_example.json")
    run_git(repository, "commit", "-q", "-m", "remove fixture")
    assert run_guard(repository, "--tracked") == 0
    assert run_guard(repository, "--history") == 1


@pytest.mark.parametrize(
    "signed_name", ["Jose\u0301 Example", "Jose Example"], ids=["decomposed", "unaccented"]
)
def test_denylisted_name_matches_other_unicode_forms(repository: Path, signed_name: str) -> None:
    write_private(repository, "corpus/denylist.txt", "Jos\u00e9 Example\n")
    stage(repository, "signed.txt", f"Signed: {signed_name}\n")
    assert run_guard(repository, "--staged") == 1


def test_denied_term_matches_unaccented_text(repository: Path) -> None:
    write_private(repository, "guard.json", json.dumps({"denied_terms": ["caf\u00e9-codename"]}))
    stage(repository, "plan.txt", "see CAFE-CODENAME\n")
    assert run_guard(repository, "--staged") == 1


def test_fullwidth_denylisted_uid_is_blocked(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "12345678\n")
    stage(repository, "uid.txt", "uid \uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\n")
    assert run_guard(repository, "--staged") == 1


def test_denied_terms_are_blocked_in_files_and_messages(repository: Path, tmp_path: Path) -> None:
    write_private(repository, "guard.json", json.dumps({"denied_terms": ["internal-codename"]}))
    stage(repository, "ok.txt", "an internal codename discussion\n")
    assert run_guard(repository, "--staged") == 0
    stage(repository, "bad.txt", "see Internal-Codename notes\n")
    assert run_guard(repository, "--staged") == 1
    message_path = tmp_path / "message.txt"
    message_path.write_text("Fix parser (internal-codename)\n", encoding="utf-8")
    assert run_guard(repository, "--commit-msg", str(message_path)) == 1
    message_path.write_text("Fix parser\n", encoding="utf-8")
    assert run_guard(repository, "--commit-msg", str(message_path)) == 0


def test_commit_message_denylist(repository: Path, tmp_path: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    message_path = tmp_path / "message.txt"
    message_path.write_text("Add example for Alex Example\n", encoding="utf-8")
    assert run_guard(repository, "--commit-msg", str(message_path)) == 1


def test_commit_message_passes_without_private_folder(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message_path = tmp_path / "message.txt"
    message_path.write_text("Add example for Alex Example\n", encoding="utf-8")
    assert run_guard(repository, "--commit-msg", str(message_path)) == 0
    assert "structural checks only" in capsys.readouterr().err


# Private configuration files


def test_byte_order_mark_in_denylist_does_not_hide_first_uid(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "\ufeff12345678\n")
    stage(repository, "uid.txt", "uid=12345678\n")
    assert run_guard(repository, "--staged") == 1


def test_byte_order_mark_in_guard_config_is_accepted(repository: Path) -> None:
    config_text = "\ufeff" + json.dumps({"denied_terms": ["internal-codename"]})
    write_private(repository, "guard.json", config_text)
    stage(repository, "bad.txt", "see internal-codename notes\n")
    assert run_guard(repository, "--staged") == 1


@pytest.mark.parametrize(
    "config",
    [
        {"denied_term": ["internal-codename"]},
        {"denied_terms": "internal-codename"},
        {"overlap_exempt_code_fences": [1]},
        ["internal-codename"],
    ],
    ids=["unknown-key", "string-instead-of-list", "non-string-item", "not-an-object"],
)
def test_invalid_guard_config_exits_with_a_clear_message(repository: Path, config: object) -> None:
    write_private(repository, "guard.json", json.dumps(config))
    stage(repository, "ok.txt", "fine\n")
    with pytest.raises(SystemExit) as exit_information:
        run_guard(repository, "--staged")
    assert "guard.json" in str(exit_information.value)


# Repository modes


def test_linked_worktree_uses_private_folder_of_main_worktree(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    linked_worktree = tmp_path / "linked worktree"
    run_git(repository, "worktree", "add", "-q", "-b", "linked", str(linked_worktree))
    stage(linked_worktree, "credits.txt", "Thanks Alex Example\n")
    monkeypatch.chdir(linked_worktree)
    assert guard.main(["--staged"]) == 1


def test_tracked_mode_checks_committed_files(repository: Path) -> None:
    stage(repository, "data/example.fm", "text\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    assert run_guard(repository, "--tracked") == 1


def test_tracked_mode_applies_private_references(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    assert run_guard(repository, "--tracked") == 0
    assert "structural checks and private references" in capsys.readouterr().err
    stage(repository, "credits.txt", "Thanks Alex Example\n")
    run_git(repository, "commit", "-q", "-m", "add credits")
    assert run_guard(repository, "--tracked") == 1


def test_history_mode_finds_deleted_files_and_messages(repository: Path) -> None:
    stage(repository, "data/example.fm", "text\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    run_git(repository, "rm", "-q", "data/example.fm")
    run_git(repository, "commit", "-q", "-m", "remove file")
    assert run_guard(repository, "--tracked") == 0
    assert run_guard(repository, "--history") == 1


def test_history_mode_checks_every_path_of_a_shared_blob(repository: Path) -> None:
    stage(repository, "ok.txt", "same content\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    stage(repository, "data/example.fm", "same content\n")
    run_git(repository, "commit", "-q", "-m", "add copy")
    run_git(repository, "rm", "-q", "data/example.fm")
    run_git(repository, "commit", "-q", "-m", "remove copy")
    assert run_guard(repository, "--tracked") == 0
    assert run_guard(repository, "--history") == 1


@pytest.mark.parametrize("becomes_link", [True, False], ids=["file-to-link", "file-to-executable"])
def test_history_mode_reports_a_path_once_when_only_its_mode_changes(
    repository: Path, capsys: pytest.CaptureFixture[str], becomes_link: bool
) -> None:
    run_text = encoded_run(HEX_ALPHABET, 512)
    stage(repository, "docs/data", run_text)
    run_git(repository, "commit", "-q", "-m", "add file")
    if becomes_link:
        object_id = stage_symbolic_link_entry(repository, "docs/data", run_text)
    else:
        object_id = write_object(repository, run_text.encode("utf-8"))
        run_git(repository, "update-index", "--chmod=+x", "docs/data")
    run_git(repository, "commit", "-q", "-m", "change mode")
    assert run_guard(repository, "--history") == 1
    location = f"guard: docs/data@{object_id[:12]}"
    link_lines = [f"{location}: {SYMBOLIC_LINK_REASON}"] if becomes_link else []
    assert capsys.readouterr().err.splitlines() == [
        *link_lines,
        f"{location}:1: contains a long encoded run (hex, 512 characters)",
        blocked_line(len(link_lines) + 1),
    ]


def test_history_mode_reports_a_link_that_later_becomes_a_file_with_the_same_content(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_text = encoded_run(HEX_ALPHABET, 512)
    object_id = stage_symbolic_link_entry(repository, "docs/data", run_text)
    run_git(repository, "commit", "-q", "-m", "add link")
    run_git(repository, "rm", "-q", "--cached", "docs/data")
    stage(repository, "docs/data", run_text)
    run_git(repository, "commit", "-q", "-m", "replace link with file")
    assert run_guard(repository, "--history") == 1
    location = f"guard: docs/data@{object_id[:12]}"
    assert capsys.readouterr().err.splitlines() == [
        f"{location}: {SYMBOLIC_LINK_REASON}",
        f"{location}:1: contains a long encoded run (hex, 512 characters)",
        blocked_line(2),
    ]


@pytest.mark.parametrize(
    "tag_options", [[], ["-a", "-m", "tagged payload"]], ids=["lightweight", "annotated"]
)
def test_history_mode_checks_a_blob_reachable_only_from_a_tag(
    repository: Path, capsys: pytest.CaptureFixture[str], tag_options: list[str]
) -> None:
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    object_id = write_object(repository, (encoded_run(HEX_ALPHABET, 512) + "\n").encode("utf-8"))
    run_git(repository, "tag", *tag_options, "payload", object_id)
    assert run_guard(repository, "--tracked") == 0
    capsys.readouterr()
    assert run_guard(repository, "--history") == 1
    assert capsys.readouterr().err.splitlines() == [
        f"guard: tagged blob {object_id[:12]}:1: contains a long encoded run (hex, 512 characters)",
        blocked_line(1),
    ]


def test_history_mode_checks_commit_messages(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "thanks Alex Example")
    assert run_guard(repository, "--history") == 1


def test_history_mode_checks_denied_terms_in_commit_messages(repository: Path) -> None:
    write_private(repository, "guard.json", json.dumps({"denied_terms": ["internal-codename"]}))
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "Fix parser (internal-codename)")
    assert run_guard(repository, "--history") == 1


def test_history_mode_checks_annotated_tag_messages(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    run_git(repository, "tag", "-a", "v0.0.1", "-m", "thanks Alex Example")
    assert run_guard(repository, "--history") == 1
