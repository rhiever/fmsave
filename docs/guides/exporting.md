# Getting data out

Every reader returns a `Table`, and every `Table` offers the same four ways out. Pick the one that
suits where the data is going.

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
so on. Two of the four forms keep that shape and two flatten it.

- Nested: `to_dicts()`, `write_json()`, `write_jsonl()`.
- Flat: `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv()`.

The flattening rules are short:

- A nested group becomes `<field>_<subfield>`: `ability_current`, `contract_wage`,
  `attributes_finishing`. These are the names `pandas.json_normalize(sep="_")` would give.
- A coded value becomes two columns: a label column and a `<field>_code` column holding the raw
  number, so `contract_squad_status` and `contract_squad_status_code`.
- A tuple stays one value: a JSON array in JSON, a `;`-joined string in CSV, or compact JSON text
  in CSV when its items are groups.

A player flattens to 217 columns. To see the names for any record type without opening a save:

```python
import fmsave.export

fmsave.export.column_names(fmsave.Player)  # ("uid", "name", "first_name", ...)
```

Nested JSON carries the label **and** the code, so **JSON is the lossless format**. Reach for it
when you are handing the data to another program. CSV is for reading and for spreadsheets.

`to_dicts(json_ready=True)` gives the same nesting write_json uses: dates as ISO strings, tuples
as lists, everything JSON-serialisable.

## From the command line

`fmsave export` does the same work without Python, and needs a table and a scope.

```console
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm players --managed-club --columns name,age,ability_current,contract_wage
fmsave export career.fm players --all --format json -o players.json
fmsave export career.fm fixtures --managed-club --format jsonl -o fixtures.jsonl
```

The scope is required, and exactly one of:

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

Table names on the command line use hyphens where the Python method uses underscores:
`managed-clubs`, `league-tables`, `player-match-stats`, `set-pieces`.

Four tables (`training`, `mentoring`, `tactics` and `set-pieces`) only exist for the club you
manage. Any other scope returns no rows.
