---
myst:
  html_meta:
    description: "Reference for every record type fmsave reads from a Football Manager 26 save and its fields."
---

# Records

The dataclass each reader's `Table` holds, grouped by the reader family that produces it.
`Table` itself, and the value-wrapper and metadata types shared across every reader, live on
their own pages: see {doc}`table` and {doc}`enums`.

## People

`players()`, `contracts()`, `suspensions()`, `staff()` and `staff_lists()`.

```{eval-rst}
.. autoclass:: fmsave.Player
.. autoclass:: fmsave.Attributes
.. autoclass:: fmsave.Ability
.. autoclass:: fmsave.Reputation
.. autoclass:: fmsave.Positions
.. autoclass:: fmsave.Personality
.. autoclass:: fmsave.Contract
.. autoclass:: fmsave.Clause
.. autoclass:: fmsave.ContractChainEntry
.. autoclass:: fmsave.PlayerSuspension
.. autoclass:: fmsave.Suspension
.. autoclass:: fmsave.Staff
.. autoclass:: fmsave.StaffAttributes
.. autoclass:: fmsave.StaffPreferences
.. autoclass:: fmsave.StaffList
```

## Clubs

`clubs()`, `facilities()`, `stadiums()`, `finances()`, `sponsorships()`, `affiliates()` and
`job_vacancies()`.

```{eval-rst}
.. autoclass:: fmsave.Club
.. autoclass:: fmsave.Team
.. autoclass:: fmsave.ClubFacilities
.. autoclass:: fmsave.Stadium
.. autoclass:: fmsave.FinanceMonth
.. autoclass:: fmsave.Sponsorship
.. autoclass:: fmsave.AffiliateGroup
.. autoclass:: fmsave.JobVacancy
```

## Nations

`nations()` pairs each save-local `nation_id` with its game `database_id`. Join other
tables' nation fields to `nation_id`, then use `database_id` with an external name map.

```{eval-rst}
.. autoclass:: fmsave.Nation
```

## Competitions

`stages()`, `competitions()`, `fixtures()`, `league_tables()`, `transfer_windows()`,
`competition_rules()` and `player_match_stats()`.

```{eval-rst}
.. autoclass:: fmsave.Stage
.. autoclass:: fmsave.Competition
.. autoclass:: fmsave.Fixture
.. autoclass:: fmsave.LeagueTable
.. autoclass:: fmsave.LeagueTableSplit
.. autoclass:: fmsave.LeagueTableMatch
.. autoclass:: fmsave.LeagueTableRow
.. autoclass:: fmsave.TransferWindow
.. autoclass:: fmsave.CompetitionRules
.. autoclass:: fmsave.RulesRound
.. autoclass:: fmsave.PlayerMatchStats
```

## Season statistics

`player_season_stats()`: each player's current season, one row per competition type and team.

```{eval-rst}
.. autoclass:: fmsave.PlayerSeasonStats
   :members:
```

`player_season_history()`: archived rows with the same counts and rates. Candidate year and
competition-reference meanings remain unconfirmed; stored order need not be chronological.
See [exporting](../guides/exporting.md) for sparsity and scope details.

```{eval-rst}
.. autoclass:: fmsave.PlayerSeasonHistory
   :members:
   :inherited-members:
```

## Injuries

`injury_types()` and `injuries()`.

```{eval-rst}
.. autoclass:: fmsave.InjuryType
.. autoclass:: fmsave.InjuryRecord
```

## Managed-club-only

`managed_clubs()`, `tactics()`, `set_pieces()`, `training()` and `mentoring()`: rows here exist
only for the club the save's human manager runs.

```{eval-rst}
.. autoclass:: fmsave.ManagedClub
.. autoclass:: fmsave.Tactic
.. autoclass:: fmsave.TacticSlot
.. autoclass:: fmsave.TacticSettingUnit
.. autoclass:: fmsave.SetPieceRoutine
.. autoclass:: fmsave.TeamTraining
.. autoclass:: fmsave.TrainingSchedule
.. autoclass:: fmsave.TrainingWeek
.. autoclass:: fmsave.MentoringGroup
```
