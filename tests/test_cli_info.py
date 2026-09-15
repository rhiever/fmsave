from __future__ import annotations

import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest

import fmsave
from fmsave import cli
from tests.fixtures.career import career_fragment
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    length_prefixed,
    save_summary_body,
    section_body,
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
    assert record["known_build"] is True
    assert record["game_date"] == "2031-03-01"
    assert record["time_slot"] == 66
    assert record["section_count"] == 7
    assert record["section_schemas"]["game_info"] == 46
    assert list(record["section_schemas"]) == sorted(record["section_schemas"])


SUMMARY_TEXTS = ("Alex Manager", "Northbridge", "Example League")


def summary_fragment_path(tmp_path: Path) -> Path:
    summary = save_summary_body(
        leading_strings=("Example League",),
        trailing_strings=("Alex Manager",),
        club_uid_after=("Northbridge", 5001),
    )
    return build_container_fragment(replaced_sections(save_game_summary=summary)).write(
        tmp_path / "career.bin"
    )


@pytest.mark.parametrize(
    ("json_output", "show_name"),
    [(False, False), (False, True), (True, False)],
    ids=["text", "text-show-name", "json"],
)
def test_info_prints_summary_strings_only_as_json_with_show_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], show_name: bool, json_output: bool
) -> None:
    arguments = ["info", str(summary_fragment_path(tmp_path))]
    if json_output:
        arguments.append("--json")
    if show_name:
        arguments.append("--show-name")
    assert cli.main(arguments) == cli.EXIT_OK
    output = capsys.readouterr().out
    assert "26.3.2+2329565" in output
    for summary_text in SUMMARY_TEXTS:
        assert summary_text not in output
    if json_output:
        assert "summary_strings" not in json.loads(output)


def test_info_json_with_show_name_includes_the_summary_strings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["info", str(summary_fragment_path(tmp_path)), "--json", "--show-name"]
    assert cli.main(arguments) == cli.EXIT_OK
    record = json.loads(capsys.readouterr().out)
    assert list(record)[-2:] == ["save_name", "summary_strings"]
    assert record["summary_strings"] == [
        "Example League",
        "26.3.2+2329565",
        "Alex Manager",
        "Northbridge",
    ]


def test_info_on_a_whole_career_shows_summary_strings_only_on_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    career_path = career_fragment().write(tmp_path / "Ünïcode folder" / "career.fm")
    assert cli.main(["info", str(career_path), "--json"]) == cli.EXIT_OK
    assert "summary_strings" not in json.loads(capsys.readouterr().out)
    assert cli.main(["info", str(career_path), "--json", "--show-name"]) == cli.EXIT_OK
    assert "Alex Manager" in json.loads(capsys.readouterr().out)["summary_strings"]


def test_fmsave_warnings_print_as_fmsave_warnings(
    fragment_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def warn_and_succeed(arguments: object) -> int:
        warnings.warn(fmsave.FmsaveWarning("an example caution"), stacklevel=1)
        return cli.EXIT_OK

    monkeypatch.setattr(cli, "run_info", warn_and_succeed)
    assert cli.main(["info", str(fragment_path)]) == cli.EXIT_OK
    assert "fmsave: warning: an example caution" in capsys.readouterr().err


def test_other_warnings_are_emitted_as_python_warnings(
    fragment_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def warn_and_succeed(arguments: object) -> int:
        warnings.warn("a library caution", DeprecationWarning, stacklevel=1)
        return cli.EXIT_OK

    monkeypatch.setattr(cli, "run_info", warn_and_succeed)
    with pytest.warns(DeprecationWarning, match="a library caution"):
        assert cli.main(["info", str(fragment_path)]) == cli.EXIT_OK
    assert "fmsave: warning" not in capsys.readouterr().err


def test_info_json_with_non_ascii_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fragment_path = build_container_fragment(save_name="Carrière 東京").write(
        tmp_path / "career.bin"
    )
    assert cli.main(["info", str(fragment_path), "--json", "--show-name"]) == cli.EXIT_OK
    json_output = capsys.readouterr().out
    assert json_output.isascii()
    assert json.loads(json_output)["save_name"] == "Carrière 東京"


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


def test_directory_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(tmp_path)]) == cli.EXIT_UNEXPECTED
    assert "unexpected" not in capsys.readouterr().err


def test_truncated_save_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = build_container_fragment().content
    file_path = tmp_path / "career.bin"
    file_path.write_bytes(content[:-10])
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNEXPECTED
    error_output = capsys.readouterr().err
    assert "unexpected" not in error_output
    assert "career.bin" in error_output


