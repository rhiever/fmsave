# fmsave

Read your Football Manager 26 and 27 saves from disk into Python records, DataFrames, CSV, and JSON.

[Documentation](https://rhiever.github.io/fmsave/): guides and the full reference.
[Release notes](https://rhiever.github.io/fmsave/changelog.html) cover each release.

No Python? [Open fmsave in your browser](https://rhiever.github.io/fmsave/app/) and drop a save on
the page. You get your squad and every player in the save, with all attributes, CA and PA, this
season's stats, and CSV downloads. The save is read on your computer and never uploaded.

## Game coverage

FM27 support covers build `27.0.0+2486695` through the normal API and commands. Other FM27
builds open as unverified builds: fmsave borrows the `27.0.0+2486695` layouts for each section
whose schema matches, and a reader of a section whose schema differs raises
`UnsupportedGameError`. Every reader runs on FM27, including fixtures, league tables,
competition rules, suspensions, per-match histories, training calendars and mentoring groups.
Three season-stat fields are not read. Run `fmsave validate SAVE --json` for reader coverage and checks.

The validation report shows which FM27 fields have been checked against the game.
`known_build` is true for `27.0.0+2486695` because every reader has a registered layout, not
because its fields are confirmed. It is false for other FM27 builds.
Unknown values stay explicit rather than borrowing FM26 meanings. Finance rows are snapshots,
not current-month totals, and money is not converted to display currency. See the
[trust guide](https://rhiever.github.io/fmsave/guides/trust.html) before relying on a value.

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

A player carries his names, birth date and age, nationality, club, height, positions, all 52
attributes, the 8 personality attributes, current and potential ability, reputation, transfer
value, condition, traits, his contract and any unserved ban. Records and tables are immutable and
keep working after the save is closed. Use `uid` for joins within a save and `unique_id` to
match database people or clubs across careers; created people can reuse deleted people's IDs.
Club uid 0 is valid. Use `is not None` to check whether a club reference resolved.

Each reader returns a `Table`: `where(...)`, `filter(...)`, `sorted_by(...)`, `find(name=...)`,
`by_uid(...)`, `by_id(...)` and `coverage`, plus `to_dicts()`, `to_columns()`, `to_pandas()`,
`to_polars()`, `write_csv(...)`, `write_json(...)` and `write_jsonl(...)`.

## What else it reads

30 readers in all, each returning a `Table` of records:

- **People**: `players()`, `contracts()`, `suspensions()`, `staff()`, `staff_lists()`
- **Clubs**: `clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`,
  `stadiums()`, `affiliates()`, `job_vacancies()`
- **Competitions**: `stages()`, `competitions()`, `fixtures()`, `league_tables()`,
  `competition_rules()`, `transfer_windows()`, `player_match_stats()`, `player_season_stats()`,
  `player_season_history()`
- **Nations**: `nations()` pairs save-local nation ids with game database ids.
- **Injuries**: `injury_types()`, `injuries()`
- **Your own club's work**, which only the club you manage stores: `training()`, `mentoring()`,
  `tactics()`, `set_pieces()`, `selections()`

Every field is either verified against the game or unconfirmed; ask with
`fmsave.field_status(fmsave.Player, "contract.wage")`. Values come from the save as stored, a value
fmsave cannot read is `None` rather than a guess, and money is kept in the unit the game stores it
in, which can differ from the currency it displays.

Reader checks test completeness, joins, and expected ranges. Failed checks warn and return
decoded tables by default. Use strict mode to stop on failed blocking checks. See
[Trusting a number](https://rhiever.github.io/fmsave/guides/trust.html) before relying on a result.

## What it cannot read

- **Names the game renders from its own installed database.** Competitions, leagues, nations,
  cities and most grounds. fmsave ships none of these and reads nothing from
  your game install. Competitions carry `database_id`, the id every outside name source is keyed
  on, so you can supply your own map. See [Competition names](#competition-names).
- **Links the save does not store**, such as which competition a rules block belongs to, or which
  ground a club plays at. Worked out from the fixture calendar where possible, left empty where not.
- **Meanings for numbers the game never displayed**, such as most settings inside a tactic, or
  staff job titles on FM26. These come back as raw numbers rather than as labels fmsave guessed at.
- **Partial history and unsupported fields**: match-score coverage that varies by save,
  older injuries, and today's availability, the next match's line-up (`selections()` holds the
  stored picks), staff attribute values, club debt and asking prices.

## Competition names

```python
competition_names = fmsave.read_competition_names("competition-names.csv")
with fmsave.open("career.fm", competition_names=competition_names) as career_save:
    for competition in career_save.competitions():
        print(competition.database_id, competition.name)  # 12345 "Example League"
```

The file is UTF-8, 2 columns, `database_id` then `name`; a leading header row is skipped. Any
mapping of database id to name works too. Without a map, `name` and every denormalised
`competition_name` is `None`. Competitions without a database id cannot use this map; those created during a career may have
no entry in an outside name source.

## Command line

```console
fmsave info career.fm
fmsave export career.fm players --managed-club -o squad.csv
fmsave export career.fm players --nation 7 --columns name,age,club_name,contract_wage
fmsave validate career.fm --json
```

`export` writes any of the 30 tables as CSV, JSON, or JSON Lines, and needs a scope:
`--club`, `--managed-club`, `--competition`, `--nation` or `--all`. Nested groups flatten to
`contract_wage`-style columns and a coded value gives a label column plus a `_code` column, so JSON
is the lossless format. `--all` is explicit and is for local analysis of your own single-player
save. `validate` runs every reader and reports its checks, counts and coverage, holding no names,
uids or text from the save, so it is safe to paste into an issue.

## Where saves live

- macOS: `~/Library/Application Support/Sports Interactive/Football Manager 26/games/`
- Windows: usually `Documents\Sports Interactive\Football Manager 26\games\`
- Steam Cloud and other stores may keep saves somewhere else.

If the game is running, copy the save and read the copy.

## Safety

fmsave is read-only. It never modifies saves, makes no network connections, and does not read game
memory. Local single-player analysis is supported. Using hidden data to gain an advantage in a
shared online career may break platform or community rules.

## Contributors

Thanks to everyone who has reported bugs, suggested features, helped test or worked out how the
game stores its data:

<p>
<a href="https://github.com/1e16miin" title="@1e16miin"><img src="https://github.com/1e16miin.png?size=80" width="40" height="40" alt="@1e16miin"></a>
<a href="https://github.com/Buglerru" title="@Buglerru"><img src="https://github.com/Buglerru.png?size=80" width="40" height="40" alt="@Buglerru"></a>
<a href="https://github.com/BWH95" title="@BWH95"><img src="https://github.com/BWH95.png?size=80" width="40" height="40" alt="@BWH95"></a>
<a href="https://github.com/GetChatGPTToDoIt" title="@GetChatGPTToDoIt"><img src="https://github.com/GetChatGPTToDoIt.png?size=80" width="40" height="40" alt="@GetChatGPTToDoIt"></a>
<a href="https://github.com/guyluzon64" title="@guyluzon64"><img src="https://github.com/guyluzon64.png?size=80" width="40" height="40" alt="@guyluzon64"></a>
<a href="https://github.com/hostlund" title="@hostlund"><img src="https://github.com/hostlund.png?size=80" width="40" height="40" alt="@hostlund"></a>
<a href="https://github.com/ironkay-beep" title="@ironkay-beep"><img src="https://github.com/ironkay-beep.png?size=80" width="40" height="40" alt="@ironkay-beep"></a>
<a href="https://github.com/jeohist" title="@jeohist"><img src="https://github.com/jeohist.png?size=80" width="40" height="40" alt="@jeohist"></a>
<a href="https://github.com/johnmmcparland" title="@johnmmcparland"><img src="https://github.com/johnmmcparland.png?size=80" width="40" height="40" alt="@johnmmcparland"></a>
<a href="https://github.com/jtstothard" title="@jtstothard"><img src="https://github.com/jtstothard.png?size=80" width="40" height="40" alt="@jtstothard"></a>
<a href="https://github.com/kdr6989" title="@kdr6989"><img src="https://github.com/kdr6989.png?size=80" width="40" height="40" alt="@kdr6989"></a>
<a href="https://github.com/mameabdou24" title="@mameabdou24"><img src="https://github.com/mameabdou24.png?size=80" width="40" height="40" alt="@mameabdou24"></a>
<a href="https://github.com/matthiasvetter1104" title="@matthiasvetter1104"><img src="https://github.com/matthiasvetter1104.png?size=80" width="40" height="40" alt="@matthiasvetter1104"></a>
<a href="https://github.com/menidi" title="@menidi"><img src="https://github.com/menidi.png?size=80" width="40" height="40" alt="@menidi"></a>
<a href="https://github.com/Namhahaha1110" title="@Namhahaha1110"><img src="https://github.com/Namhahaha1110.png?size=80" width="40" height="40" alt="@Namhahaha1110"></a>
<a href="https://github.com/OdumWorld" title="@OdumWorld"><img src="https://github.com/OdumWorld.png?size=80" width="40" height="40" alt="@OdumWorld"></a>
<a href="https://github.com/paul-anthony-oneill" title="@paul-anthony-oneill"><img src="https://github.com/paul-anthony-oneill.png?size=80" width="40" height="40" alt="@paul-anthony-oneill"></a>
<a href="https://github.com/rui7avares-create" title="@rui7avares-create"><img src="https://github.com/rui7avares-create.png?size=80" width="40" height="40" alt="@rui7avares-create"></a>
<a href="https://github.com/sebheusig" title="@sebheusig"><img src="https://github.com/sebheusig.png?size=80" width="40" height="40" alt="@sebheusig"></a>
<a href="https://github.com/thaffy" title="@thaffy"><img src="https://github.com/thaffy.png?size=80" width="40" height="40" alt="@thaffy"></a>
</p>

## Support

fmsave is a hobby project, maintained on a best-effort basis. Report problems through
[GitHub issues](https://github.com/rhiever/fmsave/issues). Never post a save file or a link to one
in an issue. A save sent privately is the fastest route to a fix: email a link to the address on
[my GitHub profile](https://github.com/rhiever). See [CONTRIBUTING.md](CONTRIBUTING.md#reporting-a-wrong-value)
for what helps most in a report. To request removal of any content, open an issue with the rights
request form.

fmsave does not merge pull requests from other people. Open an issue instead, and you'll be
credited when the change ships. See [CONTRIBUTING.md](CONTRIBUTING.md#how-contributions-work).

## Disclaimer

fmsave is an unofficial fan project. It is not affiliated with, endorsed by, or sponsored by Sports
Interactive or SEGA. Football Manager, Sports Interactive and SEGA are trademarks or registered
trademarks of their respective owners.

## License

MIT. See [LICENSE](LICENSE).
