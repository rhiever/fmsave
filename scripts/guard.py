#!/usr/bin/env python3
"""Repository guard for fmsave.

Blocks content that must never be committed or published: files under the private
folder, save files and save bytes, binary files, oversized files, notebooks with
outputs, symbolic links, submodules, long encoded data, text copied from the private
folder, banned internal-process wording, runs of per-save figures in the published prose,
and locally denylisted names, uids and terms in file contents, file paths and
messages.

Banned internal-process wording is the house vocabulary of how the work was organised, which
means nothing to a reader of a public repository: the words in `BANNED_WORDS` and plan numbers
of the form M1, M2 or M3, in file contents, in file paths and in a commit message about to be
written. It is matched on the same normalized and accent-folded forms the denylist uses, and
the word found is printed, because it is a house style rule rather than private content. Two
paths are exempt, because they are where the rule itself is written down: `scripts/guard.py`
and `tests/test_guard.py`. The check does **not** run in history mode, since history is never
rewritten and a past message or path cannot be fixed.

Runs of per-save figures are looked for in `PROSE_PATHS` alone -- the published README and
changelog -- as two or three figures separated by slashes or commas, which is how one
measurement per save is written. A bound is a single figure or a range with a word between its
ends, so `0.99`, `0.9 to 1.0` and `30% to 43%` pass while `0.11 / 0.22 / 0.33` and
`11,111, 22,222 and 33,333` do not. Version numbers, dates and dotted or hyphenated tokens are
not figure runs and pass.

Long encoded data is looked for in text files up to the size limit, and in commit and
annotated tag messages. It is any of:
- an unbroken run of 512+ hex digits, or of 1,024+ characters from the standard and
  URL-safe base64 alphabets;
- 4+ consecutive lines on which one run of 40+ base64 characters holds all but at most 8
  of the non-whitespace characters. The run is standard base64, or URL-safe base64 with up
  to two `=` after it that holds upper case, lower case and digits and has at most one
  `-` or `_` in 8 characters. When every such run is hex digits, 512+ characters in all
  with an a-f digit among them;
- a hex dump of 64+ bytes with an a-f digit: consecutive lines of 4+ groups of 2, 4, 6 or
  8 hex digits, after up to 2 leading tokens and an optional offset, and before any text
  column, where a `*` line for repeated rows does not end the dump;
- 64+ two-digit hex byte pairs, each with an optional 0x prefix, separated by whitespace,
  commas or colons, with an a-f digit or a 0x prefix among them;
- 32+ consecutive backslash-x escapes.

Usage:
    python scripts/guard.py --staged              # pre-commit hook
    python scripts/guard.py --tracked             # CI and manual runs
    python scripts/guard.py --history             # every blob, path and message in history
    python scripts/guard.py --commit-msg PATH     # a commit message or any text to publish

Checks that need local private files run only when those files exist, so CI runs
the structural checks only. The private folder is looked up in the main worktree,
so linked worktrees get the same checks. Findings never print text matched against a private
reference; a file whose path matches is shown by its object id instead of its path.
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import hashlib
import itertools
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 1_000_000
SAVE_MAGIC = bytes.fromhex("0201666d662e")
SYMBOLIC_LINK_MODE = "120000"
SUBMODULE_MODE = "160000"
HEX_RUN_MINIMUM = 512
BASE64_RUN_MINIMUM = 1024
WRAPPED_BASE64_LINE_MINIMUM = 40
WRAPPED_BASE64_MINIMUM_LINES = 4
WRAPPED_BASE64_OTHER_CHARACTERS = 8
URLSAFE_BASE64_CHARACTERS_PER_SEPARATOR = 8
HEX_PAIR_MINIMUM = 64
ESCAPED_BYTE_MINIMUM = 32
HEX_DUMP_MINIMUM_GROUPS = 4
HEX_DUMP_MINIMUM_BYTES = 64
HEX_DUMP_GROUP_LENGTHS = frozenset({2, 4, 6, 8})
HEX_DUMP_OFFSET_MINIMUM_DIGITS = 4
HEX_DUMP_OFFSET_MAXIMUM_DIGITS = 16
HEX_DUMP_REPEATED_ROWS_MARKER = "*"
HEX_DUMP_MAXIMUM_PREFIX_TOKENS = 2
HEX_DIGIT_CHARACTERS = "0123456789abcdefABCDEF"
HEX_LETTER_PATTERN = re.compile(r"[a-fA-F]")
# The lookbehind lets a match start only at the start of a run, which keeps the scan linear.
HEX_RUN_PATTERN = re.compile(rf"(?<![0-9A-Fa-f])[0-9A-Fa-f]{{{HEX_RUN_MINIMUM},}}")
BASE64_RUN_PATTERN = re.compile(rf"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{{{BASE64_RUN_MINIMUM},}}")
WRAPPED_BASE64_LINE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{{{WRAPPED_BASE64_LINE_MINIMUM},}}"
)
URLSAFE_BASE64_LINE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{{{WRAPPED_BASE64_LINE_MINIMUM},}}"
)
ESCAPED_BYTE_RUN_PATTERN = re.compile(
    rf"(?<!\\x[0-9A-Fa-f]{{2}})(?:\\x[0-9A-Fa-f]{{2}}){{{ESCAPED_BYTE_MINIMUM},}}+"
)
# No minimum count and only possessive repeats: each sequence is matched once, whole, and its
# pairs are counted afterwards, which keeps the scan linear.
HEX_PAIR_SEQUENCE_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:0[xX])?[0-9A-Fa-f]{2}(?![0-9A-Za-z])"
    r"(?:[\s,:]++(?:0[xX])?[0-9A-Fa-f]{2}(?![0-9A-Za-z]))*+"
)
HEX_PAIR_SEPARATOR_PATTERN = re.compile(r"[\s,:]+")
# Inside a hex pair sequence an x can only come from a 0x prefix.
HEX_LETTER_OR_PREFIX_PATTERN = re.compile(r"[a-fA-FxX]")
HEX_DIGITS_PATTERN = re.compile(r"[0-9A-Fa-f]+")
UPPERCASE_PATTERN = re.compile(r"[A-Z]")
LOWERCASE_PATTERN = re.compile(r"[a-z]")
DIGIT_PATTERN = re.compile(r"[0-9]")
PRIVATE_FOLDER_NAME = ".local"
GUARD_CONFIG_NAME = "guard.json"
GUARD_CONFIG_KEYS = ("overlap_exempt_code_fences", "denied_terms")
DENYLIST_RELATIVE_PATH = PurePosixPath("corpus/denylist.txt")
OVERLAP_WINDOW_LINES = 6
OVERLAP_MINIMUM_ALPHANUMERIC = 40
OVERLAP_MAX_SOURCE_BYTES = 5_000_000
MINIMUM_UID_DIGITS = 6
WORD_PATTERN = re.compile(r"[^\W_]+(?:['’.\-][^\W_]+)*")
UID_PATTERN = re.compile(r"(?<![0-9A-Za-z])[0-9]{6,}(?![0-9A-Za-z])")
FENCE_OPENER_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
PATH_SEPARATOR_PATTERN = re.compile(r"[_\-/.]+")
MATCH_REASONS = (
    "contains a denylisted uid",
    "contains a denylisted name",
    "contains a denied internal term",
)
UID_REASON_INDEX, NAME_REASON_INDEX, TERM_REASON_INDEX = range(len(MATCH_REASONS))
# The house vocabulary of how the work was organised, which a public reader cannot resolve.
BANNED_WORDS = (
    "task",
    "tasks",
    "review",
    "reviews",
    "reviewer",
    "reviewers",
    "subagent",
    "subagents",
    "ledger",
    "ledgers",
    "controller",
    "controllers",
    "milestone",
    "milestones",
    "golden",
)
# Matched against casefolded text, so the alternatives need no upper-case spellings.
BANNED_WORD_PATTERN = re.compile(rf"(?<![0-9a-z])(?:{'|'.join(BANNED_WORDS)})(?![0-9a-z])")
PLAN_NUMBER_PATTERN = re.compile(r"(?<![0-9a-z])m[123](?![0-9a-z])")
# Where the rule is written down, so the words appear there on purpose.
BANNED_WORDING_EXEMPT_PATHS = frozenset({"scripts/guard.py", "tests/test_guard.py"})
# The published prose, where a run of per-save figures has no business being.
PROSE_PATHS = frozenset({"README.md", "CHANGELOG.md"})
FIGURE = r"[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?%?"
# Two or three figures separated by slashes, or by commas with an optional "and" before the
# last: one measurement per save. A lone figure and a worded range are neither and pass.
SLASH_FIGURE_RUN_PATTERN = re.compile(
    rf"(?<![\w./-])({FIGURE})(?:[ \t]*/[ \t]*({FIGURE})){{1,2}}(?![\w./-])"
)
COMMA_FIGURE_RUN_PATTERN = re.compile(
    rf"(?<![\w./-])({FIGURE})(?:,[ \t]+({FIGURE})){{1,2}}"
    rf"(?:[ \t]+and[ \t]+({FIGURE}))?(?![\w./-])"
)
FIGURE_PATTERN = re.compile(FIGURE)
# What tells a measurement from a list of small code values: a decimal point, a per cent sign
# or a thousands separator in any of the figures, or two digits or more in every one of them.
MEASUREMENT_MARKS = ".,%"
MEASUREMENT_MINIMUM_DIGITS = 2


@dataclass(frozen=True, slots=True)
class Blob:
    """One file version to check; `location` is what findings print, `mode` is the git mode."""

    path: str
    location: str
    object_id: str
    mode: str
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
    denied_path_names: set[tuple[str, ...]] = field(default_factory=set[tuple[str, ...]])
    denied_path_name_lengths: set[int] = field(default_factory=set[int])
    denied_uids: set[str] = field(default_factory=set[str])
    denied_term_patterns: list[re.Pattern[str]] = field(default_factory=list[re.Pattern[str]])
    denied_path_term_patterns: list[re.Pattern[str]] = field(default_factory=list[re.Pattern[str]])


def decode_text(content: bytes) -> str | None:
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def normalize_text(text: str) -> str:
    """NFKC plus casefold: the form every private comparison starts from."""
    return unicodedata.normalize("NFKC", text).casefold()


def fold_accents(text: str) -> str:
    """Remove combining marks after canonical decomposition."""
    decomposed_text = unicodedata.normalize("NFD", text)
    return "".join(
        character for character in decomposed_text if not unicodedata.combining(character)
    )


def comparison_forms(lines: Sequence[str]) -> list[list[str]]:
    """Normalized lines, plus an accent-folded copy when folding changes anything."""
    normalized_lines = [normalize_text(line) for line in lines]
    folded_lines = [fold_accents(line) for line in normalized_lines]
    if folded_lines == normalized_lines:
        return [normalized_lines]
    return [normalized_lines, folded_lines]


def tokenize(text: str) -> list[str]:
    return [match.group(0) for match in WORD_PATTERN.finditer(text)]


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


def blank_code_fences(lines: Sequence[str]) -> list[str]:
    """Blank out closed fenced code blocks, keeping line positions.

    Follows CommonMark: an opener is 3+ backticks or tildes indented at most 3 spaces;
    the closer uses the same character, is at least as long and carries no info string.
    An unclosed fence exempts nothing, so its lines stay prose.
    """
    result_lines = list(lines)
    line_index = 0
    while line_index < len(lines):
        opener = FENCE_OPENER_PATTERN.match(lines[line_index])
        if opener is None or (opener.group(1).startswith("`") and "`" in opener.group(2)):
            line_index += 1
            continue
        fence_marker = opener.group(1)
        closer_pattern = re.compile(
            rf"^ {{0,3}}{re.escape(fence_marker[0])}{{{len(fence_marker)},}}[ \t]*$"
        )
        closer_index = next(
            (
                candidate_index
                for candidate_index in range(line_index + 1, len(lines))
                if closer_pattern.match(lines[candidate_index])
            ),
            None,
        )
        if closer_index is None:
            break
        for blanked_index in range(line_index, closer_index + 1):
            result_lines[blanked_index] = ""
        line_index = closer_index + 1
    return result_lines


def json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def json_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value]  # pyright: ignore[reportUnknownVariableType]


def config_string_list(config: dict[str, object], key: str) -> list[str]:
    items = json_list(config.get(key, []))
    if items is None or not all(isinstance(item, str) for item in items):
        raise SystemExit(f"guard: {GUARD_CONFIG_NAME}: {key!r} must be a list of strings")
    return [item for item in items if isinstance(item, str)]


def load_guard_config(private_folder: Path) -> tuple[list[str], list[str]]:
    config_path = private_folder / GUARD_CONFIG_NAME
    if not config_path.is_file():
        return [], []
    config = json_object(json.loads(config_path.read_text(encoding="utf-8-sig")))
    if config is None:
        raise SystemExit(f"guard: {GUARD_CONFIG_NAME} must hold a JSON object")
    unknown_keys = sorted(set(config) - set(GUARD_CONFIG_KEYS))
    if unknown_keys:
        raise SystemExit(
            f"guard: {GUARD_CONFIG_NAME}: unknown key(s) {', '.join(map(repr, unknown_keys))};"
            f" allowed keys are {', '.join(GUARD_CONFIG_KEYS)}"
        )
    return (
        config_string_list(config, "overlap_exempt_code_fences"),
        config_string_list(config, "denied_terms"),
    )


def load_denylist(denylist_text: str, references: PrivateReferences) -> None:
    for raw_line in denylist_text.splitlines():
        entry = normalize_text(raw_line).strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.isascii() and entry.isdigit():
            if len(entry) >= MINIMUM_UID_DIGITS:
                references.denied_uids.add(entry)
            continue
        for (entry_form,) in comparison_forms([entry]):
            tokens = tuple(tokenize(entry_form))
            if len(tokens) >= 2:
                references.denied_names.add(tokens)
                references.denied_name_lengths.add(len(tokens))
                path_tokens = tuple(tokenize(PATH_SEPARATOR_PATTERN.sub(" ", entry_form)))
                references.denied_path_names.add(path_tokens)
                references.denied_path_name_lengths.add(len(path_tokens))


def boundary_pattern(term_text: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term_text)}(?![A-Za-z0-9])")


def add_denied_term(term: str, references: PrivateReferences) -> None:
    """Compile a term for whitespace-normalized text and for paths, in each comparison form."""
    for (term_form,) in comparison_forms([term]):
        text_form = " ".join(term_form.split())
        path_form = " ".join(PATH_SEPARATOR_PATTERN.sub(" ", term_form).split())
        references.denied_term_patterns.append(boundary_pattern(text_form))
        references.denied_path_term_patterns.append(boundary_pattern(path_form))


def load_private_references(private_root: Path) -> PrivateReferences | None:
    private_folder = private_root / PRIVATE_FOLDER_NAME
    if not private_folder.is_dir():
        return None
    exempt_patterns, denied_terms = load_guard_config(private_folder)
    references = PrivateReferences()
    for term in denied_terms:
        add_denied_term(term, references)
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
        load_denylist(denylist_path.read_text(encoding="utf-8-sig"), references)
    return references


def join_nonblank_lines(lines: Sequence[str]) -> tuple[str, list[int], list[int]]:
    """Whitespace-normalized text of the non-blank lines, with each line's offset and number."""
    collapsed_lines: list[str] = []
    line_offsets: list[int] = []
    line_numbers: list[int] = []
    next_offset = 0
    for line_number, line in enumerate(lines, start=1):
        collapsed_line = " ".join(line.split())
        if collapsed_line:
            collapsed_lines.append(collapsed_line)
            line_offsets.append(next_offset)
            line_numbers.append(line_number)
            next_offset += len(collapsed_line) + 1
    return " ".join(collapsed_lines), line_offsets, line_numbers


