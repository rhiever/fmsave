# Trusting a number

Check a field's status, coverage and reader checks before relying on it. These answer different
questions: what a value means, how often it is present, and whether the reader passed its checks.

## Verified or unconfirmed

Verified means the value was checked against what the game shows. Unconfirmed means its
meaning has not been confirmed on a game screen.

```python
import fmsave

fmsave.field_status(fmsave.Player, "attributes.finishing")  # "verified"
fmsave.field_status(fmsave.Player, "contract.wage")  # "unconfirmed"
```

Dots reach into groups. A field with no registered status raises `KeyError`.
An unconfirmed field needs independent evidence before you treat its meaning as established.

## Coverage measures presence

`coverage` gives the share of records whose value is not `None`, per flat column.

```python
with fmsave.open("career.fm") as career_save:
    squad = career_save.players().where(club_uid=career_save.managed_clubs()[0].club_uid)

squad.coverage["contract_wage"]
squad.coverage["loan_parent_club_name"]
```

Missing values can mean the save omitted data, a join could not resolve, or fmsave could not decode
it. Coverage alone cannot distinguish these. See [What a save holds](what-a-save-holds.md).
A missing match score does not mean a 0-0 result.

## Reader checks

Checks test completeness, joins and expected ranges. A failed check produces a
`ReaderCheckWarning` and returns the table. Some range checks may fail on a valid save unlike the
reference careers; investigate the failed check before using its output.

Use strict mode when your pipeline should stop on a failed check:

```python
with fmsave.open("career.fm", strict=True) as career_save:
    squad = career_save.players()  # raises ReaderCheckError on a failed check
```

A structural failure that prevents a table from being decoded raises `ReaderCheckError` in either
mode. Empty output can be valid: `player_match_stats()` accepts it when every player explicitly
has no stored history. Missing or incomplete histories still fail checks.

## Validation reports

`validate_save` runs every reader and collects its outcome without emitting reader warnings or
raising reader errors.

```python
with fmsave.open("career.fm") as career_save:
    report = fmsave.validate_save(career_save)

for reader in report.readers:
    print(reader.reader, reader.status, reader.record_count)
    # "players" "ok" 124310
```

A reader's status is `ok`, `failed` (a check did not pass) or `error` (it raised).
Each `ReaderValidation` also carries `gates`, `coverage` and `anomalies`.
Passing checks is useful evidence, but does not confirm every field's meaning or guarantee full
historical coverage.

The same report is available from the command line:

```console
fmsave validate career.fm
fmsave validate career.fm --json
```

```text
players: ok (124310 records)
injuries: failed (630 records)
  injury_log_dates = 0.71 expected 0.9..1
game FM26, build 26.1.0+1234567
```

The report contains checks, counts and rates, without names, uids or text from your save. Paste it
into a [GitHub issue](https://github.com/rhiever/fmsave/issues) when a reader misbehaves. Do not
attach or link the save itself. To share it, email a link to the address on
[the maintainer's GitHub profile](https://github.com/rhiever).

## Money and game builds

Money uses the save's stored unit. Wages, values and balances are not converted to the currency
the game displays. Check that unit before interpreting a difference.

`UnknownBuildWarning` means fmsave does not recognize that FM26 build. Readers still run; inspect
their checks before relying on the output.
