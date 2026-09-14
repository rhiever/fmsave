#!/usr/bin/env python3
"""Repository guard for fmsave.

Blocks content that must never be committed or published: files under the private
folder, save files and save bytes, binary files, oversized files, notebooks with
outputs, text copied from the private folder, and locally denylisted names, uids
and terms.

Usage:
    python scripts/guard.py --staged              # pre-commit hook
    python scripts/guard.py --tracked             # CI and manual runs
    python scripts/guard.py --history             # every blob and message in history
    python scripts/guard.py --commit-msg PATH     # a commit message or any text to publish

Checks that need local private files run only when those files exist, so CI runs
the structural checks only. Findings never print the matched text.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 1_000_000
SAVE_MAGIC = bytes.fromhex("0201666d662e")
PRIVATE_FOLDER_NAME = ".local"
GUARD_CONFIG_NAME = "guard.json"
DENYLIST_RELATIVE_PATH = PurePosixPath("corpus/denylist.txt")
OVERLAP_WINDOW_LINES = 6
OVERLAP_MINIMUM_ALPHANUMERIC = 40
OVERLAP_MAX_SOURCE_BYTES = 5_000_000
MINIMUM_UID_DIGITS = 6
WORD_PATTERN = re.compile(r"[^\W_]+(?:['’.\-][^\W_]+)*")
UID_PATTERN = re.compile(r"(?<![0-9A-Za-z])[0-9]{6,}(?![0-9A-Za-z])")
CODE_FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class Blob:
    """One file version to check; `location` is what findings print."""

    path: str
    location: str
    content: bytes


@dataclass(frozen=True, slots=True)
class Finding:
    location: str
    reason: str


@dataclass(slots=True)
class PrivateReferences:
    """Reference data that exists only on the maintainer's machine."""

    overlap_windows: dict[str, str] = field(default_factory=dict[str, str])
    denied_names: set[tuple[str, ...]] = field(default_factory=set[tuple[str, ...]])
    denied_name_lengths: set[int] = field(default_factory=set[int])
    denied_uids: set[str] = field(default_factory=set[str])
    denied_term_patterns: list[re.Pattern[str]] = field(default_factory=list[re.Pattern[str]])


def decode_text(content: bytes) -> str | None:
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def tokenize(text: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_PATTERN.finditer(text)]


def iter_overlap_windows(lines: Sequence[str]) -> Iterator[tuple[int, str]]:
    """Yield (first line number, digest) for each run of non-blank lines worth comparing."""
    kept_lines: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        normalized_line = " ".join(raw_line.split())
        if normalized_line:
            kept_lines.append((line_number, normalized_line))
    for start_index in range(len(kept_lines) - OVERLAP_WINDOW_LINES + 1):
        window = kept_lines[start_index : start_index + OVERLAP_WINDOW_LINES]
        window_text = "\n".join(line_text for _, line_text in window)
        if sum(character.isalnum() for character in window_text) < OVERLAP_MINIMUM_ALPHANUMERIC:
            continue
        yield window[0][0], hashlib.sha256(window_text.encode("utf-8")).hexdigest()


def blank_code_fences(lines: list[str]) -> list[str]:
    """Blank out fenced code blocks, keeping line positions."""
    result_lines: list[str] = []
    inside_fence = False
    for line in lines:
        if CODE_FENCE_PATTERN.match(line):
            inside_fence = not inside_fence
            result_lines.append("")
        else:
            result_lines.append("" if inside_fence else line)
    return result_lines


