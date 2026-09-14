from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fmsave import cli
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    save_summary_body,
)


def replaced_sections(**replacement_bodies: bytes) -> list[SectionFrame]:
    return [
        SectionFrame(
            section.name,
            replacement_bodies.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]


@pytest.fixture
def fragment_path(tmp_path: Path) -> Path:
    return build_container_fragment().write(tmp_path / "Private Folder" / "career.bin")


def test_info_text_hides_save_name(fragment_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(fragment_path)]) == cli.EXIT_OK
    output = capsys.readouterr().out
    for expected in (
        "FM26",
        "26.3.2+2329565",
        "26.2.0+0",
        "2031-03-01",
        "hidden (use --show-name)",
        "Sections",
    ):
        assert expected in output
    assert "Example Career" not in output


def test_info_text_show_name(fragment_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(fragment_path), "--show-name"]) == cli.EXIT_OK
    assert "Example Career" in capsys.readouterr().out


def test_info_json(fragment_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(fragment_path), "--json"]) == cli.EXIT_OK
    record = json.loads(capsys.readouterr().out)
    assert list(record) == [
        "fmsave_version",
        "game",
        "build",
        "known_build",
        "db_version",
        "game_date",
        "time_slot",
        "section_count",
        "section_schemas",
    ]
    assert record["game"] == "FM26"
    assert record["game_date"] == "2031-03-01"
    assert record["section_count"] == 7
    assert record["section_schemas"]["game_info"] == 46
    assert list(record["section_schemas"]) == sorted(record["section_schemas"])


def test_info_json_with_non_ascii_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fragment_path = build_container_fragment(save_name="Carrière 東京").write(
        tmp_path / "career.bin"
    )
    assert cli.main(["info", str(fragment_path), "--json", "--show-name"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["save_name"] == "Carrière 東京"


def test_not_a_save_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file_path = tmp_path / "Private Folder" / "notes.txt"
    file_path.parent.mkdir()
    file_path.write_text("hello", encoding="utf-8")
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNSUPPORTED
    error_output = capsys.readouterr().err
    assert error_output.startswith("fmsave: error:")
    assert "Private Folder" not in error_output


def test_missing_file_exits_2_without_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_path = tmp_path / "Private Folder" / "missing.bin"
    assert cli.main(["info", str(missing_path)]) == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "missing.bin" in error_output
    assert "Private Folder" not in error_output


def test_directory_exits_1(tmp_path: Path) -> None:
    assert cli.main(["info", str(tmp_path)]) == cli.EXIT_UNEXPECTED


def test_truncated_save_exits_1(tmp_path: Path) -> None:
    content = build_container_fragment().content
    file_path = tmp_path / "career.bin"
    file_path.write_bytes(content[:-10])
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNEXPECTED


def test_future_game_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sections = replaced_sections(save_game_summary=save_summary_body(version="27.0.1+3000001"))
    file_path = build_container_fragment(sections).write(tmp_path / "career.bin")
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNSUPPORTED
    assert "FM27" in capsys.readouterr().err


def test_layout_mismatch_exits_3(tmp_path: Path) -> None:
    sections = replaced_sections(game_info=game_info_body(build_numbers=(2329565, 2329565, 1)))
    file_path = build_container_fragment(sections).write(tmp_path / "career.bin")
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNSUPPORTED


def test_unknown_build_prints_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sections = replaced_sections(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(build_numbers=(2400000, 2400000, 2400000)),
    )
    file_path = build_container_fragment(sections).write(tmp_path / "career.bin")
    assert cli.main(["info", str(file_path)]) == cli.EXIT_OK
    error_output = capsys.readouterr().err
    assert "fmsave: warning:" in error_output
    assert "26.4.0" in error_output


def test_unexpected_exception_exits_1(
    fragment_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_info", explode)
    assert cli.main(["info", str(fragment_path)]) == cli.EXIT_UNEXPECTED
    error_output = capsys.readouterr().err
    assert "unexpected RuntimeError" in error_output
    assert "Traceback" not in error_output


def test_info_requires_a_path() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_module_entry_point_info_json(fragment_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "fmsave", "info", str(fragment_path), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["build"] == "26.3.2+2329565"