def test_short_game_info_error_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    short_game_info = section_body(".dat", 46, length_prefixed("26.2.0+0"))
    file_path = build_container_fragment(replaced_sections(game_info=short_game_info)).write(
        tmp_path / "Private Folder" / "career.bin"
    )
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNEXPECTED
    error_output = capsys.readouterr().err
    assert "fmsave: error: career.bin: game_info is damaged or was being written" in error_output
    assert "Private Folder" not in error_output


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
    captured_output = capsys.readouterr()
    assert "fmsave: warning:" in captured_output.err
    assert "26.4.0" in captured_output.err
    assert "(unknown build)" in captured_output.out


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


def test_warning_is_printed_before_a_failed_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sections = replaced_sections(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(build_numbers=(2400000, 2400000, 1)),
    )
    file_path = build_container_fragment(sections).write(tmp_path / "career.bin")
    assert cli.main(["info", str(file_path)]) == cli.EXIT_UNSUPPORTED
    error_lines = capsys.readouterr().err.splitlines()
    warning_indexes = [
        line_index
        for line_index, line in enumerate(error_lines)
        if line.startswith("fmsave: warning:") and "26.4.0" in line
    ]
    failure_indexes = [
        line_index
        for line_index, line in enumerate(error_lines)
        if line.startswith("fmsave: error:")
    ]
    assert warning_indexes, error_lines
    assert failure_indexes, error_lines
    assert warning_indexes[0] < failure_indexes[0]


def test_invalid_command_path_hides_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command_path = tmp_path / "Private Folder" / "career.fm"
    with pytest.raises(SystemExit) as exit_info:
        cli.main([str(command_path)])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "career.fm" in error_output
    assert "Private Folder" not in error_output


@pytest.mark.parametrize("path_style", ["posix", "windows"])
def test_unrecognized_path_argument_hides_folder(
    fragment_path: Path, path_style: str, capsys: pytest.CaptureFixture[str]
) -> None:
    if path_style == "windows":
        extra_argument = "C:\\Private Folder\\career.fm"
        expected_name = "career.fm"
    else:
        extra_argument = str(fragment_path)
        expected_name = fragment_path.name
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", str(fragment_path), extra_argument])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert expected_name in error_output
    assert "Private Folder" not in error_output


