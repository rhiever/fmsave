# What a save holds

A save holds players, clubs and competitions across the game world. The available history
varies by career; it is not a complete archive of every match or injury.

27 readers get at it. Each one returns a `Table` of records, and each one reads the save
you point it at and nothing else.

## People

`players()`, `contracts()`, `suspensions()`, `staff()`, `staff_lists()`

Players carry names, birth date and age, nationality, club, height, positions, 52 attributes,
the 8 personality attributes, current and potential ability, reputation, transfer value,
condition, traits, contract and any unserved ban. `contracts()` is the same contract record as a
table of its own, which is what you want when you are looking across every deal in the save
rather than at one club's players. Staff carry their people data, ability, personality and how
they prefer a side to be run. Of the attributes a staff profile rates, fmsave currently reads
only adaptability.

## Clubs

`clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`, `stadiums()`,
`affiliates()`, `job_vacancies()`

`managed_clubs()` is the club you run, and is empty between jobs. `finances()` is monthly figures
per club, in the save's own unit. `sponsorships()` includes historical contracts, so a row
does not necessarily describe current income: an ended contract can keep a non-zero annual
value, so filter on `end` against the save's date. `stadiums()` holds capacities and ownership;
names are available for only some grounds.

Club data still has limits. The meaning of a zero corporate-facilities rating and some
sponsorship amounts is unconfirmed. Some finance histories still fail continuity checks.
Passing the reader checks does not confirm every field's meaning.
See [Trusting a number](trust.md) before using these fields in an analysis.

## Competitions

`stages()`, `competitions()`, `fixtures()`, `league_tables()`, `competition_rules()`,
`transfer_windows()`, `player_match_stats()`, `player_season_stats()`

Fixtures provide dates, teams, rounds and scores where fmsave can decode an unambiguous result.

`player_season_stats()` is each player's current season, as the squad and player screens show it:
one row per competition type and team, with counts such as minutes, xG, passes and tackles, and
the per-90 and percentage figures the game shows. `player_match_stats()` reads individual match
histories stored within player records. Coverage varies by save and player; it is not a complete
career match log. Empty output passes validation when every player explicitly has no stored
history.
Incomplete or unresolved histories fail the reader checks.

## Injuries

`injury_types()`, `injuries()`

`injuries()` reads retained injury history, not a complete career medical record.

## Your own club's work

`training()`, `mentoring()`, `tactics()`, `set_pieces()`

These readers return data for the club you manage. Other clubs return no rows. `tactics()`
includes stored preset and alternate tactics; a row is a copy for one team, so the same tactic
can appear more than once.

## Limits and missing values

**Names from the installed game database.** fmsave ships no competition, league, nation or city
names and reads nothing from your game install. Some stadium names are available in the save.
See [Competition names](#competition-names) below.

**Unresolved links.** Some rules blocks cannot be linked to a competition. A club's home ground
is inferred from fixtures where possible. Missing links remain `None`.

**Unconfirmed meanings.** Most tactic settings and staff job codes have no confirmed labels.
They keep their raw numbers. Other fields can have a value whose meaning is still unconfirmed;
[Trusting a number](trust.md) explains how to check.

**Partial history.** A missing score can mean the result was not retained, is not yet decoded,
or could not be joined unambiguously. Injury history also has limits. Neither reader promises
complete career coverage.

**Unsupported fields.** fmsave does not expose today's availability, a full matchday lineup,
most staff attributes, club debt or asking prices. That does not establish whether the save
stores them. Season statistics do include yellow and red cards; check each field's status
before using it.

Unreadable values remain `None`. Empty tables need context: the save may explicitly have no
records, or the reader may have failed to recover them. Use validation and table coverage to
check the distinction.

(competition-names)=

## Competition names

Competitions carry a `database_id`, the id every outside name source is keyed on. Supply a map and
fmsave fills in `name` and every denormalised `competition_name`:

```python
import fmsave

competition_names = fmsave.read_competition_names("competition-names.csv")
with fmsave.open("career.fm", competition_names=competition_names) as career_save:
    for competition in career_save.competitions():
        print(competition.database_id, competition.name)  # 12345 "Example League"
```

The file is UTF-8, 2 columns, `database_id` then `name`; a leading header row is skipped. Any
mapping of database id to name works in its place, and `fmsave export --competition-names PATH`
takes the same file.

Without a matching map entry, `name` and `competition_name` remain `None`. Competitions without
a `database_id` cannot use this map; competitions created during a career may have no entry in
an outside name source.

## Which reader has the field you want

The [reference](../reference/records.md) lists every record type and every field. If you are not
sure a number means what you think it means, read [Trusting a number](trust.md) first.
