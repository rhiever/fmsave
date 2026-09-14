from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import fmsave
from fmsave import cli


def test_version_is_a_string() -> None:
    assert isinstance(fmsave.__version__, str)
    assert fmsave.__version__


def test_output_schema_version_is_int() -> None:
    assert fmsave.OUTPUT_SCHEMA_VERSION == 1


@pytest.mark.parametrize(
    "error_class",
    [
        fmsave.NotAFmSaveError,
        fmsave.CorruptSaveError,
        fmsave.UnsupportedGameError,
        fmsave.ReaderCheckError,
        fmsave.SaveChangedError,
        fmsave.SaveClosedError,
        fmsave.AmbiguousNameError,
    ],
)
def test_errors_share_a_base(error_class: type[Exception]) -> None:
    assert issubclass(error_class, fmsave.FmsaveError)


def test_unknown_build_warning_is_a_user_warning() -> None:
    assert issubclass(fmsave.UnknownBuildWarning, UserWarning)


def test_all_names_exist() -> None:
    for exported_name in fmsave.__all__:
        assert hasattr(fmsave, exported_name), exported_name


def test_public_api_names() -> None:
    assert {"open", "Save", "SaveInfo", "SectionInfo"} <= set(fmsave.__all__)


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"fmsave {fmsave.__version__}"


def test_cli_without_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_importing_the_main_module_does_not_run_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["fmsave", "--version"])
    monkeypatch.delitem(sys.modules, "fmsave.__main__", raising=False)
    importlib.import_module("fmsave.__main__")


def test_module_entry_point_runs() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "fmsave", "--version"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert completed.stdout.startswith("fmsave ")
