"""Shared export-test assertions: comparing fmsave's flat output against pandas.

Used by any test module that needs to check a record type's flattening matches
`pandas.json_normalize(record_to_dict(record, json_ready=True), sep="_")`, so the
comparison logic (and its NaN/NA/bool normalization) lives in one place.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy
import pandas

from fmsave.export import column_names, flatten_dict, record_to_dict


def normalized_cell(cell: object) -> object:
    """A DataFrame cell or a plain flat-column value, normalized so both compare equal.

    Booleans are tagged (pandas may store True/False as numpy.bool_), NaN/NA/NaT become
    None, and lists and tuples are compared item by item.
    """
    if isinstance(cell, (bool, numpy.bool_)):
        return ("bool", bool(cell))
    if isinstance(cell, (list, tuple)):
        return [normalized_cell(item) for item in cell]
    if cell is None:
        return None
    if isinstance(cell, float) and math.isnan(cell):
        return None
    if cell is pandas.NA or cell is pandas.NaT:
        return None
    return cell


def assert_matches_json_normalize(records: Sequence[object], record_type: type) -> None:
    """Assert every record's flat columns equal pandas.json_normalize's, cell by cell."""
    nested_rows = [record_to_dict(record, json_ready=True) for record in records]
    frame = pandas.json_normalize(nested_rows, sep="_")
    expected_columns = column_names(record_type)
    # json_normalize lists top-level values before flattened groups, so compare names only.
    assert len(frame.columns) == len(expected_columns)
    assert set(frame.columns) == set(expected_columns)
    for row_index, nested_row in enumerate(nested_rows):
        expected_row = flatten_dict(nested_row)
        for column_name in expected_columns:
            assert normalized_cell(frame.at[row_index, column_name]) == normalized_cell(
                expected_row[column_name]
            ), column_name
