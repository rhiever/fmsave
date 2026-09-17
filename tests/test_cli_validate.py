from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

import fmsave
from fmsave import cli
from fmsave._container import ContainerIndex, read_region_frames
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
PRIVATE_TEXTS = (
    "Alex",
    "Northbridge",
    "Southport",
    "Example",
    "900001",
    "5001",
    "Ünïcode",
    # A staff row, a mentoring group and a stadium name that none of the texts above catches.
    "Sam Sample",
    "Group 1",
    FILE_NAME,
)
READER_ORDER = (
    "clubs",
    "players",
    "contracts",
    "suspensions",
    "managed_clubs",
    "stages",
    "competitions",
    "fixtures",
    "league_tables",
    "transfer_windows",
    "competition_rules",
    "player_match_stats",
    "stadiums",
    "finances",
    "sponsorships",
    "affiliates",
    "job_vacancies",
    "staff",
    "staff_lists",
    "injury_types",
    "injury_history",
    "training",
    "mentoring",
    "tactics",
    "set_pieces",
)
# The readers that cannot run without the one streamed pass over the span: the three built
# from it, and the stadiums whose home clubs are counted from the calendar it carries.
SPAN_PASS_READERS = ("fixtures", "league_tables", "competition_rules", "stadiums")
# The four pairs that each come out of one decode, with the function that decode goes through.
SHARED_PASS_PAIRS = (
    ("fmsave._save.read_club_finances", ("finances", "sponsorships")),
    ("fmsave._save.read_staff", ("staff", "staff_lists")),
    ("fmsave._save.walk_training_blocks", ("training", "mentoring")),
    ("fmsave._save.walk_tactic_blocks", ("tactics", "set_pieces")),
)


@pytest.fixture
def save_path(career_save_path: Path) -> Path:
    """The shared read-only career save, whose file is named FILE_NAME."""
    assert career_save_path.name == FILE_NAME
    return career_save_path


def failing_contract_gates(*arguments: object) -> tuple[GateResult, ...]:
    return (GateResult("tails_parsed", 0.5, 0.9, None, passed=False, applied=True),)


def failing_league_table_gates(*arguments: object) -> tuple[GateResult, ...]:
    return (GateResult("table_blocks_minimum", 2, 1_000, None, passed=False, applied=True),)


def failing_staff_gates(*arguments: object) -> tuple[GateResult, ...]:
    return (GateResult("staff_people", 4, 1_000, None, passed=False, applied=True),)


def test_validate_json_prints_only_the_report_allowlist(
    save_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["validate", str(save_path), "--json"]) == cli.EXIT_OK
    output_text = capsys.readouterr().out
    report = json.loads(output_text)
    assert set(report) == REPORT_KEYS
    assert tuple(reader["reader"] for reader in report["readers"]) == READER_ORDER
    assert [reader["status"] for reader in report["readers"]] == ["ok"] * len(READER_ORDER)
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
        "league_tables: ok (2 records)",
        "transfer_windows: ok (2 records)",
        "competition_rules: ok (2 records)",
        "player_match_stats: ok (4 records)",
        "stadiums: ok (101 records)",
        "finances: ok (6 records)",
        "sponsorships: ok (3 records)",
        "affiliates: ok (2 records)",
        "job_vacancies: ok (3 records)",
        "staff: ok (4 records)",
        "staff_lists: ok (3 records)",
        "injury_types: ok (5 records)",
        "injury_history: ok (6 records)",
        "training: ok (2 records)",
        "mentoring: ok (2 records)",
        "tactics: ok (2 records)",
        "set_pieces: ok (40 records)",
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


def test_a_failed_span_pass_is_reported_for_its_readers_and_scans_the_span_once(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The span is streamed once however many of its readers report the failure."""
    span_scans = 0

    def counting_read_region_frames(
        container_index: ContainerIndex, region_name: str
    ) -> Iterator[bytes]:
        nonlocal span_scans
        span_scans += 1
        return read_region_frames(container_index, region_name)

    def failing_scan_span(*arguments: object, **keyword_arguments: object) -> object:
        raise fmsave.ReaderCheckError("the span pass cannot run")

    monkeypatch.setattr("fmsave._context.read_region_frames", counting_read_region_frames)
    monkeypatch.setattr("fmsave._context.scan_span", failing_scan_span)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNSUPPORTED
    output_lines = capsys.readouterr().out.splitlines()
    for reader_name in SPAN_PASS_READERS:
        assert f"{reader_name}: failed" in output_lines
    assert span_scans == 1
    for reader_name in READER_ORDER:
        if reader_name in SPAN_PASS_READERS:
            continue
        assert any(line.startswith(f"{reader_name}: ok") for line in output_lines), reader_name


def test_a_failed_league_table_check_leaves_the_other_span_readers_ok(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reader that failed after its shared pass ran fails alone: the pass is already read.

    The competition-rules reader is the exception, and not because of the shared pass: it
    takes each block's competition from the league table stored after it, so a failed
    league-table check stops it as well, and it reports no gate of its own.
    """
    monkeypatch.setattr("fmsave.checks.evaluate_league_tables", failing_league_table_gates)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNSUPPORTED
    output_lines = capsys.readouterr().out.splitlines()
    assert "league_tables: failed (2 records)" in output_lines
    assert "  table_blocks_minimum = 2 expected 1000.." in output_lines
    assert "fixtures: ok (6 records)" in output_lines
    assert "competition_rules: failed" in output_lines


@pytest.mark.parametrize(("decode_target", "pass_readers"), SHARED_PASS_PAIRS)
def test_a_failed_shared_decode_is_reported_for_both_its_readers_and_runs_once(
    save_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    decode_target: str,
    pass_readers: tuple[str, str],
) -> None:
    """A pass whose decode raises is reported for both its readers, and is not decoded twice.

    The second reader of a pass would run the same decode again only to raise the same error,
    which is what the carried failure exists to stop: the count proves it was carried rather
    than repeated.
    """
    decode_calls = 0

    def failing_decode(*arguments: object, **keyword_arguments: object) -> object:
        nonlocal decode_calls
        decode_calls += 1
        raise fmsave.CorruptSaveError("career example.fm: this pass cannot be decoded")

    monkeypatch.setattr(decode_target, failing_decode)
    assert cli.main(["validate", str(save_path)]) == cli.EXIT_UNEXPECTED
    output_lines = capsys.readouterr().out.splitlines()
    for reader_name in pass_readers:
        assert f"{reader_name}: error" in output_lines
    assert decode_calls == 1


def test_a_failed_staff_check_fails_both_staff_readers_with_their_own_gates(
    save_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A check that fails before the pass is cached fails the pass, as the player pass does.

    Both staff tables and both sets of checks are built by the one decode, and the checks are
    enforced before either table is kept, so a failed staff gate leaves nothing cached and the
    staff-list reader is reported failed as well. Each reader still lists its own gates, so
    the report names the gate that failed and not the other reader's.
    """
    monkeypatch.setattr("fmsave.checks.evaluate_staff", failing_staff_gates)
    assert cli.main(["validate", str(save_path), "--json"]) == cli.EXIT_UNSUPPORTED
    report = json.loads(capsys.readouterr().out)
    readers = {reader["reader"]: reader for reader in report["readers"]}
    assert readers["staff"]["status"] == "failed"
    assert readers["staff_lists"]["status"] == "failed"
    assert [gate["name"] for gate in readers["staff"]["gates"]] == ["staff_people"]
    assert "staff_people" not in [gate["name"] for gate in readers["staff_lists"]["gates"]]
    assert readers["clubs"]["status"] == "ok"


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
