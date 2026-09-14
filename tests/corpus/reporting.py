"""Failure reporting for corpus tests that never puts values read from a save in the output."""

from __future__ import annotations

import pytest


class CorpusMismatches:
    """Collects corpus mismatches as short messages, then fails once with all of them.

    Callers compare values themselves and pass only the result, a file-name label and a
    field name, so a failure never shows what a save or its golden values contain.
    """

    def __init__(self) -> None:
        self._messages: list[str] = []

    def check(self, label: str, field_name: str, matched: bool) -> None:
        """Record that `field_name` differs for `label` when `matched` is false."""
        if not matched:
            self._messages.append(f"{label}: {field_name} differs")

    def note(self, message: str) -> None:
        """Record a message built only from labels, field names and test-chosen counts."""
        self._messages.append(message)

    def fail_if_any(self) -> None:
        """Fail the test, without a traceback, when anything was recorded."""
        if self._messages:
            pytest.fail("; ".join(self._messages), pytrace=False)
