from __future__ import annotations

import csv
import errno
import functools
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest

import fmsave
from fmsave import AmbiguousNameError, Club, Stage, Table, cli, export
from fmsave.checks import GateResult
from fmsave.models.players import Player
from tests.fixtures.career import (
    ATHLETIC_NATION_ID,
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    NORTHBRIDGE_UID,
    PLAYER_A_UID,
    PLAYER_D_LEGAL_NAME,
    PLAYER_D_UID,
    PLAYER_NATION_ID,
    SECOND_COMPETITION_DATABASE_ID,
    SECOND_COMPETITION_ID,
    SOUTHPORT_UID,
    STAGE_ROW_COUNT,
    career_fragment,
)

FILE_NAME = "career example.fm"
PRIVATE_FOLDER = "Private Folder"
COMPETITION_NAMES_FILE_NAME = "competition names.csv"
EXAMPLE_COMPETITION_NAME = "Example League"
UNKNOWN_COMPETITION_ID = 999
# What the shared career fragment holds, counted from the fixture rather than from a reader.
EXAMPLE_COMPETITION_COUNT = 3
FIXTURE_COUNT = 6
FIRST_COMPETITION_FIXTURE_COUNT = 4
NORTHBRIDGE_FIXTURE_COUNT = 6
SOUTHPORT_FIXTURE_COUNT = 3
ATHLETIC_FIXTURE_COUNT = 3
FIRST_COMPETITION_STAGE_COUNT = 2
LEAGUE_TABLE_COUNT = 2
TRANSFER_WINDOW_COUNT = 2
COMPETITION_RULES_COUNT = 2
MATCH_STATS_COUNT = 4
FIRST_COMPETITION_MATCH_STATS_COUNT = 3


def write_competition_names(names_path: Path, rows: list[tuple[int, str]]) -> Path:
    """A two-column name file with a header row, as read_competition_names reads them."""
    named_rows = "".join(f"{database_id},{name}\n" for database_id, name in rows)
    names_path.parent.mkdir(parents=True, exist_ok=True)
    names_path.write_text(f"database_id,name\n{named_rows}", encoding="utf-8")
    return names_path


def write_career(
    tmp_path: Path, *, duplicate_club_name: bool = False, manager_between_jobs: bool = False
) -> Path:
    return career_fragment(
        duplicate_club_name=duplicate_club_name, manager_between_jobs=manager_between_jobs
    ).write(tmp_path / "Ünïcode folder" / FILE_NAME)


@pytest.fixture
def save_path(career_save_path: Path) -> Path:
    """The shared read-only career save; tests write their output files under tmp_path."""
    return career_save_path


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
    assert "  uid 5006  Northbridge FC (Northbridge), nation id 9" in error_lines
    assert "later release" in error_text
    assert error_lines[-1].endswith("use the uid to choose one")


