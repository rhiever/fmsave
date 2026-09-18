# fmsave

Read your Football Manager 26 saves from disk into Python records, DataFrames, CSV and JSON.

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

    squad_frame = squad.to_pandas()  # needs fmsave[pandas]
    squad.write_csv("squad.csv")
```

A player carries his names, birth date and age, nationality, club, height, positions, all 24
attributes, the eight personality attributes, current and potential ability, reputation, transfer
value, condition, traits, his contract and any unserved ban. Records and tables are immutable and
keep working after the save is closed.

Each reader returns a `Table`: `where(...)`, `filter(...)`, `sorted_by(...)`, `find(name=...)`,
`by_uid(...)`, `by_id(...)` and `coverage`, plus `to_dicts()`, `to_columns()`, `to_pandas()`,
`to_polars()`, `write_csv(...)`, `write_json(...)` and `write_jsonl(...)`.

## What else it reads

Twenty-six readers in all, each returning a `Table` of records:

- **People** — `players()`, `contracts()`, `suspensions()`, `staff()`, `staff_lists()`
- **Clubs** — `clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`,
  `stadiums()`, `affiliates()`, `job_vacancies()`
- **Competitions** — `stages()`, `competitions()`, `fixtures()`, `league_tables()`,
  `competition_rules()`, `transfer_windows()`, `player_match_stats()`
- **Injuries** — `injury_types()`, `injury_history()`
- **Your own club's work**, which only the club you manage stores — `training()`, `mentoring()`,
  `tactics()`, `set_pieces()`

Every field is either verified against the game or unconfirmed; ask with
`fmsave.field_status(fmsave.Player, "contract.wage")`. Values come from the save as stored, a value
fmsave cannot read is `None` rather than a guess, and money is kept in the unit the game stores it
in, which is not the currency it displays.

Each reader also measures what it decoded against loose bounds drawn from a couple of careers. A
save unlike them can miss one and still be read perfectly well, so a missed bound is a warning and
you get the table anyway. Pass `strict=True` to `fmsave.open` to have one raise instead.

## What it cannot read

- **Names the game renders from its own installed database.** Competitions, leagues, nations,
  cities and all but a couple of hundred grounds. fmsave ships none of these and reads nothing from
  your game install. Competitions carry `database_id`, the id every outside name source is keyed
  on, so you can supply your own map — see [Competition names](#competition-names).
- **Links the save does not store**, such as which competition a rules block belongs to, or which
  ground a club plays at. Worked out from the fixture calendar where possible, left empty where not.
- **Meanings for numbers the game never displayed**, such as staff job titles or the settings
  inside a tactic. These come back as raw numbers rather than as labels fmsave guessed at.
- **What the save keeps only in part or not at all** — scores for about three quarters of a
  career's matches, injuries older than about two years, and today's availability, line-ups, staff
  attribute values, card counts, club debt and asking prices.

## Competition names

```python
competition_names = fmsave.read_competition_names("competition-names.csv")
with fmsave.open("career.fm", competition_names=competition_names) as career_save:
    for competition in career_save.competitions():
        print(competition.database_id, competition.name)  # 12345 "Example League"
```

The file is UTF-8, two columns, `database_id` then `name`; a leading header row is skipped. Any
mapping of database id to name works too. Without a map, `name` and every denormalised
`competition_name` is `None`. About one competition in ten carries no database id and can never be
named, and one the game created during a career carries an id no outside source holds.

## Command line

```console
fmsave info career.fm
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm players --nation 7 --columns name,age,club_name,contract_wage
fmsave validate career.fm --json
```

`export` writes any of the twenty-six tables as CSV, JSON or JSON Lines, and needs a scope:
`--club`, `--managed-club`, `--competition`, `--nation` or `--all`. Nested groups flatten to
`contract_wage`-style columns and a coded value gives a label column plus a `_code` column, so JSON
is the lossless format. `validate` runs every reader and reports its checks, counts and coverage,
holding no names, uids or text from the save, so it is safe to paste into an issue.

## Where saves live

- macOS: `~/Library/Application Support/Sports Interactive/Football Manager 26/games/`
- Windows: usually `Documents\Sports Interactive\Football Manager 26\games\`
- Steam Cloud and other stores may keep saves somewhere else.

If the game is running, copy the save and read the copy.

## Safety

fmsave is read-only. It never modifies saves, makes no network connections, and does not read game
memory. Using it to gain an advantage in shared online careers may break platform or community
rules.

## Support

fmsave is a hobby project, maintained on a best-effort basis. Report problems through
[GitHub issues](https://github.com/rhiever/fmsave/issues), and never attach save files. See
[CONTRIBUTING.md](CONTRIBUTING.md) for how to report a wrong value without sharing real data. To
request removal of any content, open an issue with the rights request form.

## Disclaimer

fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored by Sports
Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks or registered
trademarks of their respective owners.

## License

MIT. See [LICENSE](LICENSE).