def load_guard_config(private_folder: Path) -> tuple[list[str], list[str]]:
    config_path = private_folder / GUARD_CONFIG_NAME
    if not config_path.is_file():
        return [], []
    loaded: object = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"guard: {GUARD_CONFIG_NAME} must hold a JSON object")
    config: dict[str, object] = {str(key): value for key, value in loaded.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return string_list(config.get("overlap_exempt_code_fences")), string_list(
        config.get("denied_terms")
    )


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def load_denylist(denylist_text: str, references: PrivateReferences) -> None:
    for raw_line in denylist_text.splitlines():
        entry = raw_line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.isascii() and entry.isdigit():
            if len(entry) >= MINIMUM_UID_DIGITS:
                references.denied_uids.add(entry)
            continue
        tokens = tuple(tokenize(entry))
        if len(tokens) >= 2:
            references.denied_names.add(tokens)
            references.denied_name_lengths.add(len(tokens))


def load_private_references(repository_root: Path) -> PrivateReferences | None:
    private_folder = repository_root / PRIVATE_FOLDER_NAME
    if not private_folder.is_dir():
        return None
    exempt_patterns, denied_terms = load_guard_config(private_folder)
    references = PrivateReferences()
    for term in denied_terms:
        references.denied_term_patterns.append(
            re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        )
    for source_path in sorted(private_folder.rglob("*")):
        if source_path.is_symlink() or not source_path.is_file():
            continue
        if source_path.stat().st_size > OVERLAP_MAX_SOURCE_BYTES:
            continue
        source_text = decode_text(source_path.read_bytes())
        if source_text is None:
            continue
        relative_name = source_path.relative_to(private_folder).as_posix()
        source_lines = source_text.splitlines()
        if relative_name.endswith(".md") and any(
            fnmatch.fnmatch(relative_name, pattern) for pattern in exempt_patterns
        ):
            source_lines = blank_code_fences(source_lines)
        for _, digest in iter_overlap_windows(source_lines):
            references.overlap_windows.setdefault(digest, relative_name)
    denylist_path = private_folder / DENYLIST_RELATIVE_PATH
    if denylist_path.is_file():
        load_denylist(denylist_path.read_text(encoding="utf-8"), references)
    return references


def text_findings(location: str, text: str, references: PrivateReferences) -> list[Finding]:
    """Denylist and denied-term findings, one per offending line."""
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line_location = f"{location}:{line_number}"
        if references.denied_uids and any(
            match.group(0) in references.denied_uids for match in UID_PATTERN.finditer(line)
        ):
            findings.append(Finding(line_location, "contains a denylisted uid"))
        if references.denied_names:
            tokens = tokenize(line)
            if any(
                tuple(tokens[start : start + length]) in references.denied_names
                for length in references.denied_name_lengths
                for start in range(len(tokens) - length + 1)
            ):
                findings.append(Finding(line_location, "contains a denylisted name"))
        if any(pattern.search(line) for pattern in references.denied_term_patterns):
            findings.append(Finding(line_location, "contains a denied internal term"))
    return findings


def overlap_findings(location: str, text: str, references: PrivateReferences) -> list[Finding]:
    for start_line, digest in iter_overlap_windows(text.splitlines()):
        private_source = references.overlap_windows.get(digest)
        if private_source is not None:
            reason = f"shares {OVERLAP_WINDOW_LINES}+ lines with a private file ({private_source})"
            return [Finding(f"{location}:{start_line}", reason)]
    return []


def notebook_has_outputs(text: str) -> bool:
    try:
        notebook: object = json.loads(text)
    except json.JSONDecodeError:
        return True
    if not isinstance(notebook, dict):
        return True
    cells: object = notebook.get("cells", [])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(cells, list):
        return True
    for cell in cells:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(cell, dict) and (cell.get("outputs") or cell.get("execution_count")):  # pyright: ignore[reportUnknownMemberType]
            return True
    return False


def check_blob(blob: Blob, references: PrivateReferences | None) -> list[Finding]:
    findings: list[Finding] = []
    blob_path = PurePosixPath(blob.path)
    if PRIVATE_FOLDER_NAME in blob_path.parts:
        findings.append(Finding(blob.location, "is inside the private folder"))
    if blob_path.name.casefold().endswith(".fm"):
        findings.append(Finding(blob.location, "is a save file (*.fm)"))
    if len(blob.content) > MAX_FILE_BYTES:
        findings.append(Finding(blob.location, f"is larger than {MAX_FILE_BYTES} bytes"))
    if SAVE_MAGIC in blob.content:
        findings.append(Finding(blob.location, "contains save file magic bytes"))
    text = decode_text(blob.content)
    if text is None:
        findings.append(Finding(blob.location, "is binary (NUL byte or invalid UTF-8)"))
        return findings
    if blob_path.suffix == ".ipynb" and notebook_has_outputs(text):
        findings.append(Finding(blob.location, "is a notebook with outputs"))
    if references is not None:
        findings.extend(overlap_findings(blob.location, text, references))
        findings.extend(text_findings(blob.location, text, references))
    return findings


def run_git(
    repository_root: Path, arguments: Sequence[str], input_bytes: bytes | None = None
) -> bytes:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository_root, input=input_bytes, check=True, capture_output=True
    )
    return completed.stdout


