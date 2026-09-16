from __future__ import annotations

import json
from pathlib import Path

import pytest

import fmsave
from fmsave import cli
from fmsave.checks import GateResult

FILE_NAME = "career example.fm"
REPORT_KEYS = {
    "fmsave_version",
    "python_version",
    "os",
    "game",
    "build",
    "known_build",
    "section_schemas",
    "readers",
    "field_statuses",
}
PRIVATE_TEXTS = ("Alex", "Northbridge", "Example", "900001", "5001", "Ünïcode", FILE_NAME)


@pytest.fixture
def save_path(career_save_path: Path) -> Path:
    """The shared read-only career save, whose file is named FILE_NAME."""
    assert career_save_path.name == FILE_NAME
    return career_save_path


def failing_contract_gates(*arguments: object) -> tuple[GateResult, ...]:
    return (GateResult("tails_parsed", 0.5, 0.9, None, passed=False, applied=True),)


def test_validate_json_prints_only_the_report_allowlist(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["validate", str(save_path), "--json"]) == cli.EXIT_OK
    output_text = capsys.readouterr().out
    report = json.loads(output_text)
    assert set(report) == REPORT_KEYS
    assert [reader["status"] for reader in report["readers"]] == ["ok"] * 10
    for private_text in PRIVATE_TEXTS:
        assert private_text not in output_text


def test_validate_text_lists_each_reader_and_the_build(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_OK
    output_text = capsys.readouterr().out
    assert output_text.splitlines() == [
        "clubs: ok (3 records)",
        "players: ok (4 records)",
        "contracts: ok (4 records)",
        "suspensions: ok (2 records)",
        "managed_clubs: ok (1 records)",
        "stages: ok (220 records)",
        "competitions: ok (3 records)",
        "fixtures: ok (6 records)",
        "transfer_windows: ok (2 records)",
        "league_tables: ok (2 records)",
        "game FM26, build 26.3.2+2329565",
    ]
    for private_text in PRIVATE_TEXTS:
        assert private_text not in output_text


def test_a_failed_contract_check_exits_3_and_names_the_gate(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("fmsave.checks.evaluate_contracts", failing_contract_gates)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNSUPPORTED
    output_lines = capsys.readouterr().out.splitlines()
    assert "contracts: failed (4 records)" in output_lines
    assert "  tails_parsed = 0.5 expected 0.9.." in output_lines
    assert "players: failed (4 records)" in output_lines
    assert "clubs: ok (3 records)" in output_lines


def test_a_failed_check_in_json_exits_3(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("fmsave.checks.evaluate_contracts", failing_contract_gates)
    assert cli.main(["validate", str(save_path), "--json"]) == cli.EXIT_UNSUPPORTED
    report = json.loads(capsys.readouterr().out)
    statuses = {reader["reader"]: reader["status"] for reader in report["readers"]}
    assert statuses["contracts"] == "failed"


def raise_corrupt_save(career_save: fmsave.Save) -> object:
    raise fmsave.CorruptSaveError("career example.fm: section 'humans' is damaged")


def test_a_reader_error_without_failures_exits_1(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fmsave.Save, "managed_clubs", raise_corrupt_save)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNEXPECTED
    captured_output = capsys.readouterr()
    assert "managed_clubs: error" in captured_output.out.splitlines()
    assert "humans" not in captured_output.out
    assert captured_output.err == ""


def test_a_failure_outranks_a_reader_error(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fmsave.Save, "managed_clubs", raise_corrupt_save)
    monkeypatch.setattr("fmsave.checks.evaluate_contracts", failing_contract_gates)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNSUPPORTED
    capsys.readouterr()


def test_validate_a_missing_save_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_path = tmp_path / "Private Folder" / "missing.fm"
    assert cli.main(["validate", str(missing_path)]) == cli.EXIT_USAGE
    error_text = capsys.readouterr().err
    assert "missing.fm" in error_text
    assert "Private Folder" not in error_text
