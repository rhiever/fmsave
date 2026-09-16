# fmsave

Read your Football Manager 26 saves from disk into Python records, DataFrames, CSV and JSON.

## Try it

```console
uvx fmsave info path/to/career.fm
```

## Install

fmsave needs Python 3.12 or newer.

```console
pip install fmsave
pip install "fmsave[pandas]"   # adds Table.to_pandas()
pip install "fmsave[polars]"   # adds Table.to_polars()
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

## What you can read in 0.1

- **Save info** (`career_save.info`): game, build, database version and in-game date.
- **Players** (`players()`): names, birth date and age, nationality, club, positions, attributes, personality, traits, reputation, transfer value, contract and unserved suspensions.
- **Contracts** (`contracts()`): wage, start and end dates, squad status, contract type, clauses and loan details for every player with a contract. Each row is the contract in effect at the save's in-game date, never an agreed future move such as a pre-contract or a transfer that takes effect later. Squad status is the role agreed in the contract, not a forecast of how much the player plays.
- **Suspensions** (`suspensions()`): each unserved suspension with its player, club, competition id and date issued, including bans the game no longer displays.
- **Clubs** (`clubs()`): name, short name, nation id, reputation, last league position and teams.
- **Managed clubs** (`managed_clubs()`): the club the human manager runs. The list is empty when the manager is between jobs.
- **Stages** (`stages()`): every stage of every competition, with the stage id that fixtures, league tables and per-match records join through, plus the competition id, group and round. A league season is one stage, a cup round is one, and each leg of a two-legged tie is its own stage.
- **Competitions** (`competitions()`): every competition the stage table names, with the ids of its stages and, for about nine competitions in ten, the competition's id in the game's own editor database. The save stores no competition names, so every row's `name` is empty until you supply a name map; see [Competition names](#competition-names). Stages and competitions are read in Python; `export` writes the five tables above.

A club's `teams` are its own team slots, in stored order, followed by the teams it controls at other clubs, such as a B team the save stores as a club of its own. A player registered with one of those teams counts as a player of the controlling club, keeps the club storing his team in `team_club_uid`, and is not on loan; `on_loan` marks a real loan, with the club of the contract in effect as the parent club and the loan's own dates in `loan_start` and `loan_end`. How the save stores those links is read from the file and not checked against the game: `team_club_uid`, `parent_club_uid` and a team's `club_uid` and `affiliate` mark are all unconfirmed, so ask `field_status` before relying on them.

Each reader returns a `Table`, an immutable sequence of records with `where(...)`, `filter(...)`, `find(name=...)`, `by_uid(...)`, `get_by_uid(...)` and `coverage`, plus `to_dicts()`, `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv(...)`, `write_json(...)` and `write_jsonl(...)`.

Every field is either verified (checked against the game) or unconfirmed; ask with `fmsave.field_status(fmsave.Player, "contract.wage")`.

Every value comes from the save as stored. A value fmsave cannot read is `None`, never a guess. Wages and other money are kept exactly as the game stores them and are not converted.

## Competition names

No save holds a competition name: the game renders them from its own installed database. fmsave ships none, never reads your game install, and makes no network call. What every competition row does carry is `database_id`, the competition's id in the game's editor database, which is the same value in every save and is what name sources outside a save are keyed on.

Supply your own map to fill the names in:

```python
import fmsave

competition_names = fmsave.read_competition_names("competition-names.csv")
with fmsave.open("career.fm", competition_names=competition_names) as career_save:
    for competition in career_save.competitions():
        print(competition.database_id, competition.name)  # 12345 "Example League"
```

`competition_names` also takes the path itself, or any mapping of database id to name. Tables are read once and then kept, so the map cannot be changed after opening: open the save again to read it under a different one. Without a map, `name` and every denormalised `competition_name` is `None`. A competition the save gives no database id can never be named, which is why about one competition in ten stays empty however complete your map is.

The file is UTF-8 with two columns, `database_id` then `name`. A first row whose first cell is not a number is treated as a header and skipped, blank lines are skipped, and surrounding spaces are trimmed:

```
database_id,name
12345,Example League
12346,Example Cup
```

A row is exactly two columns wide, and an id is plain digits. A third column is refused rather than guessed at, since nothing says whether the name was meant to hold the comma or whether a column was added, so put quotes around a name that holds one. A mapping you build in Python is held to the same rules, and its names are trimmed the same way, so the same text gives the same map whichever form you pass.

Building one is up to you, and one source is your own installation: the game's database folder holds plain tab-separated UTF-8 `.lnc` files whose `COMP_LONG_NAME_CHANGE`, `COMP_SHORT_NAME_CHANGE` and `COMP_3LETTER_NAME_CHANGE` lines are keyed on the same database id. fmsave neither locates nor reads those files.

## Command line

```console
fmsave info career.fm
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm contracts --club "Northbridge FC" --format json
fmsave export career.fm players --nation 7 --columns name,age,club_name,contract_wage,contract_end
fmsave validate career.fm --json
```

- `info` shows the game, build, database version and in-game date. It leaves out the save's name unless you pass `--show-name`. Add `--json` for JSON.
- `export` writes one table (`players`, `contracts`, `suspensions`, `clubs` or `managed-clubs`) as CSV, JSON or JSON Lines (`--format csv|json|jsonl`), to standard output or to a file with `-o`. `--columns` picks and orders columns.
- `export` needs a scope: a club by name, short name or uid (`--club`), the club you manage (`--managed-club`), or a nation id (`--nation`). Choose a scope; `--all` exists for full exports. Competition scopes arrive in a later release.
- `validate` runs every reader and reports its checks, record counts and coverage. The report holds no names, uids or text from the save, so it is safe to paste into an issue.

### Output format notes

- Nested groups flatten to `<group>_<field>` columns, such as `contract_wage`.
- A missing group, such as a player without a contract, appears as all-null subfields in JSON.
- Coded values give a label column plus a `_code` column, such as `contract_squad_status` and `contract_squad_status_code`. Tuples of coded values give two list columns, such as `traits` and `traits_code`.
- Dates are ISO 8601.
- In CSV, an empty list and a missing value both appear as an empty cell. Lists of plain values are joined with `;`, and lists of groups (such as `teams` or `clauses`) are written as compact JSON text. JSON is the lossless format.
- fmsave does not escape cells that spreadsheet programs may read as formulas.

## What it cannot read (yet)

- Planned for later releases: nation names; fixtures, league tables and per-match records, which reach a competition through the stage ids that already ship; finances, staff, injuries and tactics.
- Not stored in the save at all: competition and league names. The game renders them from its own installed database, so fmsave ships none; supply your own map to fill them in, as [Competition names](#competition-names) describes.
- Not stored in a readable way in the save: today's injuries and availability, staff attribute values, card counts, scouting budget and asking prices.

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

Report security problems privately as described in [SECURITY.md](SECURITY.md), and follow the [Code of Conduct](CODE_OF_CONDUCT.md) when taking part.

## Rights holders

To request removal of any content, open a [GitHub issue](https://github.com/rhiever/fmsave/issues/new/choose) with the rights request form.

## Disclaimer

fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored by Sports Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks or registered trademarks of their respective owners.

## License

MIT. See [LICENSE](LICENSE).
