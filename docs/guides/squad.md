---
myst:
  html_meta:
    description: "Read your Football Manager 26 and 27 squads with fmsave: attributes, ability, contracts, and season stats, sorted, filtered, and exported."
---

# Your squad

Read your squad, compare ability and season performance, and export the results.

## Open the save

```python
import fmsave

with fmsave.open("career.fm") as career_save:
    managed = career_save.managed_clubs()
    if not managed:
        raise ValueError("No managed club: choose a club from career_save.clubs()")
    my_club = managed[0]
    squad = career_save.players().where(club_uid=my_club.club_uid)
```

`fmsave.open` is a context manager. Call the readers you need inside the `with` block; asking a
closed save for another table raises `SaveClosedError`. The records and tables themselves keep
working after the save closes, so you can carry `squad` out of the block and use it for the rest
of the program.

`players()` returns the players fmsave reads from the save. `where(club_uid=...)` cuts that
to one club, including its youth and B teams. `team_id` and `team_slot` tell its teams apart.

## Sort it

```python
best = squad.sorted_by(lambda player: player.ability.current, reverse=True)

for player in best[:5]:
    print(player.name, player.age, player.ability.current, player.ability.potential)
    # "Alex Example" 24 148 165
```

A slice of a `Table` is a `Table`, and tables are immutable, so `sorted_by` hands back a new
table and leaves the original alone.

## Read a player

```python
player = best[0]

player.attributes.finishing  # 16
player.attributes.determination  # 17
player.positions.stc  # 20
player.natural_positions  # ("STC", "AMC")
player.personality.professionalism
if player.contract is not None:
    print(player.contract.wage, player.contract.end)
```

`attributes` holds 52 attributes on the 1 to 20 display scale, from `crossing` and `passing`
to `handling` and `reflexes` for a goalkeeper. `positions` rates the 15 position slots on the
same scale, and `natural_positions` is the shorthand for the ones rated 18 or better.
`ability` carries `current` and `potential`, `reputation` carries 4 figures, and `personality`
carries the 8 personality attributes.

Wages and transfer values come back in the unit the save stores them in, which can differ from the
currency the game displays. fmsave does not convert them.

Some fields are coded values: they carry both the number the save holds and the label fmsave reads
it as.

```python
if player.contract is not None:
    status = player.contract.squad_status
    if status is not None:
        print(status.label, status.raw)
```

A value fmsave cannot read is `None` rather than a guess. Before you lean on a field, check
whether it is verified. See [Trusting a number](trust.md).

## Narrow it down

```python
squad.where(on_loan=True)
squad.filter(
    lambda player: (
        player.age is not None
        and player.age <= 21
        and player.ability.potential is not None
        and player.ability.potential >= 150
    )
)
squad.find(name="Alex Example")
```

- `where(**fields)` matches top-level fields for equality. Flat column names such as
  `contract_wage` are not field names; use `filter` for anything nested.
- `filter(predicate)` takes any function of a record.
- `find(name=...)` returns a table of all exact name matches, ignoring case and surrounding
  whitespace. It can be empty or contain several people.

Passing an enum label to a coded-value field matches every record carrying that label:

```python
with fmsave.open("career.fm") as career_save:
    starters = career_save.contracts().where(squad_status=fmsave.SquadStatus.STAR_PLAYER)
```

## Compare season performance

```python
with fmsave.open("career.fm") as career_save:
    season = career_save.player_season_stats().where(
        club_uid=my_club.club_uid, kind=fmsave.SeasonStatsKind.OVERALL
    )

regulars = season.filter(lambda row: row.minutes >= 900)
ranked = regulars.sorted_by(lambda row: row.expected_goals_per_90, reverse=True)
for row in ranked[:5]:
    print(row.player_name, row.minutes, row.expected_goals_per_90, row.pass_completion_percent)
```

Choose one `kind` before comparing players: league, cup and overall rows overlap. `OVERALL`
is the club season total; rows can also cover another team a player played for this season.
Join a row's `player_uid` to `Player.uid` when you need attributes or contract details.

Rates are calculated from the counts and included in every export. They are `None` when the
count does not apply or the denominator is zero. The minutes filter above excludes zero-minute
rows and limits comparisons to players with some playing time.

## Out to pandas, CSV or JSON

```python
frame = squad.to_pandas()  # needs fmsave[pandas]
frame[["name", "age", "ability_current", "contract_wage"]].head()

squad.write_csv("squad.csv")
```

The DataFrame and the CSV use flat column names: nested groups become `ability_current`,
`contract_wage`, `attributes_finishing`. [Getting data out](exporting.md) covers the rest of the
formats, the flattening rules, and doing the same job from the command line.

## The rest of the club

The squad is 1 of 30 tables. The same club uid opens the others:

```python
with fmsave.open("career.fm") as career_save:
    club_uid = career_save.managed_clubs()[0].club_uid

    staff = career_save.staff().where(club_uid=club_uid)
    finances = career_save.finances().where(club_uid=club_uid)
    injuries = career_save.injuries().where(club_uid=club_uid)
```

Club uid 0 is valid; use `is not None` to check whether a club reference resolved.

Use `uid` to join records within a save. To match players, staff, or clubs across careers started
from the same database, use `unique_id` when available. The game can reuse a deleted person's
ID for a new person, so check identity before treating it as a lasting match.

[What a save holds](what-a-save-holds.md) lists the readers and their limits.
