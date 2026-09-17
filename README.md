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

## What it reads

- **Save info** (`career_save.info`): game, build, database version and in-game date.
- **Players** (`players()`): names, birth date and age, nationality, club, positions, attributes, personality, traits, reputation, transfer value, contract and unserved suspensions.
- **Contracts** (`contracts()`): wage, start and end dates, squad status, contract type, clauses and loan details for every player with a contract. Each row is the contract in effect at the save's in-game date, never an agreed future move such as a pre-contract or a transfer that takes effect later. Squad status is the role agreed in the contract, not a forecast of how much the player plays.
- **Suspensions** (`suspensions()`): each unserved suspension with its player, club, competition id and date issued, including bans the game no longer displays.
- **Clubs** (`clubs()`): name, short name, nation id, reputation, last league position and teams.
- **Managed clubs** (`managed_clubs()`): the club the human manager runs. The list is empty when the manager is between jobs.
- **Stages** (`stages()`): every stage of every competition, with the stage id that fixtures, league tables and per-match records join through, plus the competition id, group and round. A league season is one stage, a cup round is one, and each leg of a two-legged tie is its own stage.
- **Competitions** (`competitions()`): every competition the stage table names, with the ids of its stages and, for about nine competitions in ten, the competition's id in the game's own editor database. The save stores no competition names, so every row's `name` is empty until you supply a name map; see [Competition names](#competition-names).
- **Fixtures** (`fixtures()`): every match the save has scheduled or played, in date and kick-off order, with its stage, competition, round, date, kick-off time, season, both team ids and the clubs they belong to, and whether the match was played away from the home club's usual ground. A save holds several copies of its calendar, one of them a block of template matches dated years off the clock; only the career's own calendar is returned. The goals of a played match are filled in from the separate records the save keeps scores in, which still cover about a quarter of the matches a career has played; empty goals on a played match mean the save no longer holds that score, not that it finished goalless. `export` writes this table under any scope: a club, managed-club or nation scope keeps a match either side of which is in it, and `--competition` keeps a whole competition.
- **Transfer windows** (`transfer_windows()`): every transfer window the save's rules database holds, in stored order, with the day and month each one opens and closes and which of the season's two years each date falls in. A window is database content rather than career state: every save made from one installed database holds the same windows, whatever has happened in the career. The dates are season-relative, so a window carries an offset from the season's start year rather than a calendar date, and a window has no name of its own. A save returns more rows than it has distinct windows, and rows that repeat are equal in every field, so deduplicate if you want one row per window. `export` writes the table under `--all`, the only scope it takes: a window names no club, competition or nation fmsave can read.
- **League tables** (`league_tables()`): every live table the save holds, in the order the save stores them, with one row per club: its total record, its home, away, first-half and second-half splits, and one slot per match with the opponent, the score, the result and the points. Rows come back in the save's own standings order, which is the league position, so do not re-sort them: the game separates clubs level on points by their results against each other first, and no field here carries that, so a sort by points and goal difference moves clubs the save had in the right order. Nothing in a table names its competition, so it is voted for from the fixture calendar, and a table the vote cannot settle carries none and is still returned. The vote settles almost every table, but read that beside the shape of the tables: 30% to 43% of them hold a single club and settle on a majority of one, and over the tables of two clubs or more it settles 0.998 to 1.000 of them. Each slot says whether it was played at home or away: the save alternates venue with the slot's parity, and the even slots are the home ones, which is checked against the fixture calendar's own home team on every table whose results account for one season of it and holds on 99.8% of the slots that calendar can settle. `export` writes the table under any scope, always whole tables: a club or nation scope keeps the standings a club of it sits in.
- **Competition rules** (`competition_rules()`): every rules block the save holds, in the order the save stores them, carrying a competition's promotion, play-off and relegation places, its tie-break codes, its prize money by finishing position and its round calendar. **A row's competition comes from where the save keeps the block, not from a field it stores**: the span alternates rules blocks and league-table blocks, and the table stored right after a block is the one that block's rules govern, so `competition_id` and `competition_name` are that table's and are empty where the blocks that follow are not exactly one table with a competition of its own — 32% to 45% of rows. Every field is unconfirmed: the competition is a vote on the fixture calendar rather than a stored value, and nothing else here has been read back off a screen. The squad and financial rules the save's rules database holds are not read, since nothing readable ties one of those groups to a competition and their content is identical on every save, so `kind` is the preamble kind on every row; transfer windows are their own table. `export` writes the table under `--competition` or `--all`.
- **Per-match player stats** (`player_match_stats()`): every match a player played that the save still holds a record of, in player order and, inside each player, in the order the save stores them, as `PlayerMatchStats` rows carrying the date, the competition, the opponent's team and the club fielding it, and, for a match the save kept a performance body for, the position played, minutes, goals, assists, the rating, the minute the player left the pitch and both pass counts. This is never a whole season and never a career: the save keeps about twenty matches per player per spell at a team, across all competitions at once, and drops the oldest as new ones arrive, so a player who has played more than that has only his most recent matches here, and a per-competition total summed from these rows is short without saying so. Friendlies, internationals and youth matches are kept apart from these records and are not here at all. A match the save kept no body for carries its date, competition and opponent and nothing else, because the record stops there. The position is a bit mask of this table's own, read as a `MatchPosition` coded value: only the goalkeeper bit is named, and every other mask keeps its raw number rather than being given a meaning the game never displayed. `body_valid` says whether fmsave finds a body's own numbers sound; a body it does not is flagged and kept exactly as stored, never blanked. `export` writes the table under any scope, keeping the matches of the players a club or nation scope holds.

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
fmsave export career.fm fixtures --managed-club --format json
fmsave validate career.fm --json
```

- `info` shows the game, build, database version and in-game date. It leaves out the save's name unless you pass `--show-name`. Add `--json` for JSON.
- `export` writes one table (`players`, `contracts`, `suspensions`, `clubs`, `managed-clubs`, `stages`, `competitions`, `fixtures`, `league-tables`, `transfer-windows`, `competition-rules`, `player-match-stats`, `stadiums`, `finances`, `sponsorships`, `affiliates`, `job-vacancies`, `staff`, `staff-lists`, `injury-types`, `injury-history`, `training`, `mentoring`, `tactics` or `set-pieces`) as CSV, JSON or JSON Lines (`--format csv|json|jsonl`), to standard output or to a file with `-o`. `--columns` picks and orders columns.
- `export` needs a scope: a club by name, short name or uid (`--club`), the club you manage (`--managed-club`), a competition by id (`--competition`), or a nation id (`--nation`). Choose a scope; `--all` exists for full exports. A table takes only the scopes its rows can answer, and a scope it does not take names the ones it does.
- `--competition-names` names the competitions of one run, from the same file `fmsave.read_competition_names` reads. Without it a competition has only its id, so `--competition` takes an id alone; with it, `--competition` also takes a name.
- `validate` runs every reader and reports its checks, record counts and coverage. The report holds no names, uids or text from the save, so it is safe to paste into an issue.

### Output format notes

- Nested groups flatten to `<group>_<field>` columns, such as `contract_wage`.
- A missing group, such as a player without a contract, appears as all-null subfields in JSON.
- Coded values give a label column plus a `_code` column, such as `contract_squad_status` and `contract_squad_status_code`. Tuples of coded values give two list columns, such as `traits` and `traits_code`.
- Dates are ISO 8601.
- In CSV, an empty list and a missing value both appear as an empty cell. Lists of plain values are joined with `;`, and lists of groups (such as `teams` or `clauses`) are written as compact JSON text. JSON is the lossless format.
- fmsave does not escape cells that spreadsheet programs may read as formulas.

## What it cannot read (yet)

- Planned for later releases: nation names, stadiums, finances, staff, injuries and tactics.
- Not stored in the save at all: competition and league names. The game renders them from its own installed database, so fmsave ships none; supply your own map to fill them in, as [Competition names](#competition-names) describes.
- Not stored in the save at all: which competition a rules block belongs to. No field inside a block names one, and a measured search of every offset around a block found none. What a `competition_rules()` row carries instead comes from where the save keeps the block: the league table stored right after it. That leaves 32% to 45% of rows with an empty competition, and the rest with one that is a vote on the fixture calendar rather than a stored link.
- Not stored in the save at all: which competition a transfer window applies to. A window names no competition, club or nation fmsave can read, so its rows stand on their dates alone.
- Not named in the save: the meaning of most round codes. Five are named, each from a round label the game itself displayed, and every other code comes back as a raw number rather than a meaning fmsave guessed at.
- Not shipped yet: a fixture's stadium as a club uid. The fixture stores a stadium ordinal and nothing that turns that ordinal into a uid; the stadium table is a later release. The ordinal is still read, and is what says whether a match was played away from the home club's usual ground.
- Not named in the save: the squad and financial rules the rules database holds. They sit in tagged groups that nothing readable ties to a competition, their content is identical on every save of one installed database, and no displayed label pins the meaning of the values they hold, so `competition_rules()` ships no field for them.
- Kept only in part: the score of a played match. The fixture calendar stores no score, and the records that do are retained for about a quarter of the matches a career has played, so the rest come back with empty goals. The save also keeps several seasons of older results whose fixtures it no longer holds, and those have nothing to attach to.
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

## Rights holders

To request removal of any content, open a [GitHub issue](https://github.com/rhiever/fmsave/issues/new/choose) with the rights request form.

## Disclaimer

fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored by Sports Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks or registered trademarks of their respective owners.

## License

MIT. See [LICENSE](LICENSE).
