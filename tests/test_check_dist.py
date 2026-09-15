"""Tests for scripts/check_dist.py, run against small archives built in a temporary folder."""

from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

CHECK_DIST_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_dist.py"
VERSION = "1.2.3"
SDIST_ROOT = f"fmsave-{VERSION}"


def load_check_dist_module() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("fmsave_check_dist", CHECK_DIST_PATH)
    assert module_spec is not None and module_spec.loader is not None
    check_dist_module = importlib.util.module_from_spec(module_spec)
    sys.modules["fmsave_check_dist"] = check_dist_module
    module_spec.loader.exec_module(check_dist_module)
    return check_dist_module


check_dist = load_check_dist_module()


def clean_wheel_files() -> dict[str, bytes]:
    return {
        "fmsave/__init__.py": b'"""Example."""\n',
        "fmsave/py.typed": b"",
        "fmsave/readers/__init__.py": b"",
        f"fmsave-{VERSION}.dist-info/METADATA": b"Name: fmsave\nVersion: 1.2.3\n",
        f"fmsave-{VERSION}.dist-info/licenses/LICENSE": b"MIT\n",
        f"fmsave-{VERSION}.dist-info/RECORD": b"",
    }


def clean_sdist_files() -> dict[str, bytes]:
    return {
        f"{SDIST_ROOT}/PKG-INFO": b"Name: fmsave\n",
        f"{SDIST_ROOT}/pyproject.toml": b'[project]\nname = "fmsave"\n',
        f"{SDIST_ROOT}/README.md": b"# fmsave\n",
        f"{SDIST_ROOT}/LICENSE": b"MIT\n",
        f"{SDIST_ROOT}/src/fmsave/__init__.py": b'"""Example."""\n',
        f"{SDIST_ROOT}/src/fmsave/py.typed": b"",
    }


def write_wheel(dist_dir: Path, files: dict[str, bytes], version: str = VERSION) -> None:
    wheel_path = dist_dir / f"fmsave-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("fmsave/", b"")
        for path, content in files.items():
            wheel.writestr(path, content)


def write_sdist(
    dist_dir: Path,
    files: dict[str, bytes],
    version: str = VERSION,
    symlinks: dict[str, str] | None = None,
) -> None:
    root = f"fmsave-{version}"
    sdist_path = dist_dir / f"{root}.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as sdist:
        for directory in (root, f"{root}/src", f"{root}/src/fmsave"):
            directory_info = tarfile.TarInfo(directory)
            directory_info.type = tarfile.DIRTYPE
            sdist.addfile(directory_info)
        for path, content in files.items():
            file_info = tarfile.TarInfo(path)
            file_info.size = len(content)
            sdist.addfile(file_info, io.BytesIO(content))
        for path, target in (symlinks or {}).items():
            link_info = tarfile.TarInfo(path)
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = target
            sdist.addfile(link_info)


@pytest.fixture
def pyproject(tmp_path: Path) -> Path:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(f'[project]\nname = "fmsave"\nversion = "{VERSION}"\n')
    return pyproject_path


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / ".gitignore").write_text("*")
    return folder


def run_check(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    exit_code = check_dist.main([str(dist_dir), "--pyproject", str(pyproject)])
    return exit_code, capsys.readouterr().err


def test_clean_distributions_pass(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_wheel(dist_dir, clean_wheel_files())
    write_sdist(dist_dir, clean_sdist_files())
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 0, output
    assert "ok" in output


def test_test_builder_in_wheel_fails_naming_the_path(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_wheel(dist_dir, {**clean_wheel_files(), "tests/fixtures/container.py": b"x = 1\n"})
    write_sdist(dist_dir, clean_sdist_files())
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert "tests/fixtures/container.py is outside the allowlist" in output


def test_file_over_one_megabyte_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_wheel(dist_dir, {**clean_wheel_files(), "fmsave/large.py": b"#" * 1_500_000})
    write_sdist(dist_dir, clean_sdist_files())
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert "fmsave/large.py is larger than 1000000 bytes" in output


def test_wheel_without_typed_marker_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel_files = clean_wheel_files()
    del wheel_files["fmsave/py.typed"]
    write_wheel(dist_dir, wheel_files)
    write_sdist(dist_dir, clean_sdist_files())
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert "fmsave/py.typed is missing" in output


def test_private_folder_in_sdist_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private_path = f"{SDIST_ROOT}/.local/example.md"
    write_wheel(dist_dir, clean_wheel_files())
    write_sdist(dist_dir, {**clean_sdist_files(), private_path: b"private\n"})
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert f"{private_path} is outside the allowlist" in output
    assert f"{private_path} is inside a folder that is never shipped" in output


def test_sdist_with_the_uv_build_pyproject_backup_passes(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backup_path = f"{SDIST_ROOT}/pyproject.toml.orig"
    write_wheel(dist_dir, clean_wheel_files())
    write_sdist(dist_dir, {**clean_sdist_files(), backup_path: b'[project]\nname = "fmsave"\n'})
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 0, output


@pytest.mark.parametrize(
    "orig_path",
    [
        f"{SDIST_ROOT}/README.md.orig",
        f"{SDIST_ROOT}/src/pyproject.toml.orig",
        "pyproject.toml.orig",
    ],
)
def test_sdist_with_any_other_orig_file_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str], orig_path: str
) -> None:
    write_wheel(dist_dir, clean_wheel_files())
    write_sdist(dist_dir, {**clean_sdist_files(), orig_path: b"backup\n"})
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert f"{orig_path} is outside the allowlist" in output


def test_version_mismatch_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other_version = "9.9.9"
    wheel_files = {
        path.replace(VERSION, other_version): content
        for path, content in clean_wheel_files().items()
    }
    sdist_files = {
        path.replace(VERSION, other_version): content
        for path, content in clean_sdist_files().items()
    }
    write_wheel(dist_dir, wheel_files, version=other_version)
    write_sdist(dist_dir, sdist_files, version=other_version)
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert "version 9.9.9 does not match pyproject.toml version 1.2.3" in output


@pytest.mark.parametrize(
    ("member_path", "reason"),
    [
        ("fmsave/example.fm", "is a save file"),
        ("fmsave/tests/test_example.py", "is inside a folder that is never shipped"),
        ("fmsave/../outside.py", "is an unsafe path"),
        ("/fmsave/absolute.py", "is an unsafe path"),
    ],
)
def test_denied_wheel_members_fail(
    dist_dir: Path,
    pyproject: Path,
    capsys: pytest.CaptureFixture[str],
    member_path: str,
    reason: str,
) -> None:
    write_wheel(dist_dir, {**clean_wheel_files(), member_path: b"x"})
    write_sdist(dist_dir, clean_sdist_files())
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert f"{member_path} {reason}" in output


def test_symlink_in_sdist_fails(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link_path = f"{SDIST_ROOT}/src/fmsave/link.py"
    write_wheel(dist_dir, clean_wheel_files())
    write_sdist(dist_dir, clean_sdist_files(), symlinks={link_path: "/etc/passwd"})
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert f"{link_path} is not a regular file or directory" in output


def test_missing_sdist_and_unexpected_file_fail(
    dist_dir: Path, pyproject: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_wheel(dist_dir, clean_wheel_files())
    (dist_dir / "notes.txt").write_text("x")
    exit_code, output = run_check(dist_dir, pyproject, capsys)
    assert exit_code == 1
    assert "expected exactly one sdist, found 0" in output
    assert "notes.txt is not an expected distribution file" in output
