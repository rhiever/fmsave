---
myst:
  html_meta:
    description: "Reference for fmsave's Table: lookups, queries, and export to pandas, polars, CSV, JSON, and JSON Lines."
---

# Table

The immutable sequence every reader returns: one dataclass type per table, with lookups,
queries and export to pandas, polars, CSV, JSON and JSON Lines.

```{eval-rst}
.. autoclass:: fmsave.Table
   :members: record_type, index, count, where, filter, sorted_by, find, by_uid, get_by_uid,
       by_id, get_by_id, coverage, to_columns, to_dicts, to_pandas, to_polars, write_csv,
       write_json, write_jsonl
```

## Scouting

See the [scouting guide](../guides/scouting.md) for model inputs and export examples.

```{eval-rst}
.. autodata:: fmsave.SCOUTING_POSITIONS
.. autofunction:: fmsave.scout_players
.. autofunction:: fmsave.scouting_score
```
