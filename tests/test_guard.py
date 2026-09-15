"""Tests for scripts/guard.py, run against throwaway git repositories."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
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


@pytest.mark.parametrize("pattern_name", ["HEX_RUN_PATTERN", "BASE64_RUN_PATTERN"])
def test_encoded_run_pattern_starts_only_where_no_run_character_precedes(pattern_name: str) -> None:
    """Without the leading lookbehind, every position inside a short run would be rescanned."""
    pattern_text = getattr(guard, pattern_name).pattern
    assert LOOKBEHIND_RUN_SHAPE.fullmatch(pattern_text) is not None, pattern_text


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