def private_match_lines(
    lines: Sequence[str],
    references: PrivateReferences,
    names: set[tuple[str, ...]],
    name_lengths: set[int],
    term_patterns: Sequence[re.Pattern[str]],
) -> list[tuple[int, str]]:
    """(line number, reason) pairs for denylisted uids and names and denied terms.

    Names and terms may span line breaks; each is reported at the line where it starts.
    """
    matches: set[tuple[int, int]] = set()
    for form_lines in comparison_forms(lines):
        if references.denied_uids:
            for line_number, line in enumerate(form_lines, start=1):
                if any(
                    match.group(0) in references.denied_uids for match in UID_PATTERN.finditer(line)
                ):
                    matches.add((line_number, UID_REASON_INDEX))
        if names:
            numbered_tokens = [
                (line_number, token)
                for line_number, line in enumerate(form_lines, start=1)
                for token in tokenize(line)
            ]
            tokens = [token for _, token in numbered_tokens]
            for length in name_lengths:
                for start in range(len(tokens) - length + 1):
                    if tuple(tokens[start : start + length]) in names:
                        matches.add((numbered_tokens[start][0], NAME_REASON_INDEX))
        if term_patterns:
            joined_text, line_offsets, line_numbers = join_nonblank_lines(form_lines)
            if not joined_text:
                continue
            for pattern in term_patterns:
                for match in pattern.finditer(joined_text):
                    line_index = max(bisect.bisect_right(line_offsets, match.start()) - 1, 0)
                    matches.add((line_numbers[line_index], TERM_REASON_INDEX))
    return [
        (line_number, MATCH_REASONS[reason_index]) for line_number, reason_index in sorted(matches)
    ]


