#!/usr/bin/env python3
"""Write the version pins the web app loads, with fmsave pinned to a release on PyPI.

Usage:
    python scripts/app_pins.py OUT [--wait-for VERSION] [--timeout SECONDS]

The Pyodide version comes from docs/app/pins.json, which is committed and changed by hand.
fmsave is pinned to the newest release on PyPI that has a pure-Python wheel, so the page
never asks for a version PyPI does not have yet. With --wait-for, the script waits until
PyPI lists that version and pins it: the release workflow uses this to redeploy the page
with the version it has just published. If PyPI does not answer a plain build, the pins
leave fmsave out and the page installs the newest release itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

PYPI_URL = "https://pypi.org/pypi/fmsave/json"
COMMITTED_PINS = Path(__file__).resolve().parents[1] / "docs" / "app" / "pins.json"
POLL_SECONDS = 15.0
FETCH_ATTEMPTS = 4
# What a PyPI outage or a bad response looks like from urllib and json.
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, OSError, ValueError)
USER_AGENT = "fmsave-docs-build"

type Fetch = Callable[[], Mapping[str, object]]


class PinError(Exception):
    """PyPI does not offer a version the page can load."""


def fetch_pypi() -> Mapping[str, object]:
    request = urllib.request.Request(
        PYPI_URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return cast(Mapping[str, object], json.load(response))


def has_pure_wheel(files: object) -> bool:
    """Whether a PyPI release's files include a wheel Pyodide can install."""
    if not isinstance(files, list):
        return False
    for entry in cast(list[object], files):
        if not isinstance(entry, dict):
            continue
        details = cast(dict[str, object], entry)
        filename = details.get("filename")
        if (
            details.get("packagetype") == "bdist_wheel"
            and isinstance(filename, str)
            and filename.endswith("-none-any.whl")
            and not details.get("yanked", False)
        ):
            return True
    return False


def loadable_versions(project: Mapping[str, object]) -> set[str]:
    releases = project.get("releases")
    if not isinstance(releases, dict):
        return set()
    return {
        version
        for version, files in cast(dict[str, object], releases).items()
        if has_pure_wheel(files)
    }


def latest_version(project: Mapping[str, object]) -> str:
    """The version PyPI calls latest, provided the page can load it."""
    info = project.get("info")
    version = cast(dict[str, object], info).get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or version not in loadable_versions(project):
        raise PinError(f"PyPI's latest fmsave ({version}) has no pure-Python wheel")
    return version


def wait_for_version(
    fetch: Fetch,
    version: str,
    timeout: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Poll PyPI until it lists version, then pin PyPI's latest; fail after timeout seconds.

    Pinning the latest rather than version itself means a pre-release or an older backport
    never replaces a newer stable release on the page.
    """
    deadline = clock() + timeout
    while True:
        try:
            project = fetch()
            if version in loadable_versions(project):
                return latest_version(project)
        except FETCH_ERRORS as error:
            print(f"app_pins: PyPI did not answer ({error}); trying again", file=sys.stderr)
        if clock() >= deadline:
            raise PinError(f"PyPI did not list fmsave {version} within {timeout:.0f} seconds")
        sleep(POLL_SECONDS)


def fetch_with_retries(
    fetch: Fetch, *, sleep: Callable[[float], None] = time.sleep
) -> Mapping[str, object] | None:
    """PyPI's project data, or None when PyPI does not answer after a few tries."""
    for attempt in range(FETCH_ATTEMPTS):
        try:
            return fetch()
        except FETCH_ERRORS as error:
            print(f"app_pins: PyPI did not answer ({error})", file=sys.stderr)
            if attempt + 1 < FETCH_ATTEMPTS:
                sleep(POLL_SECONDS)
    return None


def pins(committed: Mapping[str, object], fmsave_version: str | None) -> dict[str, object]:
    pyodide = committed.get("pyodide")
    if not isinstance(pyodide, str) or not pyodide:
        raise PinError("docs/app/pins.json needs a pyodide version")
    if fmsave_version is None:
        return {"pyodide": pyodide}
    return {"pyodide": pyodide, "fmsave": fmsave_version}


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetch = fetch_pypi,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description="Write the version pins the web app loads.")
    parser.add_argument("out", type=Path, help="where to write the pins, in the built site")
    parser.add_argument("--wait-for", metavar="VERSION", help="wait until PyPI lists VERSION")
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds to wait")
    parser.add_argument("--committed", type=Path, default=COMMITTED_PINS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    committed = cast(Mapping[str, object], json.loads(args.committed.read_text(encoding="utf-8")))
    try:
        version: str | None
        if args.wait_for:
            version = wait_for_version(fetch, args.wait_for, args.timeout, sleep=sleep)
        else:
            project = fetch_with_retries(fetch, sleep=sleep)
            # With PyPI down, the docs still deploy: the page then installs the newest
            # fmsave itself, unpinned, until the next build pins it again.
            version = None if project is None else latest_version(project)
        written = pins(committed, version)
    except PinError as error:
        print(f"app_pins: {error}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(written, indent=2) + "\n", encoding="utf-8")
    print(f"app_pins: Pyodide {written['pyodide']}, fmsave {written.get('fmsave', 'unpinned')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
