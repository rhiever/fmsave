---
myst:
  html_meta:
    description: "Export fmsave tables from Football Manager 26 and 27 saves to pandas, polars, CSV, JSON, and JSON Lines, or use the fmsave export command."
---

# Getting data out

Every reader returns a `Table`. Export nested records for another program or flat columns for
a spreadsheet.

```python
import fmsave

with fmsave.open("career.fm") as career_save:
    squad = career_save.players().where(club_uid=career_save.managed_clubs()[0].club_uid)

rows = squad.to_dicts()  # nested dicts of Python values
columns = squad.to_columns()  # flat columns of Python values
frame = squad.to_pandas()  # needs fmsave[pandas]

squad.write_csv("squad.csv")  # flat columns
squad.write_json("squad.json")  # nested, one array
squad.write_jsonl("squad.jsonl")  # nested, one record per line
```

`to_polars()` is there too, and needs `fmsave[polars]`. Tables keep working after the save is
closed, so exporting outside the `with` block is fine.

## Nested or flat

A record is nested. A player carries an `ability` group, an `attributes` group, a `contract`, and
so on. Exports either keep that shape or flatten it.

- Nested: `to_dicts()`, `write_json()`, `write_jsonl()`.
- Flat: `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv()`.

The flattening rules are short:

- A nested group becomes `<field>_<subfield>`: `ability_current`, `contract_wage`,
  `attributes_finishing`. These are the names `pandas.json_normalize(sep="_")` would give.
- A coded value becomes 2 columns: a label column and a `<field>_code` column holding the raw
  number, so `contract_squad_status` and `contract_squad_status_code`.
- A tuple stays a single value: a JSON array in JSON, a `;`-joined string in CSV, or compact JSON text
  in CSV when its items are groups.

To see the column names for any record type without opening a save:

```python
import fmsave.export

fmsave.export.column_names(fmsave.Player)  # ("uid", "unique_id", "name", ...)
```

Nested JSON carries the label and raw code for coded values. Dates become ISO strings, and
tuples become arrays. CSV is convenient for spreadsheets; use JSON when nested structure matters.
CSV cells are written as they are, so a spreadsheet may run a text cell that starts with `=`, `+`,
`-` or `@` as a formula.

`to_dicts(json_ready=True)` gives the same nesting `write_json()` uses: dates as ISO strings, tuples
as lists, everything JSON-serialisable.

## From the command line

`fmsave export` does the same work without Python, and needs a table and a scope.

```console
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm players --managed-club --columns name,age,ability_current,contract_wage
fmsave export career.fm players --all --format json -o players.json
fmsave export career.fm fixtures --managed-club --format jsonl -o fixtures.jsonl
fmsave export career.fm player-season-stats --managed-club -o season.csv
```

Supply exactly 1 scope supported by the table:

- `--managed-club`: the club you run.
- `--club VALUE`: one club by uid, name or short name, in any case. A name that matches more than
  one club is an error that lists the matches, so you can pick the uid.
- `--competition VALUE`: one competition by id, or by name once `--competition-names` supplies
  one.
- `--nation VALUE`: one nation, by nation id.
- `--all`: every row.

The rest:

- `--format {csv,json,jsonl}`, default `csv`.
- `--columns NAMES`: flat column names, comma-separated, written in the order you give them.
- `-o PATH`: a file instead of standard output.
- `--competition-names PATH`: a UTF-8 CSV of `database_id,name`. See
  [What a save holds](what-a-save-holds.md).
- `--strict`: stop rather than write when a reader's checks fail. See
  [Trusting a number](trust.md).

Table names on the command line use `-` where the Python method uses `_`:
`managed-clubs`, `league-tables`, `player-match-stats`, `player-season-stats`, `set-pieces`.

Not every table accepts every scope. An unsupported scope returns an error listing the accepted
alternatives. For example, `transfer-windows` and `injury-types` require `--all`; `competition-rules` accepts
`--competition` or `--all`.

For `player-season-stats`, a club or nation scope selects current players and includes their
rows for other teams this season. It does not select a single named competition. To export
league rows for your club in Python:

```python
with fmsave.open("career.fm") as career_save:
    league = career_save.player_season_stats().where(
        club_uid=career_save.managed_clubs()[0].club_uid,
        kind=fmsave.SeasonStatsKind.LEAGUE,
    )
league.write_csv("league.csv")
```

Keep counts such as `minutes` alongside rates such as `expected_goals_per_90` and
`pass_completion_percent`. Rates are included automatically and become `None` when the
count does not apply or the denominator is zero.

`training`, `mentoring`, `tactics` and `set-pieces` return data for the club you manage.
Selecting another club returns no rows.

Archived player statistics are available through `player_season_history()` and the
`player-season-history` CLI table:

```console
fmsave export career.fm player-season-history --all --format csv -o history.csv
```

Each row has the counts and computed rates of `PlayerSeasonStats`, plus `season_year` and
`competition_reference`. Both metadata fields are unconfirmed: the year does not yet have a
confirmed season-start or season-end meaning, and the competition reference has no confirmed
mapping to competition entities or database IDs. Rows keep their stored order, which may be
nonchronological. Sort explicitly if your analysis requires an order.

The archive can contain sparse imported history. Detailed counts may be 0 even when
appearances are present; a stored 0 does not prove an event never happened. Goalkeeper
fields use the player's current natural positions because the archive does not identify their
past role. Team and club fields refer to the archived team. Unresolved teams keep their raw
team reference and have empty club fields. Club and nation CLI scopes select players by their
current membership, then export those players' historical rows, including their previous teams.

A valid empty history returns an empty table. A missing or malformed archive or history index
raises `ReaderCheckError`. Large histories can require substantial memory because the table
keeps every decoded row.
