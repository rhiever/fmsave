# fmsave

Read your Football Manager 26 saves from disk into Python records, DataFrames, CSV and JSON.

## Install

fmsave needs Python 3.12 or newer.

```console
uvx fmsave info path/to/career.fm   # try it without installing
pip install fmsave
pip install "fmsave[pandas]"        # adds Table.to_pandas()
pip install "fmsave[polars]"        # adds Table.to_polars()
```

## Quickstart

```python
import fmsave

with fmsave.open("career.fm") as career_save:
    save_info = career_save.info  # game, build, database version and in-game date
    managed_clubs = career_save.managed_clubs()  # empty when the manager is between jobs
    if not managed_clubs:
        raise SystemExit("This save has no managed club")
    my_club = managed_clubs[0]  # your club, such as "Northbridge FC"
    squad_players = career_save.players().where(club_uid=my_club.club_uid)
    for squad_player in squad_players:
        contract = squad_player.contract  # None for a player without a contract
        wage = contract.wage if contract else None
        contract_end = contract.end if contract else None
        print(squad_player.name, squad_player.age, wage, contract_end)  # "Alex Example", 24, ...
    squad_frame = squad_players.to_pandas()  # needs fmsave[pandas]
```

Records and tables are immutable and keep working after the save is closed.

## What it reads

**People**

- `players()` — names, birth date and age, nationality, club, positions, attributes, personality, traits, reputation, transfer value, contract and unserved suspensions.
- `contracts()` — the contract in effect at the save's in-game date: wage, start and end, squad status, contract type, clauses and loan details. Never an agreed future move such as a pre-contract.
- `suspensions()` — every unserved ban with its player, club and date issued, including bans the game no longer displays. A ban covering one competition carries that competition's id, which joins the stage, fixture and league-table readers; a nation-wide ban carries a nation id instead, and each row says which it is.
- `staff()` — everyone a club employs who is not a player, with the department lists he is in, his contract, his ability and the preferences a staff profile shows. The human manager is a row of his own.
- `staff_lists()` — the three staff lists each club record holds. Only about a thousand clubs of a save list anybody.

**Clubs**

- `clubs()` — name, short name, nation and city ids, reputation, last league position and teams.
- `managed_clubs()` — the club the human manager runs; empty when he is between jobs.
- `finances()` — one row per club per month, oldest first: balance at the month's end, budgets, wages, income and expenditure. Only the clubs of the one or two league nations a save tracks keep a series, and which nations those are moves as a career goes on.
- `sponsorships()` — every sponsorship contract of those same clubs, contracts that have ended included.
- `facilities()` — each of those clubs' corporate facilities rating, as a word the game's own screen shows.
- `stadiums()` — every ground the save's database holds: capacities, pitch sizes, when it was built and rebuilt, the club that owns it, and the clubs that play there.
- `affiliates()` — groups of clubs the save stores together, in stored order.
- `job_vacancies()` — the job-centre feed, with the team, the competition and the date each job was advertised.

**Competitions**

- `stages()` — every stage of every competition, with the stage id that fixtures, tables and per-match records join through. A league season is one stage, a cup round is one, and each leg of a tie is its own.
- `competitions()` — every competition the stage table names, with its stages and, for about nine in ten, its id in the game's editor database.
- `fixtures()` — every match the save has scheduled or played, in date and kick-off order, with stage, competition, round, both teams and their clubs, the ground, and whether the match was played away from the home club's usual one. Goals are filled in from the separate records the save keeps scores in.
- `league_tables()` — every live table, one row per club, with its total record, its home, away and half-season splits, and one slot per match. Rows come back in the save's own standings order, so do not re-sort them: the game separates clubs level on points by their head-to-head record, which no field here carries.
- `competition_rules()` — every rules block: promotion, play-off and relegation places, tie-break codes, prize money by finishing position and the round calendar.
- `transfer_windows()` — every window the save's rules database holds, with the day and month each opens and closes. Windows are database content rather than career state, and repeat, so deduplicate if you want one row each.
- `player_match_stats()` — every match a player played that the save still holds a record of: date, competition, opponent, and for a match it still holds the statistics of, the position, minutes, goals, assists, rating, the minute he left and both pass counts. The save keeps about twenty matches per player per spell across all competitions at once, so this is never a whole season.

