# What a save holds

A save is the whole game world, not only your club. A career a decade in holds over a hundred
thousand players and tens of thousands of clubs, every fixture the calendar has ever generated,
and every injury it has recorded.

Twenty-six readers get at it. Each one returns a `Table` of records, and each one reads the save
you point it at and nothing else.

## People

`players()`, `contracts()`, `suspensions()`, `staff()`, `staff_lists()`

Players carry names, birth date and age, nationality, club, height, positions, all 52 attributes,
the eight personality attributes, current and potential ability, reputation, transfer value,
condition, traits, contract and any unserved ban. `contracts()` is the same contract record as a
table of its own, which is what you want when you are looking across every deal in the save
rather than at one club's players. Staff carry their people data, ability, personality and how
they prefer a side to be run; of the twenty or so attributes a staff profile rates, only
adaptability has been located in the save.

## Clubs

`clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`, `stadiums()`,
`affiliates()`, `job_vacancies()`

`managed_clubs()` is the club you run, and is empty between jobs. `finances()` is monthly figures
per club, in the save's own unit. `stadiums()` holds capacities and ownership for tens of
thousands of grounds, but a name for only a couple of hundred of them.

## Competitions

`stages()`, `competitions()`, `fixtures()`, `league_tables()`, `competition_rules()`,
`transfer_windows()`, `player_match_stats()`

Fixtures are the calendar: date, teams, round, and a score where the save still keeps one.

## Injuries

`injury_types()`, `injuries()`

A career keeps a long injury history, but not an endless one.

## Your own club's work

`training()`, `mentoring()`, `tactics()`, `set_pieces()`

Only the club you manage stores these. Every other club returns no rows — it is not a gap in
fmsave, the data is not in the save.

## What no save can tell you

This half of the page matters as much as the half above. Knowing a thing is absent saves you an
afternoon and saves the tracker a bug report.

**Names the game renders from its own installed database.** Competitions, leagues, nations, cities
and all but a couple of hundred grounds. fmsave ships none of these and reads nothing from your
game install. See [Competition names](#competition-names) below.

**Links the save does not store.** Which competition a rules block belongs to, which ground a club
plays at. fmsave works these out from the fixture calendar where it can and leaves them empty
where it cannot.

**Meanings for numbers the game never displayed.** Staff job titles, the settings inside a tactic.
These come back as raw numbers rather than as labels fmsave guessed at.

**What the save keeps only in part, or not at all.** Of the matches a long career has played,
only about a quarter still carry a score; the rest are played fixtures with the result dropped.
Injuries older than about two years are gone. Today's availability, line-ups, staff attribute
values, card counts, club debt and asking prices are not stored at all.

Anywhere fmsave cannot read a value it gives you `None`, never a guess.

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

The file is UTF-8, two columns, `database_id` then `name`; a leading header row is skipped. Any
mapping of database id to name works in its place, and `fmsave export --competition-names PATH`
takes the same file.

Without a map, `name` and every `competition_name` is `None`. About one competition in ten carries
no database id and can never be named, and one the game created during a career carries an id no
outside source holds.

## Which reader has the field you want

The [reference](../reference/records.md) lists every record type and every field. If you are not
sure a number means what you think it means, read [Trusting a number](trust.md) first.