def banned_wording(lines: Sequence[str]) -> list[tuple[int, str]]:
    """(line number, wording) for each banned word or plan number, at the line it starts on.

    The lines are compared in the normalized and accent-folded forms the denylist uses, so a
    mixed-case, full-width or decomposed spelling cannot slip one through.
    """
    matches: set[tuple[int, str]] = set()
    for form_lines in comparison_forms(lines):
        for line_number, line in enumerate(form_lines, start=1):
            for pattern in (BANNED_WORD_PATTERN, PLAN_NUMBER_PATTERN):
                for match in pattern.finditer(line):
                    matches.add((line_number, match.group(0)))
    return sorted(matches)


def banned_wording_findings(location: str, path: str, text: str) -> list[Finding]:
    """Banned wording in a file's contents and in its path, unless the path is exempt."""
    if path in BANNED_WORDING_EXEMPT_PATHS:
        return []
    findings = [
        Finding(f"{location}:{line_number}", f"uses banned internal wording ({wording})")
        for line_number, wording in banned_wording(text.splitlines())
    ]
    path_text = PATH_SEPARATOR_PATTERN.sub(" ", normalize_text(path))
    findings.extend(
        Finding(location, f"path uses banned internal wording ({wording})")
        for _, wording in banned_wording([path_text])
    )
    return findings


