"""Tests for scripts/app_pins.py, with PyPI replaced by made-up project data."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

APP_PINS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "app_pins.py"
COMMITTED_PINS_PATH = Path(__file__).resolve().parents[1] / "docs" / "app" / "pins.json"


def load_app_pins_module() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("fmsave_app_pins", APP_PINS_PATH)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules["fmsave_app_pins"] = module
    module_spec.loader.exec_module(module)
    return module


app_pins = load_app_pins_module()


def wheel(version: str, *, yanked: bool = False) -> dict[str, object]:
    return {
        "packagetype": "bdist_wheel",
        "filename": f"fmsave-{version}-py3-none-any.whl",
        "yanked": yanked,
    }


def sdist(version: str) -> dict[str, object]:
    return {"packagetype": "sdist", "filename": f"fmsave-{version}.tar.gz", "yanked": False}


def project(latest: str, releases: Mapping[str, list[dict[str, object]]]) -> dict[str, object]:
    return {"info": {"version": latest}, "releases": dict(releases)}


def test_the_latest_release_with_a_pure_wheel_is_pinned() -> None:
    data = project("1.2.0", {"1.1.0": [wheel("1.1.0")], "1.2.0": [sdist("1.2.0"), wheel("1.2.0")]})
    assert app_pins.latest_version(data) == "1.2.0"


@pytest.mark.parametrize(
    "files",
    [[sdist("1.2.0")], [wheel("1.2.0", yanked=True)], []],
    ids=["sdist only", "yanked wheel", "no files"],
)
def test_a_latest_release_the_page_cannot_load_is_refused(files: list[dict[str, object]]) -> None:
    data = project("1.2.0", {"1.1.0": [wheel("1.1.0")], "1.2.0": files})
    with pytest.raises(app_pins.PinError, match="1.2.0"):
        app_pins.latest_version(data)


def test_waiting_polls_until_pypi_lists_the_version() -> None:
    answers = iter(
        [
            project("1.1.0", {"1.1.0": [wheel("1.1.0")]}),
            project("1.1.0", {"1.1.0": [wheel("1.1.0")], "1.2.0": [sdist("1.2.0")]}),
            project("1.2.0", {"1.1.0": [wheel("1.1.0")], "1.2.0": [wheel("1.2.0")]}),
        ]
    )
    sleeps: list[float] = []
    version = app_pins.wait_for_version(
        lambda: next(answers), "1.2.0", 600, sleep=sleeps.append, clock=lambda: 0.0
    )
    assert version == "1.2.0"
    assert len(sleeps) == 2


def test_waiting_gives_up_after_the_timeout() -> None:
    times = iter([0.0, 10.0, 700.0])
    with pytest.raises(app_pins.PinError, match="within 600 seconds"):
        app_pins.wait_for_version(
            lambda: project("1.1.0", {"1.1.0": [wheel("1.1.0")]}),
            "1.2.0",
            600,
            sleep=lambda _: None,
            clock=lambda: next(times),
        )


def test_main_writes_the_committed_pyodide_pin_with_fmsave(tmp_path: Path) -> None:
    committed = tmp_path / "pins.json"
    committed.write_text('{"pyodide": "9.9.9"}\n', encoding="utf-8")
    out = tmp_path / "site" / "app" / "pins.json"
    status = app_pins.main(
        [str(out), "--committed", str(committed)],
        fetch=lambda: project("1.2.0", {"1.2.0": [wheel("1.2.0")]}),
    )
    assert status == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"pyodide": "9.9.9", "fmsave": "1.2.0"}


def test_main_fails_without_writing_when_pypi_has_nothing_loadable(tmp_path: Path) -> None:
    out = tmp_path / "pins.json"
    status = app_pins.main(
        [str(out), "--committed", str(COMMITTED_PINS_PATH)],
        fetch=lambda: project("1.2.0", {"1.2.0": [sdist("1.2.0")]}),
    )
    assert status == 1
    assert not out.exists()


def test_the_committed_pins_hold_pyodide_and_leave_fmsave_to_the_build() -> None:
    committed = json.loads(COMMITTED_PINS_PATH.read_text(encoding="utf-8"))
    assert set(committed) == {"pyodide"}
    assert committed["pyodide"].count(".") == 2


def test_the_ci_smoke_check_installs_the_pyodide_the_page_pins() -> None:
    smoke = Path(__file__).resolve().parents[1] / "scripts" / "app-smoke"
    committed = json.loads(COMMITTED_PINS_PATH.read_text(encoding="utf-8"))
    package = json.loads((smoke / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((smoke / "package-lock.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["pyodide"] == committed["pyodide"]
    assert lock["packages"]["node_modules/pyodide"]["version"] == committed["pyodide"]
