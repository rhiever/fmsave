---
myst:
  html_meta:
    description: "fmsave reads Football Manager 26 and 27 saves into Python records, DataFrames, CSV, and JSON. It is read-only, and a free web app reads saves in the browser."
---

# fmsave

Read your Football Manager 26 and 27 saves from disk into Python records, DataFrames, CSV, and JSON.
fmsave is read-only: it never modifies a save, makes no network connections, and does not read
game memory.

No Python? [Open fmsave in your browser](https://rhiever.github.io/fmsave/app/) and drop a save on
the page. You get your squad and every player in the save, with all attributes, CA and PA, this
season's stats, and CSV downloads. The save is read on your computer and never uploaded.

## Install

fmsave needs Python 3.12 or newer.

```console
uvx fmsave info path/to/career.fm   # try it without installing
pip install fmsave
pip install "fmsave[pandas]"        # adds Table.to_pandas()
```

## Quickstart

```python
import fmsave

with fmsave.open("career.fm") as career_save:
    my_club = career_save.managed_clubs()[0]  # empty when you are between jobs
    squad = career_save.players().where(club_uid=my_club.club_uid)

    for player in squad.sorted_by(lambda player: player.ability.current, reverse=True)[:5]:
        print(player.name, player.age, player.ability.current, player.attributes.finishing)
        # "Alex Example" 24 148 16

    squad.write_csv("squad.csv")
```

Or the same thing without writing any Python:

```console
fmsave export career.fm players --managed-club -o squad.csv
```

## Where saves live

- macOS: `~/Library/Application Support/Sports Interactive/Football Manager 26/games/`
- Windows: usually `Documents\Sports Interactive\Football Manager 26\games\`
- Steam Cloud and other stores may keep saves somewhere else.

If the game is running, copy the save and read the copy.

## Start here

- [Your squad](guides/squad.md): from a save file to a sorted squad with attributes, contracts
  and filters. Read this one first.
- [Getting data out](guides/exporting.md): DataFrames, CSV, JSON, and the `fmsave export`
  command.
- [What a save holds](guides/what-a-save-holds.md): the 29 readers and their coverage limits.
- [Trusting a number](guides/trust.md): how to tell a verified field from an unconfirmed one,
  and what a reader's checks mean.

The reference section documents every record, field and command.
[Release notes](changelog.md) cover features and fixes by version.

```{toctree}
:maxdepth: 2
:caption: Guides

guides/squad
guides/exporting
guides/what-a-save-holds
guides/trust
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/save
reference/records
reference/enums
reference/table
reference/errors
reference/cli
```

```{toctree}
:maxdepth: 1
:caption: Releases

changelog
```