def is_measurement_run(figures: Sequence[str]) -> bool:
    """Whether a run of figures reads as measurements rather than as a list of code values.

    A measurement carries a decimal point, a per cent sign or a thousands separator, or else
    the whole run is figures of two digits or more. So `0.11 / 0.22`, `11,111 / 22,222` and
    `44, 55 and 66` are measurements while `3, 4 and 16` and `1, 2 and 3` are not.
    """
    if any(mark in figure for figure in figures for mark in MEASUREMENT_MARKS):
        return True
    return all(len(figure) >= MEASUREMENT_MINIMUM_DIGITS for figure in figures)


def figure_run_findings(location: str, path: str, text: str) -> list[Finding]:
    """Runs of two or three separated figures in the published prose, one per save.

    Only `PROSE_PATHS` are read: a bound written as one figure or as a worded range is
    legitimate everywhere and is not a run, so nothing else needs the check.
    """
    if path not in PROSE_PATHS:
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        runs = (
            match.group(0)
            for pattern in (SLASH_FIGURE_RUN_PATTERN, COMMA_FIGURE_RUN_PATTERN)
            for match in pattern.finditer(line)
        )
        if any(is_measurement_run(FIGURE_PATTERN.findall(run)) for run in runs):
            findings.append(
                Finding(f"{location}:{line_number}", "contains a run of per-save figures")
            )
    return findings


def text_findings(location: str, text: str, references: PrivateReferences) -> list[Finding]:
    """Denylist and denied-term findings, each at the line where the match starts."""
    return [
        Finding(f"{location}:{line_number}", reason)
        for line_number, reason in private_match_lines(
            text.splitlines(),
            references,
            references.denied_names,
            references.denied_name_lengths,
            references.denied_term_patterns,
        )
    ]


def path_findings(location: str, path: str, references: PrivateReferences) -> list[Finding]:
    """Denylist and denied-term findings for a path; `_`, `-`, `/` and `.` separate tokens."""
    path_text = PATH_SEPARATOR_PATTERN.sub(" ", normalize_text(path))
    return [
        Finding(location, f"path {reason}")
        for _, reason in private_match_lines(
            [path_text],
            references,
            references.denied_path_names,
            references.denied_path_name_lengths,
            references.denied_path_term_patterns,
        )
    ]


def overlap_findings(location: str, text: str, references: PrivateReferences) -> list[Finding]:
    for start_line, digest in iter_overlap_windows(text.splitlines()):
        private_source = references.overlap_windows.get(digest)
        if private_source is not None:
            reason = f"shares {OVERLAP_WINDOW_LINES}+ lines with a private file ({private_source})"
            return [Finding(f"{location}:{start_line}", reason)]
    return []


def notebook_has_outputs(text: str) -> bool:
    """True for a notebook with outputs or execution counts (nbformat 3 or 4), or unparseable."""
    try:
        notebook = json_object(json.loads(text))
    except json.JSONDecodeError:
        return True
    if notebook is None:
        return True
    worksheets = json_list(notebook.get("worksheets", []))
    if worksheets is None:
        return True
    cell_list_values: list[object] = [notebook.get("cells", [])]
    for worksheet in worksheets:
        worksheet_object = json_object(worksheet)
        if worksheet_object is not None:
            cell_list_values.append(worksheet_object.get("cells", []))
    for cell_list_value in cell_list_values:
        cells = json_list(cell_list_value)
        if cells is None:
            return True
        for cell in cells:
            cell_object = json_object(cell)
            if cell_object is not None and (
                cell_object.get("outputs")
                or cell_object.get("execution_count")
                or cell_object.get("prompt_number")
            ):
                return True
    return False


