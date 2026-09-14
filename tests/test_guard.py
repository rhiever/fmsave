"""Tests for scripts/guard.py, run against throwaway git repositories."""

from __future__ import annotations

import importlib.util
import json
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


def test_clean_text_file_passes(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repository, "src/example.py", "print('hello')\n")
    assert run_guard(repository, "--staged") == 0
    assert "structural checks only" in capsys.readouterr().err


def test_private_folder_path_is_blocked(repository: Path) -> None:
    stage(repository, ".local/example.md", "private\n")
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
    with_outputs = {"cells": [{"cell_type": "code", "outputs": [{"text": "x"}], "source": []}]}
    without_outputs = {
        "cells": [{"cell_type": "code", "outputs": [], "execution_count": None, "source": []}]
    }
    stage(repository, "clean.ipynb", json.dumps(without_outputs))
    assert run_guard(repository, "--staged") == 0
    stage(repository, "dirty.ipynb", json.dumps(with_outputs))
    assert run_guard(repository, "--staged") == 1


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


def test_denylisted_name_and_uid_are_blocked_without_printing_them(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_private(repository, "corpus/denylist.txt", "# test list\nAlex Example\n12345678\n")
    stage(repository, "ok.txt", "Alex went home. 123456789 is a different number.\n")
    assert run_guard(repository, "--staged") == 0
    stage(repository, "name.txt", "Signed: alex   EXAMPLE\n")
    stage(repository, "uid.txt", "uid=12345678\n")
    assert run_guard(repository, "--staged") == 1
    error_output = capsys.readouterr().err
    assert "Alex" not in error_output
    assert "EXAMPLE" not in error_output
    assert "12345678" not in error_output


def test_denylisted_uid_inside_hash_like_token_passes(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "12345678\n")
    stage(repository, "hashes.txt", "sha256:ab12345678cd\n")
    assert run_guard(repository, "--staged") == 0


@pytest.mark.parametrize("uid_text", ["12345678", "uid_12345678", "(12345678)"])
def test_delimited_denylisted_uid_is_blocked(repository: Path, uid_text: str) -> None:
    write_private(repository, "corpus/denylist.txt", "12345678\n")
    stage(repository, "uid.txt", f"{uid_text}\n")
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


def test_tracked_mode_checks_committed_files(repository: Path) -> None:
    stage(repository, "data/example.fm", "text\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    assert run_guard(repository, "--tracked") == 1


def test_history_mode_finds_deleted_files_and_messages(repository: Path) -> None:
    stage(repository, "data/example.fm", "text\n")
    run_git(repository, "commit", "-q", "-m", "add file")
    run_git(repository, "rm", "-q", "data/example.fm")
    run_git(repository, "commit", "-q", "-m", "remove file")
    assert run_guard(repository, "--tracked") == 0
    assert run_guard(repository, "--history") == 1


def test_history_mode_checks_commit_messages(repository: Path) -> None:
    write_private(repository, "corpus/denylist.txt", "Alex Example\n")
    stage(repository, "ok.txt", "fine\n")
    run_git(repository, "commit", "-q", "-m", "thanks Alex Example")
    assert run_guard(repository, "--history") == 1
