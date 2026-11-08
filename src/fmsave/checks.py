"""The reader checks a save reports, and the validation report built from them.

Readers compare what they decode against bounds registered for the save's layout. Advisory
checks warn and return the table. Blocking checks raise `GateCheckError` on FM27 and in strict
mode. FM26 warns by default. A `GateCheckError` carries the reader checks so callers can
inspect gate names, observed values, and bounds.


`validate_save` runs every reader and returns a `ValidationReport`, which holds only structural
facts, counts and rates: never names, uids or other values from the save.

This module is the public face of the checks. How they are evaluated, which readers share a
decode and what each check measures are fmsave's to change, and live in `fmsave._checks`.
"""

from __future__ import annotations

from fmsave._checks import (
    GateCheckError,
    GateResult,
    ReaderCheck,
    ReaderStatus,
    ReaderValidation,
    ValidationReport,
    validate_save,
)

__all__ = [
    "GateCheckError",
    "GateResult",
    "ReaderCheck",
    "ReaderStatus",
    "ReaderValidation",
    "ValidationReport",
    "validate_save",
]