def unbroken_runs(lines: Sequence[str]) -> Iterator[tuple[int, str, int]]:
    """(line number, kind, length) of each unbroken hex or base64 run.

    A run made only of hex characters is reported once, as hex. Line breaks never belong
    to a run, so scanning line by line finds the same runs.
    """
    for line_number, line in enumerate(lines, start=1):
        for match in HEX_RUN_PATTERN.finditer(line):
            yield line_number, "hex", match.end() - match.start()
        for match in BASE64_RUN_PATTERN.finditer(line):
            if HEX_RUN_PATTERN.fullmatch(match.group(0)) is None:
                yield line_number, "base64", match.end() - match.start()


def longest_span(pattern: re.Pattern[str], line: str) -> tuple[int, int]:
    """(start, end) of the longest match of `pattern` in `line`; (0, 0) when there is none."""
    longest_start, longest_end = 0, 0
    for match in pattern.finditer(line):
        if match.end() - match.start() > longest_end - longest_start:
            longest_start, longest_end = match.span()
    return longest_start, longest_end


def longest_urlsafe_span(line: str) -> tuple[int, int]:
    """(start, end) of the longest URL-safe base64 run in `line`, with up to two `=` after it."""
    longest_start, longest_end = 0, 0
    for match in URLSAFE_BASE64_LINE_PATTERN.finditer(line):
        padded_end = match.end()
        if line.startswith("==", padded_end):
            padded_end += 2
        elif line.startswith("=", padded_end):
            padded_end += 1
        if padded_end - match.start() > longest_end - longest_start:
            longest_start, longest_end = match.start(), padded_end
    return longest_start, longest_end


def hex_run_state(line: str, start: int, end: int) -> tuple[bool, bool]:
    """(made only of hex digits, holds an a-f digit) for the run `line[start:end]`."""
    if HEX_DIGITS_PATTERN.fullmatch(line, start, end) is None:
        return False, False
    return True, HEX_LETTER_PATTERN.search(line, start, end) is not None


def wrapped_line_run(line: str) -> tuple[int, bool, bool] | None:
    """(length, all hex digits, holds an a-f digit) of the run that makes `line` a wrapped line.

    None when no run qualifies. The run must hold all but at most 8 of the line's
    non-whitespace characters. It is the longest standard base64 run of 40+ characters or,
    failing that, the longest URL-safe run of 40+ characters plus up to two `=`, which must
    also hold an upper-case letter, a lower-case letter and a digit, with at most one
    character in 8 a `-` or `_`.
    """
    standard_start, standard_end = longest_span(WRAPPED_BASE64_LINE_PATTERN, line)
    urlsafe_start, urlsafe_end = longest_urlsafe_span(line)
    if not standard_end and not urlsafe_end:
        return None
    shortest_run = len("".join(line.split())) - WRAPPED_BASE64_OTHER_CHARACTERS
    if standard_end and standard_end - standard_start >= shortest_run:
        is_hex, has_hex_letter = hex_run_state(line, standard_start, standard_end)
        return standard_end - standard_start, is_hex, has_hex_letter
    urlsafe_length = urlsafe_end - urlsafe_start
    separator_count = line.count("-", urlsafe_start, urlsafe_end) + line.count(
        "_", urlsafe_start, urlsafe_end
    )
    if (
        urlsafe_end
        and urlsafe_length >= shortest_run
        and UPPERCASE_PATTERN.search(line, urlsafe_start, urlsafe_end)
        and LOWERCASE_PATTERN.search(line, urlsafe_start, urlsafe_end)
        and DIGIT_PATTERN.search(line, urlsafe_start, urlsafe_end)
        and separator_count * URLSAFE_BASE64_CHARACTERS_PER_SEPARATOR <= urlsafe_length
    ):
        is_hex, has_hex_letter = hex_run_state(line, urlsafe_start, urlsafe_end)
        return urlsafe_length, is_hex, has_hex_letter
    return None


def wrapped_base64_runs(lines: Sequence[str]) -> Iterator[tuple[int, str, int]]:
    """(first line number, kind, characters) of each stretch of wrapped base64 or hex.

    A stretch is 4 or more consecutive lines that `wrapped_line_run` accepts, as in
    `base64.encodebytes` output, PEM bodies and quoted source lines; its length is the total
    of their runs. A stretch made only of hex digits is reported as wrapped hex, and only
    from 512 characters and with an a-f digit among them, so lists of digests and blocks of
    decimal literals pass.
    """
    streak_start = 0
    streak_lines = 0
    streak_characters = 0
    streak_is_hex = True
    streak_has_hex_letter = False
    for line_number, line in enumerate(itertools.chain(lines, [""]), start=1):
        line_run = wrapped_line_run(line)
        if line_run is not None:
            run_length, run_is_hex, run_has_hex_letter = line_run
            if not streak_lines:
                streak_start = line_number
                streak_is_hex = True
                streak_has_hex_letter = False
            streak_lines += 1
            streak_characters += run_length
            streak_is_hex = streak_is_hex and run_is_hex
            streak_has_hex_letter = streak_has_hex_letter or run_has_hex_letter
            continue
        if streak_lines >= WRAPPED_BASE64_MINIMUM_LINES:
            if not streak_is_hex:
                yield streak_start, "wrapped base64", streak_characters
            elif streak_characters >= HEX_RUN_MINIMUM and streak_has_hex_letter:
                yield streak_start, "wrapped hex", streak_characters
        streak_lines = 0
        streak_characters = 0


