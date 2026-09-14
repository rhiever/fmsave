from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_FOLDER = Path(__file__).resolve().parent / "fixtures"

RUNTIME_IMPORT_PROBE = """
import importlib
import json
import pkgutil
import sys

import tests.fixtures

imported_modules = []
for module_info in pkgutil.walk_packages(tests.fixtures.__path__, "tests.fixtures."):
    importlib.import_module(module_info.name)
    imported_modules.append(module_info.name)
loaded_fmsave_modules = sorted(
    module_name
    for module_name in sys.modules
    if module_name == "fmsave" or module_name.startswith("fmsave.")
)
print(json.dumps({"imported": imported_modules, "fmsave": loaded_fmsave_modules}))
"""


def test_fixture_modules_never_import_fmsave() -> None:
    module_paths = sorted(FIXTURES_FOLDER.rglob("*.py"))
    assert module_paths, "no fixture modules were scanned"
    for module_path in module_paths:
        syntax_tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert not any(name == "fmsave" or name.startswith("fmsave.") for name in imported), (
                module_path.relative_to(FIXTURES_FOLDER).as_posix()
            )


def test_fixture_modules_never_load_fmsave_at_runtime() -> None:
    completed_probe = subprocess.run(
        [sys.executable, "-c", RUNTIME_IMPORT_PROBE],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed_probe.returncode == 0, completed_probe.stderr
    probe_report = json.loads(completed_probe.stdout.strip().splitlines()[-1])
    assert probe_report["imported"], "no fixture modules were imported"
    assert probe_report["fmsave"] == [], probe_report["fmsave"]
