# Your squad

The thing most people want from a save is their own squad: who is at the club, how good they are,
what they are paid and when their deals run out. This page goes from a file on disk to that, in
about twenty lines.

## Open the save

```python
import fmsave

with fmsave.open("career.fm") as career_save:
    my_club = career_save.managed_clubs()[0]  # empty when you are between jobs
    squad = career_save.players().where(club_uid=my_club.club_uid)
```

`fmsave.open` is a context manager. Call the readers you need inside the `with` block; asking a
closed save for another table raises `SaveClosedError`. The records and tables themselves keep
working after the save closes, so you can carry `squad` out of the block and use it for the rest
of the program.

`players()` returns every player in the save, which for a running career is well over a hundred
thousand. `where(club_uid=...)` cuts that to one club. A club's players are everyone it
registers, youth and B teams included; `team_id` and `team_slot` tell its teams apart.

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
player.contract.wage  # 34500
player.contract.end  # datetime.date(2029, 6, 30)
```

`attributes` holds all 52 attributes on the 1 to 20 display scale, from `crossing` and `passing`
to `handling` and `reflexes` for a goalkeeper. `positions` rates the fifteen position slots on the
same scale, and `natural_positions` is the shorthand for the ones rated 18 or better.
`ability` carries `current` and `potential`, `reputation` carries four figures, and `personality`
carries the eight personality attributes.

Wages and transfer values come back in the unit the save stores them in, which is not the currency
the game displays. fmsave does not convert them.

Some fields are coded values: they carry both the number the save holds and the label fmsave reads
it as.

```python
status = player.contract.squad_status
status.label  # SquadStatus.STAR_PLAYER, the reading
status.raw  # 1, the number the save holds
```

A value fmsave cannot read is `None` rather than a guess. Before you lean on a field, check
whether it is verified — see [Trusting a number](trust.md).

## Narrow it down

```python
squad.where(on_loan=True)
squad.filter(lambda player: player.age <= 21 and player.ability.potential >= 150)
squad.find(name="Alex Example")
```

- `where(**fields)` matches top-level fields for equality. Flat column names such as
  `contract_wage` are not field names; use `filter` for anything nested.
- `filter(predicate)` takes any function of a record.
- `find(name=...)` looks a person up by name and raises `AmbiguousNameError` when more than one
  matches, rather than picking one for you.

Passing an enum label to a coded-value field matches every record carrying that label:

```python
with fmsave.open("career.fm") as career_save:
    starters = career_save.contracts().where(squad_status=fmsave.SquadStatus.STAR_PLAYER)
```

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

The squad is one table of twenty-six. The same club uid opens the others:

```python
with fmsave.open("career.fm") as career_save:
    club_uid = career_save.managed_clubs()[0].club_uid

    staff = career_save.staff().where(club_uid=club_uid)
    finances = career_save.finances().where(club_uid=club_uid)
    injuries = career_save.injuries().where(club_uid=club_uid)
```

[What a save holds](what-a-save-holds.md) lists all twenty-six, and is honest about what none of
them can give you.