def hex_pair_runs(text: str) -> Iterator[tuple[int, int]]:
    """(offset, length) of each sequence of 64+ hex byte pairs between whitespace, commas or colons.

    A sequence counts only when it holds an a-f digit or a 0x prefix, so lists of two-digit
    decimal numbers and clock times pass.
    """
    shortest_length = 3 * HEX_PAIR_MINIMUM - 1
    for match in HEX_PAIR_SEQUENCE_PATTERN.finditer(text):
        start, end = match.span()
        if end - start < shortest_length:
            continue
        if HEX_LETTER_OR_PREFIX_PATTERN.search(text, start, end) is None:
            continue
        if len(HEX_PAIR_SEPARATOR_PATTERN.findall(text, start, end)) + 1 >= HEX_PAIR_MINIMUM:
            yield start, end - start


def hex_dump_tokens_digits(tokens: Sequence[str], first: int) -> tuple[int, bool] | None:
    """(hex digits, holds an a-f digit) of dump `tokens` from `first` on, or None when not a dump.

    An offset may come first: 4 to 16 hex digits, known by a 0x prefix, a trailing colon, or
    a digit count unlike the next token's; it is not counted. Groups of 2, 4, 6 or 8 hex
    digits follow, up to the first other token, so a text column after them is ignored. A
    dump line has 4 or more groups.
    """
    group_start = first
    if len(tokens) - first >= 2:
        offset_token = tokens[first]
        has_prefix = offset_token.startswith(("0x", "0X"))
        has_colon = offset_token.endswith(":")
        offset_digits = offset_token[2 if has_prefix else 0 : len(offset_token) - int(has_colon)]
        if (
            HEX_DUMP_OFFSET_MINIMUM_DIGITS <= len(offset_digits) <= HEX_DUMP_OFFSET_MAXIMUM_DIGITS
            and not offset_digits.strip(HEX_DIGIT_CHARACTERS)
            and (has_prefix or has_colon or len(offset_digits) != len(tokens[first + 1]))
        ):
            group_start = first + 1
    group_count = 0
    digit_count = 0
    has_letter = False
    for token in itertools.islice(tokens, group_start, None):
        if len(token) not in HEX_DUMP_GROUP_LENGTHS or token.strip(HEX_DIGIT_CHARACTERS):
            break
        group_count += 1
        digit_count += len(token)
        has_letter = has_letter or not token.isdigit()
    if group_count < HEX_DUMP_MINIMUM_GROUPS:
        return None
    return digit_count, has_letter


def hex_dump_line_digits(line: str) -> tuple[int, bool] | None:
    """(hex digits, holds an a-f digit) of a hex dump line, or None when `line` is not one.

    The whitespace-separated tokens are read once, and again with 1 and with 2 leading
    tokens dropped, taking the first reading that is a dump line. That way a dump quoted
    behind a comment marker, a blockquote or a short prose lead-in still counts.
    """
    tokens = line.split()
    for first in range(HEX_DUMP_MAXIMUM_PREFIX_TOKENS + 1):
        dump_tokens = hex_dump_tokens_digits(tokens, first)
        if dump_tokens is not None:
            return dump_tokens
    return None


def hex_dump_runs(lines: Sequence[str]) -> Iterator[tuple[int, int]]:
    """(first line number, hex digits) of each hex dump of 64+ bytes that holds an a-f digit.

    A dump is a stretch of consecutive lines that `hex_dump_line_digits` accepts, as printed
    by `xxd`, `hexdump -C` and `od -tx1`. A `*` line, which those tools print in place of
    repeated rows, neither counts nor ends a dump.
    """
    streak_start = 0
    streak_digits = 0
    streak_has_letter = False
    for line_number, line in enumerate(itertools.chain(lines, [""]), start=1):
        if streak_digits and line.strip() == HEX_DUMP_REPEATED_ROWS_MARKER:
            continue
        dump_line = hex_dump_line_digits(line)
        if dump_line is not None:
            digit_count, has_letter = dump_line
            if not streak_digits:
                streak_start = line_number
                streak_has_letter = False
            streak_digits += digit_count
            streak_has_letter = streak_has_letter or has_letter
            continue
        if streak_digits >= 2 * HEX_DUMP_MINIMUM_BYTES and streak_has_letter:
            yield streak_start, streak_digits
        streak_digits = 0


def encoded_run_findings(location: str, text: str) -> list[Finding]:
    """Encoded data long enough to carry smuggled bytes; only its kind and length print.

    Covers unbroken hex and base64 runs, base64 or hex wrapped over consecutive lines, hex
    dumps, hex byte pairs between whitespace, commas or colons, and runs of backslash-x
    escapes. Each finding sits at the line where its data starts; a hex dump that starts on
    the same line as a reported hex byte pair sequence is the same data and is not repeated.
    """
    runs: list[tuple[int, str, int]] = []
    lines = text.splitlines()
    if HEX_RUN_PATTERN.search(text) or BASE64_RUN_PATTERN.search(text):
        runs.extend(unbroken_runs(lines))
    if WRAPPED_BASE64_LINE_PATTERN.search(text) or URLSAFE_BASE64_LINE_PATTERN.search(text):
        runs.extend(wrapped_base64_runs(lines))
    offset_runs = [(offset, "hex byte pairs", length) for offset, length in hex_pair_runs(text)]
    offset_runs.extend(
        (match.start(), "escaped bytes", match.end() - match.start())
        for match in ESCAPED_BYTE_RUN_PATTERN.finditer(text)
    )
    if offset_runs:
        line_ends = list(itertools.accumulate(map(len, text.splitlines(keepends=True))))
        runs.extend(
            (bisect.bisect_right(line_ends, offset) + 1, kind, length)
            for offset, kind, length in offset_runs
        )
    pair_lines = {line_number for line_number, kind, _ in runs if kind == "hex byte pairs"}
    runs.extend(
        (line_number, "hex dump", length)
        for line_number, length in hex_dump_runs(lines)
        if line_number not in pair_lines
    )
    runs.sort(key=lambda run: run[0])
    return [
        Finding(
            f"{location}:{line_number}",
            f"contains a long encoded run ({kind}, {length} characters)",
        )
        for line_number, kind, length in runs
    ]


