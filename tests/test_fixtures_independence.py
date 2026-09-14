from __future__ import annotations

import ast
from pathlib import Path

FIXTURES_FOLDER = Path(__file__).resolve().parent / "fixtures"


def test_fixture_modules_never_import_fmsave() -> None:
    for module_path in sorted(FIXTURES_FOLDER.glob("*.py")):
        syntax_tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert not any(name == "fmsave" or name.startswith("fmsave.") for name in imported), (
                module_path.name
            )
