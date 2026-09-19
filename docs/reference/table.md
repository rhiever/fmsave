# Table

The immutable sequence every reader returns: one dataclass type per table, with lookups,
queries and export to pandas, polars, CSV, JSON and JSON Lines.

```{eval-rst}
.. autoclass:: fmsave.Table
   :members: record_type, index, count, where, filter, sorted_by, find, by_uid, get_by_uid,
       by_id, get_by_id, coverage, to_columns, to_dicts, to_pandas, to_polars, write_csv,
       write_json, write_jsonl
```
