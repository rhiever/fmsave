from __future__ import annotations

import ast
import dataclasses
import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import fmsave
import fmsave.checks
import fmsave.export
import fmsave.models
import fmsave.name_maps
from fmsave import cli
from fmsave.export import column_names
from fmsave.models.common import CodedValue

# Every module a caller may import from. At 1.0.0 each of them promises exactly its __all__ and
# nothing else, so a name added here without being added to __all__ is a promise made by
# accident.
PUBLIC_MODULES = [
    fmsave,
    fmsave.checks,
    fmsave.export,
    fmsave.models,
    fmsave.name_maps,
    cli,
]
# The two package modules are made of imports, so what they import is their surface. Everywhere
# else an import is a tool the module uses and not a name it offers.
RE_EXPORTING_MODULES = frozenset({"fmsave", "fmsave.models"})


def _all_order(name: str) -> tuple[int, str]:
    """The order __all__ is kept in: constants, then classes, then functions and aliases."""
    if name.isupper():
        return (0, name)
    if name[0].isupper():
        return (1, name)
    return (2, name)


def _defined_public_names(module: ModuleType) -> set[str]:
    """Every public name a module's own source puts at its top level."""
    module_file = module.__file__
    assert module_file is not None
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        match node:
            case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                names.append(node.name)
            case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
                names.append(name)
            case ast.TypeAlias(name=ast.Name(id=name)):
                names.append(name)
            case ast.Import() | ast.ImportFrom() if module.__name__ in RE_EXPORTING_MODULES:
                names.extend(
                    imported.asname or imported.name.split(".")[0] for imported in node.names
                )
            case _:
                continue
    return {name for name in names if not name.startswith("_") and name != "__all__"}


def test_version_is_a_string() -> None:
    assert isinstance(fmsave.__version__, str)
    assert fmsave.__version__


def test_output_schema_version_is_int() -> None:
    assert type(fmsave.OUTPUT_SCHEMA_VERSION) is int
    assert fmsave.OUTPUT_SCHEMA_VERSION == 2


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


def test_warnings_share_a_base() -> None:
    assert "FmsaveWarning" in fmsave.__all__
    assert issubclass(fmsave.FmsaveWarning, UserWarning)
    assert issubclass(fmsave.UnknownBuildWarning, fmsave.FmsaveWarning)


def test_all_names_exist() -> None:
    for exported_name in fmsave.__all__:
        assert hasattr(fmsave, exported_name), exported_name


def test_public_api_names() -> None:
    assert {
        "open",
        "Save",
        "SaveInfo",
        "SectionInfo",
        "CodedValue",
        "field_status",
        "read_competition_names",
    } <= set(fmsave.__all__)


def test_all_model_names_exist() -> None:
    for exported_name in fmsave.models.__all__:
        assert hasattr(fmsave.models, exported_name), exported_name
    assert {
        "CodedValue",
        "ContractEndSource",
        "SaveInfo",
        "SectionInfo",
        "TransferValueState",
    } <= set(fmsave.models.__all__)


def test_the_package_exports_every_record_type() -> None:
    """A record a caller is handed is a record they can name as `fmsave.<Name>`."""
    assert set(fmsave.models.__all__) <= set(fmsave.__all__)


@pytest.mark.parametrize("module", PUBLIC_MODULES, ids=lambda module: module.__name__)
def test_every_public_module_has_an_all(module: ModuleType) -> None:
    exported_names = getattr(module, "__all__", None)
    assert exported_names is not None, module.__name__
    assert list(exported_names) == sorted(set(exported_names), key=_all_order), module.__name__
    for exported_name in exported_names:
        assert hasattr(module, exported_name), f"{module.__name__}.{exported_name}"


@pytest.mark.parametrize("module", PUBLIC_MODULES, ids=lambda module: module.__name__)
def test_a_public_module_defines_nothing_public_beyond_its_all(module: ModuleType) -> None:
    """Everything a public module holds beyond its __all__ carries a leading underscore.

    A name without one is API at 1.0.0 whether or not it was meant to be, so a new helper
    either joins __all__ deliberately or is named privately.
    """
    assert _defined_public_names(module) <= set(module.__all__), module.__name__


def test_the_types_of_public_fields_are_exported() -> None:
    """A caller handed one of these values can declare its type."""
    for type_name in ("FieldStatus", "ReaderStatus", "TransferValueState", "ContractEndSource"):
        assert type_name in fmsave.__all__, type_name


def test_a_failed_check_is_readable_from_its_fields() -> None:
    assert issubclass(fmsave.GateCheckError, fmsave.ReaderCheckError)
    assert {"GateCheckError", "ReaderCheck"} <= set(fmsave.__all__)
    check_fields = {field.name for field in dataclasses.fields(fmsave.ReaderCheck)}
    assert {"reader", "record_count", "gates", "anomalies"} == check_fields


def test_the_command_line_promises_only_its_entry_point_and_exit_codes() -> None:
    assert set(cli.__all__) == {
        "EXIT_OK",
        "EXIT_UNEXPECTED",
        "EXIT_UNSUPPORTED",
        "EXIT_USAGE",
        "main",
    }


def test_every_public_record_type_can_be_walked() -> None:
    """The documentation site walks every record type, so every one of them must have columns."""
    for exported_name in fmsave.models.__all__:
        record_type: object = getattr(fmsave.models, exported_name)
        if not isinstance(record_type, type) or record_type is CodedValue:
            continue
        if not dataclasses.is_dataclass(record_type):
            continue
        assert column_names(record_type), exported_name


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == cli.EXIT_OK
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
