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