def check_blob(
    blob: Blob, references: PrivateReferences | None, check_wording: bool = True
) -> list[Finding]:
    """Findings for one file version; `check_wording` is false in history mode.

    Banned wording and figure runs are about what this repository publishes now, and history
    is never rewritten, so a past path or line cannot be brought into line with either rule.
    """
    findings: list[Finding] = []
    location = blob.location
    if references is not None:
        withheld_location = f"blob {blob.object_id[:12]} (path withheld)"
        findings.extend(path_findings(withheld_location, blob.path, references))
        if findings:
            location = withheld_location
    blob_path = PurePosixPath(blob.path)
    if PRIVATE_FOLDER_NAME in (normalize_text(part) for part in blob_path.parts):
        findings.append(Finding(location, "is inside the private folder"))
    if normalize_text(blob_path.name).endswith(".fm"):
        findings.append(Finding(location, "is a save file (*.fm)"))
    if blob.mode == SYMBOLIC_LINK_MODE:
        findings.append(Finding(location, "is a symbolic link"))
    if blob.mode == SUBMODULE_MODE:
        findings.append(Finding(location, "is a submodule"))
        return findings
    is_oversized = len(blob.content) > MAX_FILE_BYTES
    if is_oversized:
        findings.append(Finding(location, f"is larger than {MAX_FILE_BYTES} bytes"))
    if SAVE_MAGIC in blob.content:
        findings.append(Finding(location, "contains save file magic bytes"))
    text = decode_text(blob.content)
    if text is None:
        findings.append(Finding(location, "is binary (NUL byte or invalid UTF-8)"))
        return findings
    if normalize_text(blob_path.suffix) == ".ipynb" and notebook_has_outputs(text):
        findings.append(Finding(location, "is a notebook with outputs"))
    if not is_oversized:
        findings.extend(encoded_run_findings(location, text))
        if check_wording:
            findings.extend(banned_wording_findings(location, blob.path, text))
            findings.extend(figure_run_findings(location, blob.path, text))
    if references is not None:
        findings.extend(overlap_findings(location, text, references))
        findings.extend(text_findings(location, text, references))
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


def index_entries(repository_root: Path) -> dict[str, tuple[str, str]]:
    """Mode and object id of every index entry, by path."""
    entries: dict[str, tuple[str, str]] = {}
    for entry in split_null_terminated(run_git(repository_root, ["ls-files", "--stage", "-z"])):
        metadata, _, path = entry.partition("\t")
        mode, object_id, stage_number = metadata.split(" ")
        if stage_number != "0":
            raise SystemExit("guard: the index has unmerged entries; resolve them first")
        entries[path] = (mode, object_id)
    return entries


def index_blob(repository_root: Path, path: str, mode: str, object_id: str) -> Blob:
    """Read an index entry; a submodule entry names a commit in another repository, so no read."""
    if mode == SUBMODULE_MODE:
        return Blob(path, path, object_id, mode, b"")
    content = run_git(repository_root, ["cat-file", "blob", object_id])
    return Blob(path, path, object_id, mode, content)


def staged_blobs(repository_root: Path) -> Iterator[Blob]:
    listing = run_git(repository_root, ["diff", "--cached", "--name-only", "-z", "--diff-filter=d"])
    entries = index_entries(repository_root)
    for path in split_null_terminated(listing):
        mode, object_id = entries[path]
        yield index_blob(repository_root, path, mode, object_id)


def tracked_blobs(repository_root: Path) -> Iterator[Blob]:
    for path, (mode, object_id) in index_entries(repository_root).items():
        yield index_blob(repository_root, path, mode, object_id)


def add_object_path(object_paths: dict[str, list[str]], object_id: str, path: str) -> None:
    paths = object_paths.setdefault(object_id, [])
    if path not in paths:
        paths.append(path)


def add_blob_mode(
    blob_modes: dict[str, dict[str, str]], object_id: str, path: str, mode: str
) -> None:
    """Keep one mode per (blob, path): the first one listed, unless a symbolic link mode follows."""
    path_modes = blob_modes.setdefault(object_id, {})
    if path not in path_modes or mode == SYMBOLIC_LINK_MODE:
        path_modes[path] = mode


