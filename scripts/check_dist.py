#!/usr/bin/env python3
"""Check built distributions before they are published.

Usage:
    python scripts/check_dist.py DIST_DIR [--pyproject PATH]

DIST_DIR must hold exactly one fmsave wheel and one fmsave sdist. The check fails, listing
every problem, when an archive holds a path outside its allowlist, a file larger than 1 MB,
a link or other special member, or an unsafe path; when the wheel lacks fmsave/py.typed; or
when the version in the file names does not match pyproject.toml.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

PROJECT_NAME = "fmsave"
MAX_FILE_BYTES = 1_000_000
DEFAULT_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
IGNORED_DIST_FILES = frozenset({".gitignore"})
DENIED_PATH_PARTS = frozenset({"tests", "fuzz", "scripts", ".github", ".local"})
DENIED_SUFFIX = ".fm"
TYPED_MARKER = f"{PROJECT_NAME}/py.typed"
WHEEL_NAME_PATTERN = re.compile(
    rf"^{PROJECT_NAME}-(?P<version>[^-]+)(?:-[^-]+)?-[^-]+-[^-]+-[^-]+\.whl$"
)
SDIST_NAME_PATTERN = re.compile(rf"^{PROJECT_NAME}-(?P<version>[^-]+)\.tar\.gz$")
ZIP_FILE_TYPE_MASK = 0o170000
ZIP_REGULAR_FILE_TYPES = (0, 0o100000)
ZIP_DIRECTORY_TYPE = 0o040000


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """One entry of a wheel or sdist."""

    path: str
    size: int
    kind: str  # "file", "directory" or "other"


@dataclass(frozen=True, slots=True)
class Allowlist:
    """Allowed paths: anything under a prefix, or an exact file path."""

    prefixes: tuple[str, ...]
    exact_paths: tuple[str, ...]

    def allows_file(self, path: str) -> bool:
        return path in self.exact_paths or any(path.startswith(prefix) for prefix in self.prefixes)

    def allows_directory(self, path: str) -> bool:
        """A directory is allowed inside an allowed prefix or on the way to an allowed path."""
        if any(path.startswith(prefix) for prefix in self.prefixes):
            return True
        directory_prefix = path + "/"
        return any(
            allowed.startswith(directory_prefix) for allowed in (*self.prefixes, *self.exact_paths)
        )


def wheel_allowlist(version: str) -> Allowlist:
    return Allowlist(
        prefixes=(f"{PROJECT_NAME}/", f"{PROJECT_NAME}-{version}.dist-info/"), exact_paths=()
    )


def sdist_allowlist(version: str) -> Allowlist:
    root = f"{PROJECT_NAME}-{version}"
    return Allowlist(
        prefixes=(f"{root}/src/{PROJECT_NAME}/",),
        exact_paths=(
            f"{root}/pyproject.toml",
            # uv_build keeps the project's own pyproject.toml under this name.
            f"{root}/pyproject.toml.orig",
            f"{root}/README.md",
            f"{root}/LICENSE",
            f"{root}/PKG-INFO",
        ),
    )


def read_project_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as pyproject_file:
        project_table: object = tomllib.load(pyproject_file).get("project")
    version: object = None
    if isinstance(project_table, dict):
        version = cast("dict[str, object]", project_table).get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit(f"check_dist: {pyproject_path} has no project version")
    return version


def wheel_members(wheel_path: Path) -> list[ArchiveMember]:
    members: list[ArchiveMember] = []
    with zipfile.ZipFile(wheel_path) as wheel:
        for info in wheel.infolist():
            file_type = (info.external_attr >> 16) & ZIP_FILE_TYPE_MASK
            if info.is_dir() or file_type == ZIP_DIRECTORY_TYPE:
                kind = "directory"
            elif file_type in ZIP_REGULAR_FILE_TYPES:
                kind = "file"
            else:
                kind = "other"
            members.append(ArchiveMember(info.filename, info.file_size, kind))
    return members


def sdist_members(sdist_path: Path) -> list[ArchiveMember]:
    members: list[ArchiveMember] = []
    with tarfile.open(sdist_path, "r:gz") as sdist:
        for info in sdist.getmembers():
            if info.isdir():
                kind = "directory"
            elif info.isfile():
                kind = "file"
            else:
                kind = "other"
            members.append(ArchiveMember(info.name, info.size, kind))
    return members


def member_problems(
    archive_name: str, members: Sequence[ArchiveMember], allowlist: Allowlist
) -> list[str]:
    problems: list[str] = []
    for member in members:
        path = member.path.rstrip("/") if member.kind == "directory" else member.path
        where = f"{archive_name}: {member.path}"
        parts = path.split("/")
        if path.startswith("/") or "\\" in path or any(part in ("", ".", "..") for part in parts):
            problems.append(f"{where} is an unsafe path")
            continue
        if member.kind == "other":
            problems.append(f"{where} is not a regular file or directory")
            continue
        denied_parts = sorted(DENIED_PATH_PARTS.intersection(parts))
        if denied_parts:
            problems.append(f"{where} is inside a folder that is never shipped ({denied_parts[0]})")
        if path.casefold().endswith(DENIED_SUFFIX):
            problems.append(f"{where} is a save file (*{DENIED_SUFFIX})")
        if member.kind == "directory":
            if not allowlist.allows_directory(path):
                problems.append(f"{where} is outside the allowlist")
            continue
        if not allowlist.allows_file(path):
            problems.append(f"{where} is outside the allowlist")
        if member.size > MAX_FILE_BYTES:
            problems.append(f"{where} is larger than {MAX_FILE_BYTES} bytes")
    return problems


def check_archive(
    archive_path: Path, version: str, *, is_wheel: bool
) -> tuple[list[ArchiveMember], list[str]]:
    try:
        members = wheel_members(archive_path) if is_wheel else sdist_members(archive_path)
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        return [], [f"{archive_path.name}: cannot be read ({error})"]
    allowlist = wheel_allowlist(version) if is_wheel else sdist_allowlist(version)
    return members, member_problems(archive_path.name, members, allowlist)


def check_dist(dist_dir: Path, version: str) -> list[str]:
    """Every problem found in DIST_DIR for the project at `version`; empty when it passes."""
    if not dist_dir.is_dir():
        return [f"{dist_dir} is not a folder"]
    problems: list[str] = []
    wheels: list[Path] = []
    sdists: list[Path] = []
    for entry in sorted(dist_dir.iterdir()):
        if entry.name in IGNORED_DIST_FILES and entry.is_file():
            continue
        wheel_match = WHEEL_NAME_PATTERN.match(entry.name)
        sdist_match = SDIST_NAME_PATTERN.match(entry.name)
        name_match = wheel_match or sdist_match
        if name_match is None or not entry.is_file():
            problems.append(f"{entry.name} is not an expected distribution file")
            continue
        (wheels if wheel_match else sdists).append(entry)
        if name_match.group("version") != version:
            problems.append(
                f"{entry.name}: version {name_match.group('version')} does not match "
                f"pyproject.toml version {version}"
            )
    for kind_name, found in (("wheel", wheels), ("sdist", sdists)):
        if len(found) != 1:
            problems.append(f"expected exactly one {kind_name}, found {len(found)}")
    for wheel_path in wheels:
        members, archive_problems = check_archive(wheel_path, version, is_wheel=True)
        problems.extend(archive_problems)
        if members and not any(
            member.kind == "file" and member.path == TYPED_MARKER for member in members
        ):
            problems.append(f"{wheel_path.name}: {TYPED_MARKER} is missing")
    for sdist_path in sdists:
        problems.extend(check_archive(sdist_path, version, is_wheel=False)[1])
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check built distributions before publishing.")
    parser.add_argument("dist_dir", type=Path, help="folder holding the wheel and sdist")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT,
        help="pyproject.toml holding the expected version (default: the repository's)",
    )
    arguments = parser.parse_args(argv)
    dist_dir: Path = arguments.dist_dir
    pyproject_path: Path = arguments.pyproject
    version = read_project_version(pyproject_path)
    problems = check_dist(dist_dir, version)
    for problem in problems:
        print(f"check_dist: {problem}", file=sys.stderr)
    if problems:
        print(f"check_dist: {len(problems)} problem(s) found", file=sys.stderr)
        return 1
    print(f"check_dist: ok ({PROJECT_NAME} {version} wheel and sdist)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