def split_null_terminated(raw_output: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in raw_output.split(b"\x00") if item]


def staged_blobs(repository_root: Path) -> Iterator[Blob]:
    listing = run_git(
        repository_root, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]
    )
    for path in split_null_terminated(listing):
        yield Blob(path, path, run_git(repository_root, ["show", f":{path}"]))


def tracked_blobs(repository_root: Path) -> Iterator[Blob]:
    for path in split_null_terminated(run_git(repository_root, ["ls-files", "-z"])):
        yield Blob(path, path, run_git(repository_root, ["show", f":{path}"]))


def history_blobs(repository_root: Path) -> Iterator[Blob]:
    listing = run_git(repository_root, ["rev-list", "--objects", "--all"]).decode(
        "utf-8", "surrogateescape"
    )
    object_paths: dict[str, str] = {}
    for line in listing.splitlines():
        object_id, _, path = line.partition(" ")
        if path and object_id not in object_paths:
            object_paths[object_id] = path
    if not object_paths:
        return
    batch_input = ("\n".join(object_paths) + "\n").encode("ascii")
    type_listing = run_git(
        repository_root, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], batch_input
    ).decode("ascii")
    for type_line in type_listing.splitlines():
        object_id, _, object_type = type_line.partition(" ")
        if object_type != "blob":
            continue
        path = object_paths[object_id]
        content = run_git(repository_root, ["cat-file", "blob", object_id])
        yield Blob(path, f"{path}@{object_id[:12]}", content)


def history_message_findings(repository_root: Path, references: PrivateReferences) -> list[Finding]:
    raw_log = run_git(repository_root, ["log", "--all", "--format=%H%x00%B%x1e"]).decode(
        "utf-8", "replace"
    )
    findings: list[Finding] = []
    for record in raw_log.split("\x1e"):
        commit_id, _, message = record.strip("\n").partition("\x00")
        if commit_id:
            findings.extend(text_findings(f"commit {commit_id[:12]} message", message, references))
    return findings


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Block private or save-derived content.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check files staged for commit")
    mode.add_argument("--tracked", action="store_true", help="check every tracked file")
    mode.add_argument(
        "--history", action="store_true", help="check every blob and message in history"
    )
    mode.add_argument(
        "--commit-msg", metavar="PATH", help="check a commit message or other text file"
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="repository root (default: git top level)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    root_argument: Path | None = arguments.root
    repository_root = root_argument or Path(
        run_git(Path.cwd(), ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    )
    references = load_private_references(repository_root)
    findings: list[Finding] = []
    message_path: str | None = arguments.commit_msg
    if message_path is not None:
        if references is not None:
            message_text = Path(message_path).read_text(encoding="utf-8", errors="replace")
            findings.extend(text_findings("message", message_text, references))
    else:
        if arguments.staged:
            blobs = staged_blobs(repository_root)
        elif arguments.tracked:
            blobs = tracked_blobs(repository_root)
        else:
            blobs = history_blobs(repository_root)
        for blob in blobs:
            findings.extend(check_blob(blob, references))
        if arguments.history and references is not None:
            findings.extend(history_message_findings(repository_root, references))
    for finding in findings:
        print(f"guard: {finding.location}: {finding.reason}", file=sys.stderr)
    if findings:
        print(f"guard: {len(findings)} problem(s) found; blocked", file=sys.stderr)
        return 1
    scope = "structural checks and private references" if references else "structural checks only"
    print(f"guard: ok ({scope})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