def history_blobs(repository_root: Path) -> Iterator[Blob]:
    """One entry per (blob, path) reachable from any ref; each blob is read once.

    Entries come from the root tree of every commit and every tagged tree, which carry the
    modes. When a path holds the same blob under several modes, a symbolic link mode wins.
    A blob path that `rev-list --objects` names but no tree listing covers is still checked,
    with an empty mode, and a blob that a tag points at directly is checked as a tagged blob.
    Submodule entries are reported without reading the commit they name.
    """
    object_paths: dict[str, list[str]] = {}
    unnamed_ids: list[str] = []
    listing = run_git(repository_root, ["rev-list", "--objects", "--all"]).decode(
        "utf-8", "surrogateescape"
    )
    for line in listing.splitlines():
        object_id, _, path = line.partition(" ")
        if path:
            add_object_path(object_paths, object_id, path)
        else:
            unnamed_ids.append(object_id)
    batch_names = [
        *object_paths,
        *unnamed_ids,
        *(f"{object_id}^{{tree}}" for object_id in unnamed_ids),
    ]
    if not batch_names:
        return
    batch_input = ("\n".join(batch_names) + "\n").encode("ascii")
    type_lines = (
        run_git(
            repository_root, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], batch_input
        )
        .decode("ascii")
        .splitlines()
    )
    named_count = len(object_paths)
    unnamed_end = named_count + len(unnamed_ids)
    named_blob_ids: list[str] = []
    tagged_blob_ids: dict[str, None] = {}
    root_tree_ids: dict[str, None] = {}
    for line_index, type_line in enumerate(type_lines):
        object_id, _, object_type = type_line.partition(" ")
        if line_index < named_count:
            if object_type == "blob":
                named_blob_ids.append(object_id)
        elif line_index < unnamed_end:
            if object_type == "blob":
                tagged_blob_ids[object_id] = None
        elif object_type == "tree":
            root_tree_ids[object_id] = None
    blob_modes: dict[str, dict[str, str]] = {}
    submodule_entries: dict[tuple[str, str], None] = {}
    for tree_id in root_tree_ids:
        tree_listing = run_git(repository_root, ["ls-tree", "-r", "-z", "--full-tree", tree_id])
        for entry in split_null_terminated(tree_listing):
            metadata, _, path = entry.partition("\t")
            mode, object_type, object_id = metadata.split(" ")
            if object_type == "blob":
                add_blob_mode(blob_modes, object_id, path, mode)
            elif mode == SUBMODULE_MODE:
                submodule_entries[(object_id, path)] = None
    for object_id in named_blob_ids:
        path_modes = blob_modes.setdefault(object_id, {})
        for path in object_paths[object_id]:
            path_modes.setdefault(path, "")
    for object_id, path_modes in blob_modes.items():
        content = run_git(repository_root, ["cat-file", "blob", object_id])
        for path, mode in path_modes.items():
            yield Blob(path, f"{path}@{object_id[:12]}", object_id, mode, content)
    for object_id, path in submodule_entries:
        yield Blob(path, f"{path}@{object_id[:12]}", object_id, SUBMODULE_MODE, b"")
    for object_id in tagged_blob_ids:
        if object_id not in blob_modes:
            content = run_git(repository_root, ["cat-file", "blob", object_id])
            yield Blob("", f"tagged blob {object_id[:12]}", object_id, "", content)


def message_findings(
    location: str, message: str, references: PrivateReferences | None
) -> list[Finding]:
    """Findings for one message: encoded runs always, private text when references exist."""
    findings = encoded_run_findings(location, message)
    if references is not None:
        findings.extend(text_findings(location, message, references))
    return findings


def history_message_findings(
    repository_root: Path, references: PrivateReferences | None
) -> list[Finding]:
    """Findings for every commit message and annotated tag message in history."""
    findings: list[Finding] = []
    raw_log = run_git(repository_root, ["log", "--all", "--format=%H%x00%B%x1e"]).decode(
        "utf-8", "replace"
    )
    for record in raw_log.split("\x1e"):
        commit_id, _, message = record.strip("\n").partition("\x00")
        if commit_id:
            location = f"commit {commit_id[:12]} message"
            findings.extend(message_findings(location, message, references))
    raw_tags = run_git(
        repository_root,
        ["for-each-ref", "--format=%(objecttype)%00%(objectname)%00%(contents)%1e", "refs/tags"],
    ).decode("utf-8", "replace")
    for record in raw_tags.split("\x1e"):
        object_type, _, remainder = record.strip("\n").partition("\x00")
        tag_id, _, message = remainder.partition("\x00")
        if object_type == "tag":
            findings.extend(message_findings(f"tag {tag_id[:12]} message", message, references))
    return findings


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Block private or save-derived content.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check files staged for commit")
    mode.add_argument("--tracked", action="store_true", help="check every tracked file")
    mode.add_argument(
        "--history", action="store_true", help="check every blob, path and message in history"
    )
    mode.add_argument(
        "--commit-msg", metavar="PATH", help="check a commit message or other text file"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root, also holding the private folder (default: git top level, "
        "with the private folder of the main worktree)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    root_argument: Path | None = arguments.root
    if root_argument is not None:
        repository_root = root_argument
        private_root = root_argument
    else:
        repository_root = Path(
            run_git(Path.cwd(), ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
        )
        common_directory = run_git(
            Path.cwd(), ["rev-parse", "--path-format=absolute", "--git-common-dir"]
        )
        private_root = Path(common_directory.decode("utf-8").strip()).parent
    references = load_private_references(private_root)
    findings: list[Finding] = []
    message_path: str | None = arguments.commit_msg
    if message_path is not None:
        message_text = Path(message_path).read_text(encoding="utf-8", errors="replace")
        findings.extend(message_findings("message", message_text, references))
        findings.extend(
            Finding(f"message:{line_number}", f"uses banned internal wording ({wording})")
            for line_number, wording in banned_wording(message_text.splitlines())
        )
    else:
        if arguments.staged:
            blobs = staged_blobs(repository_root)
        elif arguments.tracked:
            blobs = tracked_blobs(repository_root)
        else:
            blobs = history_blobs(repository_root)
        for blob in blobs:
            findings.extend(check_blob(blob, references, check_wording=not arguments.history))
        if arguments.history:
            findings.extend(history_message_findings(repository_root, references))
    for finding in findings:
        print(f"guard: {finding.location}: {finding.reason}", file=sys.stderr)
    if findings:
        print(f"guard: {len(findings)} problem(s) found; blocked", file=sys.stderr)
        return 1
    if references:
        print("guard: ok (structural checks and private references)", file=sys.stderr)
    else:
        # Say plainly what did not run. Without the private folder the copied-text and
        # denylist checks are skipped, and a bare "ok" reads like a full pass.
        print(
            "guard: ok (structural checks only -- private-folder checks did NOT run)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