def test_os_error_without_strerror_names_the_error_type(
    fragment_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def raise_bare_os_error(arguments: object) -> int:
        raise OSError()

    monkeypatch.setattr(cli, "run_info", raise_bare_os_error)
    assert cli.main(["info", str(fragment_path)]) == cli.EXIT_UNEXPECTED
    error_output = capsys.readouterr().err
    assert "None" not in error_output
    assert "OSError" in error_output
    assert "unexpected" not in error_output


@pytest.mark.parametrize(
    ("raised_error", "expected_message"),
    [
        (IsADirectoryError(21, "Is a directory", "."), "cannot read the given path"),
        (FileNotFoundError(2, "No such file or directory", "."), "file not found: the given path"),
    ],
    ids=["os-error", "file-not-found"],
)
def test_empty_file_name_uses_the_given_path(
    fragment_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raised_error: OSError,
    expected_message: str,
) -> None:
    def raise_path_error(arguments: object) -> int:
        raise raised_error

    monkeypatch.setattr(cli, "run_info", raise_path_error)
    cli.main(["info", str(fragment_path)])
    assert expected_message in capsys.readouterr().err


@pytest.mark.parametrize(
    "flag_arguments",
    [
        ["info", "--json=/Example/Private Folder/career.fm", "a.fm"],
        ["info", "a.fm", "--show-name=C:\\Private Folder\\career.fm"],
        ["info", "--js=/Example/Private Folder/career.fm", "a.fm"],
        ["--version=/Example/Private Folder/career.fm"],
    ],
    ids=["json-posix", "show-name-windows", "abbreviated-json", "version"],
)
def test_flag_value_path_hides_folder(
    flag_arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(flag_arguments)
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "career.fm" in error_output
    assert "Private Folder" not in error_output


@pytest.mark.parametrize(
    ("separator_arguments", "expected_text"),
    [
        (["/", "extra"], "invalid choice: '/'"),
        (["\\", "extra"], "invalid choice: '\\\\'"),
        (["--help=extra", "/"], "argument -h/--help: ignored explicit argument 'extra'"),
    ],
    ids=["slash-command", "backslash-command", "help-option-name"],
)
def test_separator_only_argument_is_not_redacted(
    separator_arguments: list[str], expected_text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(separator_arguments)
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert expected_text in error_output
    assert "the given path" not in error_output


def test_main_without_argv_hides_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command_path = tmp_path / "Private Folder" / "career.fm"
    monkeypatch.setattr(sys, "argv", ["fmsave", str(command_path)])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "career.fm" in error_output
    assert "Private Folder" not in error_output


@pytest.mark.parametrize(
    "leading_arguments",
    [[], ["info", "a.fm"]],
    ids=["first-argument", "after-info"],
)
def test_short_option_glued_path_hides_folder(
    tmp_path: Path, leading_arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    glued_argument = f"-h-{tmp_path / 'Private Folder' / 'career.fm'}"
    with pytest.raises(SystemExit) as exit_info:
        cli.main([*leading_arguments, glued_argument])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "career.fm" in error_output
    assert "Private Folder" not in error_output


@pytest.mark.parametrize("path_style", ["posix", "windows"])
def test_paths_split_across_arguments_hide_every_folder(
    tmp_path: Path, path_style: str, capsys: pytest.CaptureFixture[str]
) -> None:
    if path_style == "windows":
        path_arguments = [
            "a.fm",
            "C:\\Users\\Fictional\\FM Saves\\c.fm",
            "D:\\Backup\\FM",
            "Saves\\c.fm",
        ]
        expected_name = "c.fm"
        folder_texts = ["Fictional", "FM Saves", "Backup"]
    else:
        path_arguments = [f"{tmp_path}/FM Saves/career.fm", "/fictional/FM", "Saves/career.fm"]
        expected_name = "career.fm"
        folder_texts = ["FM Saves", "fictional", str(tmp_path)]
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", *path_arguments])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert expected_name in error_output
    for folder_text in folder_texts:
        assert folder_text not in error_output


def test_flag_value_with_trailing_separator_keeps_its_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version=saves/"])
    assert exit_info.value.code == cli.EXIT_USAGE
    assert "ignored explicit argument 'saves'" in capsys.readouterr().err


def test_help_option_name_is_kept_beside_a_folder_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([f"--help={tmp_path / 'Hollowmere'}/"])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "argument -h/--help: ignored explicit argument 'Hollowmere'" in error_output
    assert str(tmp_path) not in error_output


def test_equals_sign_in_a_folder_name_hides_the_folder(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", "a.fm", "Season=SECRETDIR/career.fm"])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "career.fm" in error_output
    assert "Season" not in error_output
    assert "SECRETDIR" not in error_output


def test_trailing_separator_on_an_extra_argument_keeps_a_specific_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", "a.fm", "extra/"])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert "fmsave: error: unrecognized arguments: extra" in error_output
    assert cli.GENERIC_USAGE_MESSAGE not in error_output


@pytest.mark.parametrize(
    "argument_tokens",
    [
        ["x/" * 50_000],
        ["info", *[f"{token_index:02d}" + "/x" * 99 for token_index in range(50)]],
    ],
    ids=["one-long-argument", "many-arguments"],
)
def test_long_path_arguments_fail_quickly(
    argument_tokens: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    started_seconds = time.perf_counter()
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argument_tokens)
    elapsed_seconds = time.perf_counter() - started_seconds
    assert exit_info.value.code == cli.EXIT_USAGE
    assert elapsed_seconds < 10
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "argument_tokens",
    [
        ["Private Folder/--help"],
        ["Private Folder\\-h"],
        ["Private Folder/--version"],
        ["info", "a.fm", "Private Folder/--help"],
        ["info", "a.fm", "Private Folder/--json"],
    ],
    ids=["help", "short-help-windows", "version", "info-help", "info-parses"],
)
def test_redacted_arguments_that_do_not_fail_use_the_generic_message(
    argument_tokens: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argument_tokens)
    assert exit_info.value.code == cli.EXIT_USAGE
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    error_lines = captured_output.err.splitlines()
    assert error_lines[0].startswith("usage: fmsave [-h] [--version]")
    assert error_lines[-1] == f"fmsave: error: {cli.GENERIC_USAGE_MESSAGE}"
    assert "Private Folder" not in captured_output.err


def test_message_that_still_shows_a_folder_uses_the_generic_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def keep_argument(argument_token: str) -> str:
        return argument_token

    monkeypatch.setattr(cli, "redact_argument", keep_argument)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["info", "a.fm", "/Example/Private Folder/career.fm"])
    assert exit_info.value.code == cli.EXIT_USAGE
    error_output = capsys.readouterr().err
    assert f"fmsave: error: {cli.GENERIC_USAGE_MESSAGE}" in error_output
    assert "Private Folder" not in error_output
