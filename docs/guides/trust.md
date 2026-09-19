# Trusting a number

fmsave reads a binary file that nobody documented. Most of it is settled; some of it is not. This
page is how you tell which is which before you build anything on a number.

## Verified or unconfirmed

Every field carries one of two statuses. **Verified** means the value was checked against what the
game itself shows. **Unconfirmed** means it decodes consistently and looks right, but no screen
has confirmed what it means.

```python
import fmsave

fmsave.field_status(fmsave.Player, "attributes.finishing")  # "verified"
fmsave.field_status(fmsave.Player, "contract.wage")  # "unconfirmed"
```

Dots reach into groups. A field with no registered status raises `KeyError` rather than guessing.

Unconfirmed is not a warning to stay away. It is a statement about evidence, and most unconfirmed
fields are fine. It does tell you where to look first when a number surprises you.

## How much of a column is there at all

`coverage` gives the share of records whose value is not `None`, per flat column.

```python
with fmsave.open("career.fm") as career_save:
    squad = career_save.players().where(club_uid=career_save.managed_clubs()[0].club_uid)

squad.coverage["contract_wage"]  # 1.0
squad.coverage["loan_parent_club_name"]
```

A low number is usually the save, not a bug: see
[What a save holds](what-a-save-holds.md) for the things a save only keeps in part. A value fmsave
cannot read is `None`, never a guess.

## Reader checks warn, they do not block

Each of the twenty-six readers measures what it decoded against loose bounds drawn from a couple
of reference careers: how many records it found, how many names resolved, how the ratios sit. A
save unlike those careers can miss a bound and still be read perfectly well, so a missed bound is
a `ReaderCheckWarning` and you get the table anyway.

This is deliberate. Your save is not required to look like someone else's to be readable.

When you would rather not work with a table that missed a bound, ask for that:

```python
with fmsave.open("career.fm", strict=True) as career_save:
    squad = career_save.players()  # raises ReaderCheckError instead of warning
```

`strict=True` is worth it in a pipeline, where a silently odd table is worse than a stop. One
thing it does not change: a structural failure, where the decode produced no table at all, raises
`ReaderCheckError` either way.

## Ask the save how it did

`validate_save` runs every reader and reports. It neither raises nor warns.

```python
with fmsave.open("career.fm") as career_save:
    report = fmsave.validate_save(career_save)

for reader in report.readers:
    print(reader.reader, reader.status, reader.record_count)
    # "players" "ok" 124310
```

A reader's status is `ok`, `failed` (a check of its own did not pass) or `error` (it raised). Each
`ReaderValidation` also carries its `gates`, its `coverage` and its `anomalies` — counts of the
odd things it saw while decoding.

The same thing from the command line:

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

The report holds structural facts, counts and rates. **No names, no uids, no text from your
save.** That is what makes it the right thing to paste into a
[GitHub issue](https://github.com/rhiever/fmsave/issues) when a reader misbehaves. Never attach
the save file itself.

## Two things that are not errors

**Money is in the save's own unit.** Wages, values and balances come back exactly as stored, which
is not the currency the game displays and not a figure fmsave converts. A wage that looks wrong by
a factor is almost certainly this.

**A new game build warns.** `UnknownBuildWarning` means the save comes from an FM26 build fmsave
has no layout tables for. The readers still run, and their checks are what tell you whether the
layout moved under them.