def test_a_short_name_shared_by_two_clubs_is_ambiguous(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    duplicate_save_path = write_career(tmp_path, duplicate_club_name=True)
    exit_code, output_text, error_text = run_export(
        capsys, str(duplicate_save_path), "players", "--club", "northbridge"
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    error_lines = error_text.splitlines()
    assert error_lines[0] == 'fmsave: error: more than one club matches "northbridge":'
    assert error_lines[1:3] == [
        "  uid 5001  Northbridge FC (Northbridge), nation id 3",
        "  uid 5006  Northbridge FC (Northbridge), nation id 9",
    ]
    assert error_lines[-1].endswith("use the uid to choose one")


def example_club(uid: int, short_name: str) -> Club:
    return Club(uid, "Example Rovers", short_name, 3, 3, None, (), None, None, None)


def test_a_path_like_value_is_reduced_in_the_ambiguity_header() -> None:
    shared_short_name = "Hidden Place/Rovers"
    clubs = Table(
        (example_club(5101, shared_short_name), example_club(5102, shared_short_name)), Club
    )
    with pytest.raises(AmbiguousNameError) as error_info:
        cli.resolve_club(clubs, shared_short_name)
    message_lines = str(error_info.value).splitlines()
    assert message_lines[0] == 'more than one club matches "Rovers":'
    assert [line.split()[1] for line in message_lines[1:3]] == ["5101", "5102"]


@pytest.mark.parametrize(
    ("club_value", "expected_club_uids"),
    [
        pytest.param("5001", ["5001"], id="managed-club-uid"),
        pytest.param("Northbridge FC", ["5001"], id="managed-club-name"),
        pytest.param("Southport", [], id="other-club"),
    ],
)
def test_managed_clubs_club(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    club_value: str,
    expected_club_uids: list[str],
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "managed-clubs", "--club", club_value
    )
    assert exit_code == cli.EXIT_OK
    assert [record["club_uid"] for record in csv_records(output_text)] == expected_club_uids


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


@pytest.mark.parametrize(
    ("table_name", "scope_arguments", "expected_fragments"),
    [
        pytest.param(
            "players",
            ["--competition", str(FIRST_COMPETITION_ID)],
            ("players cannot be scoped by competition", "--club, --managed-club, --nation"),
            id="players-competition",
        ),
        pytest.param(
            "competitions",
            ["--club", str(NORTHBRIDGE_UID)],
            ("competitions cannot be scoped by club", "use --competition or --all"),
            id="competitions-club",
        ),
        pytest.param(
            "competitions",
            ["--nation", "3"],
            ("competitions cannot be scoped by nation",),
            id="competitions-nation",
        ),
        pytest.param(
            "stages",
            ["--managed-club"],
            ("stages cannot be scoped by managed club", "use --competition or --all"),
            id="stages-managed-club",
        ),
        pytest.param(
            "transfer-windows",
            ["--club", str(NORTHBRIDGE_UID)],
            ("transfer windows are not scoped to a club, competition or nation", "use --all"),
            id="transfer-windows-club",
        ),
        pytest.param(
            "transfer-windows",
            ["--competition", str(FIRST_COMPETITION_ID)],
            ("transfer windows are not scoped", "use --all"),
            id="transfer-windows-competition",
        ),
        pytest.param(
            "competition-rules",
            ["--nation", "3"],
            ("competition rules cannot be scoped by nation", cli.COMPETITION_RULES_NOTE),
            id="competition-rules-nation",
        ),
        pytest.param(
            "managed-clubs",
            ["--nation", "3"],
            ("managed clubs cannot be scoped by nation", "use --club, --managed-club or --all"),
            id="managed-clubs-nation",
        ),
    ],
)
def test_a_scope_a_table_does_not_take_exits_2(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    table_name: str,
    scope_arguments: list[str],
    expected_fragments: tuple[str, ...],
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), table_name, *scope_arguments
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    for expected_fragment in expected_fragments:
        assert expected_fragment in error_text


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
    assert clubs[0]["teams"] == [
        {"team_id": 70001, "slot": 0, "club_uid": 5001, "affiliate": False},
        {"team_id": 70002, "slot": 1, "club_uid": 5001, "affiliate": False},
    ]


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


CHOSEN_PLAYER_COLUMNS = ["birth_date", "name", "natural_positions", "suspensions", "uid"]


def test_csv_with_columns_matches_the_selected_flat_rows_byte_for_byte(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, _ = run_export(
        capsys, str(save_path), "players", "--all", "--columns", ",".join(CHOSEN_PLAYER_COLUMNS)
    )
    assert exit_code == cli.EXIT_OK
    with fmsave.open(save_path) as career_save:
        players = career_save.players()
    expected_output = io.StringIO(newline="")
    selected_rows = (
        export.select_columns(flat_row, CHOSEN_PLAYER_COLUMNS)
        for flat_row in export.flat_rows(players, Player)
    )
    export.write_csv(selected_rows, CHOSEN_PLAYER_COLUMNS, expected_output)
    assert output_text == expected_output.getvalue()
    assert '"[{""suspension_competition_id"":1234' in output_text


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
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "out file.csv"
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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    own_save_path = write_career(tmp_path)
    save_bytes = own_save_path.read_bytes()
    exit_code, _, error_text = run_export(
        capsys, str(own_save_path), "players", "--all", "-o", str(own_save_path)
    )
    assert exit_code == cli.EXIT_USAGE
    assert "fmsave: error:" in error_text
    assert own_save_path.read_bytes() == save_bytes


def test_a_failed_player_check_exits_3_and_writes_no_file(
    save_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_player_gates(*arguments: object) -> tuple[GateResult, ...]:
        return (GateResult("players_minimum", 4, 25000, None, passed=False, applied=True),)

    monkeypatch.setattr("fmsave.checks.evaluate_players", failing_player_gates)
    output_path = tmp_path / "out.csv"
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


class FailingOutputStream(io.StringIO):
    """A stdout whose every write and flush fails with one error, such as a closed pipe."""

    def __init__(self, write_error: OSError) -> None:
        super().__init__()
        self.write_error = write_error

    def write(self, text: str) -> int:
        raise self.write_error

    def flush(self) -> None:
        raise self.write_error


OUTPUT_COMMANDS = [
    pytest.param(["export", "{save}", "players", "--all"], id="export-csv"),
    pytest.param(["export", "{save}", "players", "--all", "--format", "json"], id="export-json"),
    pytest.param(["export", "{save}", "clubs", "--all", "--format", "jsonl"], id="export-jsonl"),
    pytest.param(["validate", "{save}"], id="validate"),
    pytest.param(["info", "{save}", "--json"], id="info"),
]


def filled_command(command_tokens: list[str], save_path: Path) -> list[str]:
    return [token.replace("{save}", str(save_path)) for token in command_tokens]


@pytest.mark.parametrize("command_tokens", OUTPUT_COMMANDS)
@pytest.mark.parametrize(
    ("write_error", "platform_name"),
    [
        pytest.param(BrokenPipeError(errno.EPIPE, "Broken pipe"), "linux", id="broken-pipe"),
        pytest.param(OSError(errno.EPIPE, "Broken pipe"), "darwin", id="epipe"),
        pytest.param(OSError(errno.EINVAL, "Invalid argument"), "win32", id="windows-einval"),
    ],
)
def test_a_closed_standard_output_exits_quietly(
    save_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_tokens: list[str],
    write_error: OSError,
    platform_name: str,
) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(sys, "stdout", FailingOutputStream(write_error))
    exit_code = cli.main(filled_command(command_tokens, save_path))
    monkeypatch.undo()
    assert exit_code == cli.EXIT_UNEXPECTED
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command_tokens", OUTPUT_COMMANDS)
@pytest.mark.parametrize(
    ("write_error", "platform_name"),
    [
        pytest.param(OSError(errno.EINVAL, "Invalid argument"), "linux", id="einval"),
        pytest.param(OSError(errno.ENOSPC, "No space left on device"), "win32", id="enospc"),
    ],
)
def test_a_failed_standard_output_write_is_reported_as_a_write_failure(
    save_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_tokens: list[str],
    write_error: OSError,
    platform_name: str,
) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(sys, "stdout", FailingOutputStream(write_error))
    exit_code = cli.main(filled_command(command_tokens, save_path))
    monkeypatch.undo()
    assert exit_code == cli.EXIT_UNEXPECTED
    error_text = capsys.readouterr().err
    assert error_text == f"fmsave: error: cannot write the output: {write_error.strerror}\n"


def export_to_a_failing_output_file(
    save_path: Path,
    output_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_error: OSError,
    platform_name: str,
) -> int:
    def failing_write_records(*arguments: object) -> None:
        raise write_error

    monkeypatch.setattr(cli, "write_records", failing_write_records)
    monkeypatch.setattr(sys, "platform", platform_name)
    output_path = output_folder / "out.csv"
    exit_code = cli.main(["export", str(save_path), "players", "--all", "-o", str(output_path)])
    monkeypatch.undo()
    return exit_code


@pytest.mark.parametrize(
    ("write_error", "platform_name"),
    [
        pytest.param(OSError(errno.ENOSPC, "No space left on device"), "linux", id="enospc"),
        pytest.param(OSError(errno.EINVAL, "Invalid argument"), "linux", id="einval"),
    ],
)
def test_a_failed_output_file_write_is_reported_as_a_write_failure(
    save_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_error: OSError,
    platform_name: str,
) -> None:
    exit_code = export_to_a_failing_output_file(
        save_path, tmp_path, monkeypatch, write_error, platform_name
    )
    assert exit_code == cli.EXIT_UNEXPECTED
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == (
        f"fmsave: error: cannot write the output: {write_error.strerror}\n"
    )


@pytest.mark.parametrize(
    ("write_error", "platform_name"),
    [
        pytest.param(BrokenPipeError(errno.EPIPE, "Broken pipe"), "linux", id="broken-pipe"),
        pytest.param(OSError(errno.EPIPE, "Broken pipe"), "darwin", id="epipe"),
        pytest.param(OSError(errno.EINVAL, "Invalid argument"), "win32", id="windows-einval"),
    ],
)
def test_an_output_file_that_is_a_closed_pipe_exits_quietly(
    save_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_error: OSError,
    platform_name: str,
) -> None:
    exit_code = export_to_a_failing_output_file(
        save_path, tmp_path, monkeypatch, write_error, platform_name
    )
    assert exit_code == cli.EXIT_UNEXPECTED
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == ""


@pytest.mark.parametrize(
    ("open_error", "platform_name"),
    [
        pytest.param(OSError(errno.EINVAL, "Invalid argument"), "win32", id="windows-einval"),
        pytest.param(BrokenPipeError(errno.EPIPE, "Broken pipe"), "linux", id="broken-pipe"),
    ],
)
def test_an_output_file_that_fails_to_open_is_never_quiet(
    save_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    open_error: OSError,
    platform_name: str,
) -> None:
    def failing_open(*arguments: object, **keyword_arguments: object) -> NoReturn:
        raise open_error

    monkeypatch.setattr(cli, "open", failing_open, raising=False)
    monkeypatch.setattr(sys, "platform", platform_name)
    output_path = tmp_path / "bad?.csv"
    exit_code = cli.main(["export", str(save_path), "players", "--all", "-o", str(output_path)])
    monkeypatch.undo()
    assert exit_code == cli.EXIT_UNEXPECTED
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == f"fmsave: error: cannot write the output: {open_error.strerror}\n"


def test_an_output_file_that_cannot_be_opened_is_a_write_failure(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder_as_output_path = tmp_path / "Ünïcode folder"
    folder_as_output_path.mkdir()
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "players", "--all", "-o", str(folder_as_output_path)
    )
    assert exit_code == cli.EXIT_UNEXPECTED
    assert output_text == ""
    assert error_text.startswith("fmsave: error: cannot write the output: ")
    assert "cannot read" not in error_text
    assert "Ünïcode" not in error_text


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


@pytest.mark.skipif(sys.platform == "win32", reason="file size limits need POSIX resource limits")
@pytest.mark.parametrize(
    "command_tokens",
    [
        pytest.param(["export", "{save}", "players", "--all"], id="export"),
        pytest.param(["validate", "{save}"], id="validate"),
        pytest.param(["info", "{save}", "--json"], id="info"),
    ],
)
def test_a_standard_output_file_that_cannot_grow_gives_one_write_message(
    save_path: Path, tmp_path: Path, command_tokens: list[str]
) -> None:
    import resource

    # The child may create files of zero bytes only, so its writes to the file fail with EFBIG.
    forbid_file_growth = functools.partial(resource.setrlimit, resource.RLIMIT_FSIZE, (0, 0))
    redirected_output_path = tmp_path / "redirected output.txt"
    with redirected_output_path.open("wb") as redirected_output:
        completed_process = subprocess.run(
            [sys.executable, "-m", "fmsave", *filled_command(command_tokens, save_path)],
            stdout=redirected_output,
            stderr=subprocess.PIPE,
            preexec_fn=forbid_file_growth,
            check=False,
            timeout=60,
        )
    error_text = completed_process.stderr.decode("utf-8")
    assert "Exception ignored" not in error_text
    assert error_text == f"fmsave: error: cannot write the output: {os.strerror(errno.EFBIG)}\n"
    assert completed_process.returncode == cli.EXIT_UNEXPECTED


@pytest.mark.parametrize(
    "argument_tokens",
    [
        pytest.param(["badtable", "--all", "-o", "{folder}/x.csv"], id="output-bad-table"),
        pytest.param(["badtable", "--all", "-o{folder}/x.csv"], id="glued-output-bad-table"),
        pytest.param(["players", "--all", "-o{folder}/x.csv", "extra"], id="glued-output-extra"),
        pytest.param(["badtable", "--all", "--columns", "{folder}/uid"], id="columns-bad-table"),
        pytest.param(["players", "--club", "{folder}/Nowhere", "--all"], id="club-two-scopes"),
        pytest.param(
            ["badtable", "--all", "--competition-names", "{folder}/names.csv"],
            id="competition-names-bad-table",
        ),
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


@pytest.mark.parametrize(
    ("argument_tokens", "expected_message"),
    [
        pytest.param(
            ["info", "a.fm", "-o{folder}/x.csv"],
            "unrecognized arguments: -ox.csv",
            id="glued-output-under-info",
        ),
        pytest.param(
            ["export", "a.fm", "players", "--all", "-o{folder}/x.csv", "{folder}/y.csv"],
            "unrecognized arguments: y.csv",
            id="extra-path-after-glued-output",
        ),
        pytest.param(
            ["export", "a.fm", "players", "--all", "--format", "{folder}/x"],
            "argument --format: invalid choice: 'x'",
            id="format-value",
        ),
        pytest.param(
            ["export", "a.fm", "{folder}/badtable", "--all"],
            "argument TABLE: invalid choice: 'badtable'",
            id="table-value",
        ),
        pytest.param(
            ["info", "a.fm", "--columns={folder}/uid"],
            "unrecognized arguments: --columns=uid",
            id="columns-value-under-info",
        ),
        pytest.param(
            ["validate", "a.fm", "--club", "{folder}/Nowhere"],
            "unrecognized arguments: --club Nowhere",
            id="club-value-under-validate",
        ),
    ],
)
def test_usage_errors_that_quote_a_path_like_value_keep_the_message_without_the_folder(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argument_tokens: list[str],
    expected_message: str,
) -> None:
    folder_text = str(tmp_path / PRIVATE_FOLDER)
    filled_tokens = [token.replace("{folder}", folder_text) for token in argument_tokens]
    with pytest.raises(SystemExit) as exit_info:
        cli.main(filled_tokens)
    assert exit_info.value.code == cli.EXIT_USAGE
    error_text = capsys.readouterr().err
    last_error_line = error_text.splitlines()[-1]
    assert last_error_line.startswith("fmsave")
    assert f": error: {expected_message}" in last_error_line
    assert PRIVATE_FOLDER not in error_text
    assert str(tmp_path) not in error_text


@pytest.mark.parametrize(
    ("scope_arguments", "expected_message"),
    [
        pytest.param(["--club", "{folder}/Nowhere"], 'no club named "Nowhere"', id="club-name"),
        pytest.param(
            ["--all", "--columns", "uid,{folder}/nope"], "unknown columns: nope", id="columns"
        ),
        pytest.param(
            ["--all", "--competition-names", "{folder}/missing.csv"],
            "file not found: missing.csv",
            id="competition-names-missing",
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


def test_stages_all_writes_every_column_and_row(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(capsys, str(save_path), "stages", "--all")
    assert exit_code == cli.EXIT_OK, error_text
    rows = csv_rows(output_text)
    assert tuple(rows[0]) == export.column_names(Stage)
    assert len(rows) - 1 == STAGE_ROW_COUNT


def test_stages_competition_selects_that_competitions_stages(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "stages", "--competition", str(FIRST_COMPETITION_ID)
    )
    assert exit_code == cli.EXIT_OK, error_text
    records = csv_records(output_text)
    assert len(records) == FIRST_COMPETITION_STAGE_COUNT
    assert {record["competition_id"] for record in records} == {str(FIRST_COMPETITION_ID)}


def test_competitions_all_and_by_id(save_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output_text, error_text = run_export(capsys, str(save_path), "competitions", "--all")
    assert exit_code == cli.EXIT_OK, error_text
    assert len(csv_records(output_text)) == EXAMPLE_COMPETITION_COUNT
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competitions", "--competition", str(SECOND_COMPETITION_ID)
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert [record["id"] for record in csv_records(output_text)] == [str(SECOND_COMPETITION_ID)]


def test_an_unknown_competition_id_exits_2(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competitions", "--competition", str(UNKNOWN_COMPETITION_ID)
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert f"fmsave: error: no competition with id {UNKNOWN_COMPETITION_ID}" in error_text


@pytest.mark.parametrize(
    ("scope_arguments", "expected_count"),
    [
        pytest.param(["--all"], FIXTURE_COUNT, id="all"),
        pytest.param(
            ["--competition", str(FIRST_COMPETITION_ID)],
            FIRST_COMPETITION_FIXTURE_COUNT,
            id="competition",
        ),
        pytest.param(["--club", str(NORTHBRIDGE_UID)], NORTHBRIDGE_FIXTURE_COUNT, id="club"),
        pytest.param(["--club", str(SOUTHPORT_UID)], SOUTHPORT_FIXTURE_COUNT, id="other-club"),
        pytest.param(
            ["--nation", str(ATHLETIC_NATION_ID)], ATHLETIC_FIXTURE_COUNT, id="club-nation"
        ),
    ],
)
def test_fixture_scopes_keep_the_matches_they_cover(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    expected_count: int,
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "fixtures", *scope_arguments
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert len(csv_records(output_text)) == expected_count


def test_fixtures_managed_club_keeps_only_the_managed_clubs_matches(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "fixtures", "--managed-club"
    )
    assert exit_code == cli.EXIT_OK, error_text
    records = csv_records(output_text)
    assert len(records) == NORTHBRIDGE_FIXTURE_COUNT
    assert all(
        str(NORTHBRIDGE_UID) in (record["home_club_uid"], record["away_club_uid"])
        for record in records
    )


def test_league_tables_all_as_json_nests_its_rows(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "league-tables", "--all", "--format", "json"
    )
    assert exit_code == cli.EXIT_OK, error_text
    league_tables = json.loads(output_text)
    assert isinstance(league_tables, list)
    assert len(league_tables) == LEAGUE_TABLE_COUNT
    for league_table in league_tables:
        assert isinstance(league_table["rows"], list)
    assert league_tables[0]["rows"][0]["club_uid"] == NORTHBRIDGE_UID


@pytest.mark.parametrize(
    ("scope_arguments", "expected_count"),
    [
        pytest.param(["--club", str(SOUTHPORT_UID)], 1, id="club"),
        pytest.param(["--nation", str(ATHLETIC_NATION_ID)], 1, id="club-nation"),
        pytest.param(["--competition", str(FIRST_COMPETITION_ID)], 1, id="competition"),
        pytest.param(["--managed-club"], LEAGUE_TABLE_COUNT, id="managed-club"),
    ],
)
def test_league_table_scopes_keep_whole_tables(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    expected_count: int,
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "league-tables", *scope_arguments, "--format", "jsonl"
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert len(output_text.splitlines()) == expected_count


def test_transfer_windows_all_writes_every_window(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "transfer-windows", "--all"
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert len(csv_records(output_text)) == TRANSFER_WINDOW_COUNT


def test_competition_rules_all_and_the_empty_competition_scope(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competition-rules", "--all"
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert len(csv_records(output_text)) == COMPETITION_RULES_COUNT
    # No rules block names a competition, so a competition scope writes a header and no rows.
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competition-rules", "--competition", str(FIRST_COMPETITION_ID)
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert csv_records(output_text) == []


@pytest.mark.parametrize(
    ("scope_arguments", "expected_count"),
    [
        pytest.param(["--all"], MATCH_STATS_COUNT, id="all"),
        pytest.param(
            ["--competition", str(FIRST_COMPETITION_ID)],
            FIRST_COMPETITION_MATCH_STATS_COUNT,
            id="competition",
        ),
        pytest.param(["--club", str(SOUTHPORT_UID)], MATCH_STATS_COUNT, id="player-club"),
        pytest.param(["--club", str(NORTHBRIDGE_UID)], 0, id="other-club"),
        pytest.param(["--nation", str(PLAYER_NATION_ID)], MATCH_STATS_COUNT, id="player-nation"),
        pytest.param(["--managed-club"], 0, id="managed-club"),
    ],
)
def test_player_match_stats_scopes_follow_the_player(
    save_path: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    expected_count: int,
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "player-match-stats", *scope_arguments, "--format", "jsonl"
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert len(output_text.splitlines()) == expected_count


def test_a_name_map_names_the_competitions_it_covers(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names_path = write_competition_names(
        tmp_path / COMPETITION_NAMES_FILE_NAME,
        [(FIRST_COMPETITION_DATABASE_ID, EXAMPLE_COMPETITION_NAME)],
    )
    exit_code, output_text, error_text = run_export(
        capsys,
        str(save_path),
        "competitions",
        "--all",
        "--competition-names",
        str(names_path),
    )
    assert exit_code == cli.EXIT_OK, error_text
    names = [record["name"] for record in csv_records(output_text)]
    assert names == [EXAMPLE_COMPETITION_NAME, "", ""]


def test_a_competition_name_selects_its_competition(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names_path = write_competition_names(
        tmp_path / COMPETITION_NAMES_FILE_NAME,
        [(FIRST_COMPETITION_DATABASE_ID, EXAMPLE_COMPETITION_NAME)],
    )
    exit_code, output_text, error_text = run_export(
        capsys,
        str(save_path),
        "competitions",
        "--competition",
        EXAMPLE_COMPETITION_NAME,
        "--competition-names",
        str(names_path),
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert [record["id"] for record in csv_records(output_text)] == [str(FIRST_COMPETITION_ID)]


def test_a_competition_name_without_a_map_exits_2(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competitions", "--competition", EXAMPLE_COMPETITION_NAME
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert f'no competition named "{EXAMPLE_COMPETITION_NAME}"' in error_text
    assert "--competition-names" in error_text


def test_one_name_on_two_competitions_lists_both_ids_and_exits_2(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names_path = write_competition_names(
        tmp_path / COMPETITION_NAMES_FILE_NAME,
        [
            (FIRST_COMPETITION_DATABASE_ID, EXAMPLE_COMPETITION_NAME),
            (SECOND_COMPETITION_DATABASE_ID, EXAMPLE_COMPETITION_NAME),
        ],
    )
    exit_code, output_text, error_text = run_export(
        capsys,
        str(save_path),
        "competitions",
        "--competition",
        EXAMPLE_COMPETITION_NAME,
        "--competition-names",
        str(names_path),
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    error_lines = error_text.splitlines()
    first_candidate_line = (
        f"  id {FIRST_COMPETITION_ID}  {EXAMPLE_COMPETITION_NAME} "
        f"(database id {FIRST_COMPETITION_DATABASE_ID})"
    )
    second_candidate_line = (
        f"  id {SECOND_COMPETITION_ID}  {EXAMPLE_COMPETITION_NAME} "
        f"(database id {SECOND_COMPETITION_DATABASE_ID})"
    )
    assert error_lines[1:3] == [first_candidate_line, second_candidate_line]
    assert error_lines[-1].endswith("use the id to choose one")


def test_a_missing_name_file_exits_2_and_names_only_the_file(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_path = tmp_path / PRIVATE_FOLDER / "missing.csv"
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competitions", "--all", "--competition-names", str(missing_path)
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "fmsave: error: file not found: missing.csv" in error_text
    assert PRIVATE_FOLDER not in error_text


def test_a_malformed_name_file_exits_2_and_names_only_the_file(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = tmp_path / PRIVATE_FOLDER / "bad.csv"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("database_id,name\n12345\n", encoding="utf-8")
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "competitions", "--all", "--competition-names", str(bad_path)
    )
    assert exit_code == cli.EXIT_USAGE
    assert output_text == ""
    assert "bad.csv" in error_text
    assert PRIVATE_FOLDER not in error_text


def test_fixtures_to_a_file_in_a_unicode_folder(
    save_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_folder = tmp_path / "Ünïcode folder"
    output_folder.mkdir()
    output_path = output_folder / "fixtures.csv"
    exit_code, output_text, error_text = run_export(
        capsys, str(save_path), "fixtures", "--all", "-o", str(output_path)
    )
    assert exit_code == cli.EXIT_OK, error_text
    assert output_text == ""
    file_text = output_path.read_bytes().decode("utf-8")
    assert len(csv_rows(file_text)) - 1 == FIXTURE_COUNT


def test_a_failed_fixture_check_exits_3(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_fixture_gates(*arguments: object) -> tuple[GateResult, ...]:
        return (GateResult("fixtures_minimum", FIXTURE_COUNT, 90_000, None, False, True),)

    monkeypatch.setattr("fmsave.checks.evaluate_fixtures", failing_fixture_gates)
    exit_code, output_text, error_text = run_export(capsys, str(save_path), "fixtures", "--all")
    assert exit_code == cli.EXIT_UNSUPPORTED
    assert output_text == ""
    assert "fixtures_minimum" in error_text