**Injuries**

- `injury_types()` — the injury names the save itself stores.
- `injury_history()` — every injury the save still remembers. A history row is one that happened, with the team, whether it was in training or in a match, and how bad it was; the save keeps about the last two years. A typed row carries the injury type of a recent or current episode, and its date is the day the player is expected back.

**Your own club's work** — only the club the manager runs stores these, and each row belongs to one of its teams.

- `training()` — one training calendar per team, with each week's start date and the schedule it runs.
- `mentoring()` — every mentoring group and its members.
- `tactics()` — each team's own copy of every tactic the manager has, with its name, style, mentality and position slots.
- `set_pieces()` — the twenty set-piece routine slots of each team, named where a routine fills one.

A club's `teams` are its own team slots followed by the teams it controls at other clubs, such as a B team the save stores as a club of its own. A player registered with one of those counts as a player of the controlling club, keeps the club storing his team in `team_club_uid`, and is not on loan; `on_loan` marks a real loan. How the save stores those links is read from the file and not checked against the game, so ask `field_status` before relying on them.

Each reader returns a `Table`, an immutable sequence of records with `where(...)`, `filter(...)`, `sorted_by(...)`, `find(name=...)`, `by_uid(...)`, `get_by_uid(...)`, `by_id(...)`, `get_by_id(...)` and `coverage`, plus `to_dicts()`, `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv(...)`, `write_json(...)` and `write_jsonl(...)`.

Every field is either verified (checked against the game) or unconfirmed; ask with `fmsave.field_status(fmsave.Player, "contract.wage")`. Every value comes from the save as stored, a value fmsave cannot read is `None` rather than a guess, and money is kept exactly as the game stores it, in a unit that is not the currency the game displays.

## What it cannot read

