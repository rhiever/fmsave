from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fmsave import cli, export
from fmsave.checks import GateResult
from fmsave.models.players import Player
from tests.fixtures.career import (
    PLAYER_A_UID,
    PLAYER_D_LEGAL_NAME,
    PLAYER_D_UID,
    career_fragment,
)

FILE_NAME = "career example.fm"
PRIVATE_FOLDER = "Private Folder"


def write_career(tmp_path: Path, **fragment_options: bool) -> Path:
    return career_fragment(**fragment_options).write(tmp_path / "Ünïcode folder" / FILE_NAME)


@pytest.fixture
def save_path(tmp_path: Path) -> Path:
    return write_career(tmp_path)


def csv_rows(output_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(output_text)))


def csv_records(output_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(output_text)))


def run_export(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str, str]:
    exit_code = cli.main(["export", *arguments])
    captured_output = capsys.readouterr()
    return exit_code, captured_output.out, captured_output.err


def test_players_all_writes_every_column_and_row(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(capsys, str(save_path), "players", "--all")
    assert exit_code == cli.EXIT_OK, error_text
    rows = csv_rows(output_text)
    assert tuple(rows[0]) == export.column_names(Player)
    assert len(rows) - 1 == 4
    assert output_text.endswith("\r\n")


def test_players_club_uid_selects_that_clubs_players(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "players", "--club", "5002")
    assert exit_code == cli.EXIT_OK
    records = csv_records(output_text)
    assert [record["uid"] for record in records] == [str(PLAYER_A_UID)]


def test_players_club_name_ignores_case_and_selects_columns(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "players", "--club", "northbridge fc", "--columns", "uid,name"
    )
    assert exit_code == cli.EXIT_OK
    assert csv_rows(output_text) == [["uid", "name"], ["900003", "Sam Sample"]]


def test_players_club_short_name_matches_when_no_full_name_does(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "players", "--club", "Northbridge"
    )
    assert exit_code == cli.EXIT_OK
    assert [record["uid"] for record in csv_records(output_text)] == ["900003"]


def test_an_ambiguous_club_name_lists_the_candidates_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    duplicate_save_path = write_career(tmp_path, duplicate_club_name=True)
    exit_code, output_text, error_text = run_export(
        capsys, str(duplicate_save_path), "players", "--club", "Northbridge FC"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "uid 5001" in error_text
    assert "uid 5006" in error_text
    error_lines = error_text.splitlines()
    assert "  uid 5001  Northbridge FC (Northbridge), nation id 3" in error_lines
    assert "  uid 5006  Northbridge FC (Northbridge Town), nation id 9" in error_lines
    assert "later release" in error_text
    assert error_lines[-1].endswith("use the uid to choose one")


@pytest.mark.parametrize(
    ("club_value", "expected_message"),
    [
        pytest.param("Nowhere", 'no club named "Nowhere"', id="unknown-name"),
        pytest.param("999", "no club with uid 999", id="unknown-uid"),
    ],
)
def test_an_unknown_club_exits_2(
    save_path: Path, capsys: pytest.CaptureFixture[str], club_value: str, expected_message: str
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--club", club_value
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert f"fmsave: error: {expected_message}" in error_text


def test_players_nation_selects_only_that_nation(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "players", "--nation", "44")
    assert exit_code == cli.EXIT_OK
    records = csv_records(output_text)
    assert [record["uid"] for record in records] == ["900001", "900002", "900003"]
    assert {record["nation_id"] for record in records} == {"44"}


def test_a_nation_name_exits_2(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--nation", "Exampleland"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "nation names arrive in a later release; pass a nation id" in error_text


def test_a_competition_scope_exits_2(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--competition", "12"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "later release" in error_text


@pytest.mark.parametrize(
    "scope_arguments",
    [pytest.param([], id="no-scope"), pytest.param(["--all", "--club", "5001"], id="two-scopes")],
)
def test_export_needs_exactly_one_scope(
    save_path: Path, capsys: pytest.CaptureFixture[str], scope_arguments: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["export", str(save_path), "players", *scope_arguments])
    assert exit_info.value.code == cli.EXIT_USAGE
    assert capsys.readouterr().out == ""


def test_unknown_columns_are_listed_and_exit_2(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--all", "--columns", "nope,name,also_nope"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "fmsave: error: unknown columns: nope, also_nope" in error_text


def test_contracts_club_follows_the_players_club(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "contracts", "--club", "5002")
    assert exit_code == cli.EXIT_OK
    assert [record["player_uid"] for record in csv_records(output_text)] == [str(PLAYER_A_UID)]


def test_contracts_nation_follows_the_players_nation(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "contracts", "--nation", "45")
    assert exit_code == cli.EXIT_OK
    assert [record["player_uid"] for record in csv_records(output_text)] == [str(PLAYER_D_UID)]


def test_suspensions_all_as_json_lines(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "suspensions", "--all", "--format", "jsonl"
    )
    assert exit_code == cli.EXIT_OK
    lines = output_text.splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert [row["issued_date"] for row in rows] == ["2031-02-20", "2030-11-02"]
    assert rows[0]["unknown"] == {"e7": 3, "e14": 1}


@pytest.mark.parametrize(
    ("scope_arguments", "expected_count"),
    [
        pytest.param(["--nation", "44"], 2, id="player-nation"),
        pytest.param(["--nation", "45"], 0, id="other-nation"),
        pytest.param(["--club", "Southport"], 2, id="club"),
        pytest.param(["--managed-club"], 0, id="managed-club"),
    ],
)
def test_suspensions_scopes(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    expected_count: int,
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "suspensions", *scope_arguments, "--format", "jsonl"
    )
    assert exit_code == cli.EXIT_OK
    assert len(output_text.splitlines()) == expected_count


def test_clubs_nation_as_a_json_array(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "clubs", "--nation", "3", "--format", "json"
    )
    assert exit_code == cli.EXIT_OK
    clubs = json.loads(output_text)
    assert isinstance(clubs, list)
    assert [club["uid"] for club in clubs] == [5001, 5002]
    assert clubs[0]["teams"] == [{"team_id": 70001, "slot": 0}, {"team_id": 70002, "slot": 1}]


def test_json_with_columns_writes_flat_objects(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(
        capsys,
        str(save_path),
        "players",
        "--club",
        "5002",
        "--format",
        "json",
        "--columns",
        "name,ability_current,uid",
    )
    assert exit_code == cli.EXIT_OK
    assert json.loads(output_text) == [
        {"name": "Alex Example", "ability_current": 140, "uid": PLAYER_A_UID}
    ]


def test_an_empty_selection_writes_an_empty_json_array(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "players", "--nation", "99", "--format", "json"
    )
    assert exit_code == cli.EXIT_OK
    assert json.loads(output_text) == []


def test_clubs_managed_club(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "clubs", "--managed-club")
    assert exit_code == cli.EXIT_OK
    assert [record["uid"] for record in csv_records(output_text)] == ["5001"]


def test_managed_clubs_managed_club(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "managed-clubs", "--managed-club"
    )
    assert exit_code == cli.EXIT_OK
    records = csv_records(output_text)
    assert len(records) == 1
    assert records[0]["club_uid"] == "5001"


def test_players_managed_club(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, _ = run_export(capsys, str(save_path), "players", "--managed-club")
    assert exit_code == cli.EXIT_OK
    assert [record["uid"] for record in csv_records(output_text)] == ["900003"]


def test_managed_clubs_have_no_nation_scope(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "managed-clubs", "--nation", "3"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "fmsave: error:" in error_text


def test_managed_club_scope_without_a_managed_club_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    between_jobs_path = write_career(tmp_path, manager_between_jobs=True)
    exit_code, output_text, error_text = run_export(
        capsys, str(between_jobs_path), "players", "--managed-club"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "fmsave: error: no managed club found in this save" in error_text


def test_all_managed_clubs_without_a_managed_club_writes_no_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    between_jobs_path = write_career(tmp_path, manager_between_jobs=True)
    exit_code, output_text, _ = run_export(capsys, str(between_jobs_path), "managed-clubs", "--all")
    assert exit_code == cli.EXIT_OK
    assert csv_rows(output_text) == [
        ["club_uid", "club_name", "club_short_name", "manager_name", "manager_person_uid"]
    ]


def test_output_file_is_utf8_and_stdout_stays_empty(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = save_path.parent / "out file.csv"
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--all", "-o", str(output_path)
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert output_text == ""
    file_text = output_path.read_bytes().decode("utf-8")
    assert PLAYER_D_LEGAL_NAME in file_text
    assert len(csv_rows(file_text)) == 5


def test_output_file_in_a_missing_folder_exits_2(
    tmp_path: Path, save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_output_path = tmp_path / "missing" / "out.csv"
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--all", "-o", str(missing_output_path)
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "fmsave: error: folder does not exist: missing" in error_text
    assert str(tmp_path) not in error_text
    assert not missing_output_path.parent.exists()


def test_output_file_that_is_the_save_exits_2_and_keeps_the_save(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save_bytes = save_path.read_bytes()
    exit_code, _, error_text = run_export(
        capsys, str(save_path), "players", "--all", "-o", str(save_path)
    )
    assert exit_code == cli.EXIT_USAGE
    assert "fmsave: error:" in error_text
    assert save_path.read_bytes() == save_bytes


def test_a_failed_player_check_exits_3_and_writes_no_file(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_player_gates(*arguments: object) -> tuple[GateResult, ...]:
        return (GateResult("players_minimum", 4, 25000, None, passed=False, applied=True),)

    monkeypatch.setattr("fmsave.checks.evaluate_players", failing_player_gates)
    output_path = save_path.parent / "out.csv"
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--all", "-o", str(output_path)
    )
    assert exit_code == cli.EXIT_UNSUPPORTED
    assert output_text == ""
    assert "players_minimum" in error_text
    assert not output_path.exists()


def test_json_to_a_cp1252_stdout_is_written_as_utf8(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    console_bytes = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(console_bytes, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)
    exit_code = cli.main(["export", str(save_path), "players", "--all", "--format", "json"])
    cp1252_stdout.flush()
    assert exit_code == cli.EXIT_OK, capsys.readouterr().err
    written_bytes = console_bytes.getvalue()
    assert PLAYER_D_LEGAL_NAME.encode("utf-8") in written_bytes
    players = json.loads(written_bytes.decode("utf-8"))
    assert [player["legal_name"] for player in players][3] == PLAYER_D_LEGAL_NAME


def test_csv_to_a_translating_stdout_keeps_single_line_endings(
    save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    console_bytes = io.BytesIO()
    translating_stdout = io.TextIOWrapper(console_bytes, encoding="cp1252", newline="\r\n")
    monkeypatch.setattr(sys, "stdout", translating_stdout)
    assert cli.main(["export", str(save_path), "clubs", "--all"]) == cli.EXIT_OK
    translating_stdout.flush()
    written_bytes = console_bytes.getvalue()
    assert b"\r\n" in written_bytes
    assert b"\r\r\n" not in written_bytes


class BrokenPipeStream(io.StringIO):
    """A stdout whose reader has gone away, as when output is piped into `head`."""

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.parametrize("output_format", ["csv", "json", "jsonl"])
def test_a_broken_pipe_exits_quietly(
    save_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    monkeypatch.setattr(sys, "stdout", BrokenPipeStream())
    exit_code = cli.main(["export", str(save_path), "players", "--all", "--format", output_format])
    assert exit_code in (cli.EXIT_OK, cli.EXIT_UNEXPECTED)
    error_text = capsys.readouterr().err
    assert "cannot read" not in error_text
    assert "error" not in error_text


def test_a_closed_pipe_exits_quietly_from_a_real_process(save_path: Path) -> None:
    export_process = subprocess.Popen(
        [sys.executable, "-m", "fmsave", "export", str(save_path), "players", "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert export_process.stdout is not None
    export_process.stdout.close()
    _, error_bytes = export_process.communicate(timeout=60)
    assert export_process.returncode in (cli.EXIT_OK, cli.EXIT_UNEXPECTED)
    assert error_bytes == b""


@pytest.mark.parametrize(
    "argument_tokens",
    [
        pytest.param(["badtable", "--all", "-o", "{folder}/x.csv"], id="output-bad-table"),
        pytest.param(["badtable", "--all", "-o{folder}/x.csv"], id="glued-output-bad-table"),
        pytest.param(["players", "--all", "-o{folder}/x.csv", "extra"], id="glued-output-extra"),
        pytest.param(["badtable", "--all", "--columns", "{folder}/uid"], id="columns-bad-table"),
        pytest.param(["players", "--club", "{folder}/Nowhere", "--all"], id="club-two-scopes"),
    ],
)
def test_usage_errors_hide_folders_in_option_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argument_tokens: list[str]
) -> None:
    folder_text = str(tmp_path / PRIVATE_FOLDER)
    filled_tokens = [token.replace("{folder}", folder_text) for token in argument_tokens]
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["export", "a.fm", *filled_tokens])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_text = capsys.readouterr().err
    assert error_text.startswith("usage:")
    assert PRIVATE_FOLDER not in error_text
    assert str(tmp_path) not in error_text


def test_a_glued_short_option_value_keeps_its_option_in_the_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    glued_argument = f"-o{tmp_path / PRIVATE_FOLDER / 'x.csv'}"
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", "a.fm", glued_argument])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_text = capsys.readouterr().err
    assert "unrecognized arguments: -ox.csv" in error_text
    assert PRIVATE_FOLDER not in error_text


@pytest.mark.parametrize(
    ("scope_arguments", "expected_message"),
    [
        pytest.param(["--club", "{folder}/Nowhere"], 'no club named "Nowhere"', id="club-name"),
        pytest.param(
            ["--all", "--columns", "uid,{folder}/nope"], "unknown columns: nope", id="columns"
        ),
    ],
)
def test_messages_about_path_like_values_hide_folders(
    save_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    expected_message: str,
) -> None:
    folder_text = str(tmp_path / PRIVATE_FOLDER)
    filled_arguments = [argument.replace("{folder}", folder_text) for argument in scope_arguments]
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", *filled_arguments
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert f"fmsave: error: {expected_message}" in error_text
    assert PRIVATE_FOLDER not in error_text


def test_errors_name_the_save_file_but_not_its_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_save_path = tmp_path / PRIVATE_FOLDER / "missing.fm"
    exit_code, output_text, error_text = run_export(
        capsys, str(missing_save_path), "players", "--all"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "missing.fm" in error_text
    assert PRIVATE_FOLDER not in error_text
