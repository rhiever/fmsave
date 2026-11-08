"""Sync the shared block in explicitly named checkouts."""

import argparse
import difflib
from pathlib import Path

START = "<!-- shared-dev-standards:start -->"
END = "<!-- shared-dev-standards:end -->"
TEMPLATE = Path(__file__).with_name("dev-standards.md")


def render(current: str, template: str) -> str:
    lines = current.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == START]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END]
    rules = template.rstrip().splitlines()
    if not starts and not ends:
        newline = "\r\n" if "\r\n" in current else "\n"
        separator = "" if not current or current.endswith(newline * 2) else newline
        if current and not current.endswith(newline):
            separator += newline
        return current + separator + newline.join([START, *rules, END, ""])

    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("expected exactly one complete shared development block")
    start, end = starts[0], ends[0]
    if end < start:
        raise ValueError("shared development block markers are reversed")
    newline = lines[start][len(START) :]
    block = newline.join([START, *rules, ""]) + lines[end]
    return "".join([*lines[:start], block, *lines[end + 1 :]])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="show drift and exit nonzero")
    mode.add_argument("--write", action="store_true", help="update the shared block")
    parser.add_argument("checkouts", nargs="+", type=Path)
    args = parser.parse_args()
    template = TEMPLATE.read_text(encoding="utf-8")

    changes: list[tuple[Path, str, str]] = []
    for checkout in args.checkouts:
        if not (checkout / ".git").exists():
            parser.error(f"not a Git checkout root: {checkout}")
        path = checkout / "AGENTS.md"
        if path.is_symlink():
            parser.error(f"expected a regular file: {path}")
        current = path.read_bytes().decode("utf-8") if path.exists() else ""
        try:
            updated = render(current, template)
        except ValueError as error:
            parser.error(f"{path}: {error}")
        if current != updated:
            changes.append((path, current, updated))

    for path, current, updated in changes:
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
        print("".join(diff), end="")
        if args.write:
            path.write_bytes(updated.encode("utf-8"))
    return int(args.check and bool(changes))


if __name__ == "__main__":
    raise SystemExit(main())