- **Names the game renders from its installed database rather than the save.** Competition, league and nation names; the name of all but a couple of hundred grounds; the name of some injury types, because a save's own injury-name table has no entry for a few of the codes its players' injuries carry; and the name of a city, so `clubs().city_id` stays a raw id. fmsave ships none of these names and reads nothing from your game install. For competitions you can supply your own map, as [Competition names](#competition-names) describes.
- **Links the save does not store.** Which competition a rules block or a transfer window belongs to, and which ground a club plays its home matches at. Where a link can be worked out from the fixture calendar it is, marked unconfirmed, and left empty where it cannot: a third of rules blocks carry no competition, and a ground no club used often enough lists none. A club's own affiliates are in no field fmsave reads — the groups `affiliates()` returns are not that list, and what the grouping means is not established.
- **Meanings for numbers the game never displayed beside them.** The job title of a staff member or of an advertised job; which tactic is selected; the positions, instructions and settings inside a tactic; which situation a set-piece routine is for; what a training schedule asks of a day; most staff preference slots; and most competition round codes. Each of these reads as a raw number, or as nothing, rather than as a label fmsave guessed at.
- **What the save keeps only in part.** The score of a played match: the calendar stores no score and the records that do are retained for about a quarter of a career's matches. Injuries older than about two years. A player's full-career injury history, which the save holds without saying whose it is, so it cannot be joined to anyone.
- **What is not stored in a readable way at all.** Today's injuries and availability, team selection and line-ups, staff attribute values, card counts, the scouting budget, club debt and asking prices.

## When a check fails

Every reader measures what it decoded — how many records, how many resolved a join, how many fell in range — against loose bounds. Those bounds come from a couple of careers, so a save unlike them can miss one and still be read perfectly well. A missed bound is a warning and you get the table anyway.

Pass `strict=True` to `fmsave.open` to have a missed bound raise `ReaderCheckError` instead, or `fmsave export --strict` on the command line. A decode that found nothing to hand back is a different thing and raises either way. `fmsave validate` lists every check without warning.

## Competition names

No save holds a competition name: the game renders them from its own installed database. What every competition row does carry is `database_id`, the competition's id in the game's editor database, which is the same value in every save and is what name sources outside a save are keyed on.

Supply your own map to fill the names in:

```python
import fmsave

competition_names = fmsave.read_competition_names("competition-names.csv")
with fmsave.open("career.fm", competition_names=competition_names) as career_save:
    for competition in career_save.competitions():
        print(competition.database_id, competition.name)  # 12345 "Example League"
```

`competition_names` also takes the path itself, or any mapping of database id to name. Tables are read once and then kept, so open the save again to read it under a different map. Without a map, `name` and every denormalised `competition_name` is `None`, and about one competition in ten has no database id and so can never be named. A competition the game created during a career does carry one, but no name source outside the save holds it, so a map built from such a source names fewer competitions than it has ids for.

The file is UTF-8 with two columns, `database_id` then `name`. A first row whose first cell is not a number is treated as a header and skipped, blank lines are skipped, and surrounding spaces are trimmed:

```
database_id,name
12345,Example League
12346,Example Cup
```

A row is exactly two columns wide and an id is plain digits; a third column is refused rather than guessed at, so put quotes around a name holding a comma. Building the map is up to you: competition name sources are keyed on the editor database id, so any mapping of that id to a name can be supplied here.

## Command line

```console
fmsave info career.fm
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm staff --club "Northbridge FC" --format json
fmsave export career.fm players --nation 7 --columns name,age,club_name,contract_wage,contract_end
fmsave validate career.fm --json
```

- `info` shows the game, build, database version and in-game date. It leaves out the save's name unless you pass `--show-name`. Add `--json` for JSON.
- `export` writes one table (`players`, `contracts`, `suspensions`, `clubs`, `managed-clubs`, `stages`, `competitions`, `fixtures`, `league-tables`, `transfer-windows`, `competition-rules`, `player-match-stats`, `stadiums`, `finances`, `sponsorships`, `facilities`, `affiliates`, `job-vacancies`, `staff`, `staff-lists`, `injury-types`, `injury-history`, `training`, `mentoring`, `tactics` or `set-pieces`) as CSV, JSON or JSON Lines (`--format csv|json|jsonl`), to standard output or to a file with `-o`. `--columns` picks and orders columns.
- `export` needs a scope: a club by name, short name or uid (`--club`), the club you manage (`--managed-club`), a competition by id (`--competition`), a nation id (`--nation`), or `--all`. A table takes only the scopes its rows can answer, and one it turns down names the scopes it does take.
- `--competition-names` names the competitions of one run, from the same file `fmsave.read_competition_names` reads. With it, `--competition` also takes a name.
- `validate` runs every reader and reports its checks, record counts and coverage. The report holds no names, uids or text from the save, so it is safe to paste into an issue.

Output notes: nested groups flatten to `<group>_<field>` columns such as `contract_wage`, and a missing group appears as all-null subfields. A coded value gives a label column plus a `_code` column. Dates are ISO 8601. In CSV, an empty list and a missing value both appear as an empty cell, lists of plain values are joined with `;`, and lists of groups such as `teams` or `clauses` are written as compact JSON, so JSON is the lossless format. fmsave does not escape cells that spreadsheet programs may read as formulas.

## Where saves live

- macOS: `~/Library/Application Support/Sports Interactive/Football Manager 26/games/`
- Windows: usually `Documents\Sports Interactive\Football Manager 26\games\`
- Steam Cloud and other stores may keep saves somewhere else.

If the game is running, copy the save and read the copy.

## Safety

fmsave is read-only. It never modifies saves, makes no network connections, and does not read game memory.

## Online careers

Using fmsave to gain an advantage in shared online careers may break platform or community rules.

## Support

fmsave is a hobby project, maintained on a best-effort basis. Report problems through [GitHub issues](https://github.com/rhiever/fmsave/issues), and never attach save files. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report a wrong value without sharing real data.

## Rights holders

To request removal of any content, open a [GitHub issue](https://github.com/rhiever/fmsave/issues/new/choose) with the rights request form.

## Disclaimer

fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored by Sports Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks or registered trademarks of their respective owners.

## License

MIT. See [LICENSE](LICENSE).
