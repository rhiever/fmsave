---
myst:
  html_meta:
    description: "Reference for fmsave.open, the Save object and its readers, and validate_save."
---

# Save

`fmsave.open` returns a `Save`; its reader methods hand back one `Table` each. `validate_save`
runs every reader at once and reports how each fared, without raising or warning.

## Opening a save

```{eval-rst}
.. autofunction:: fmsave.open
```

## Save

```{eval-rst}
.. autoclass:: fmsave.Save
   :members: info, closed, clubs, players, contracts, suspensions, managed_clubs, stages,
       competitions, nations, fixtures, stadiums, transfer_windows, injury_types, injuries, affiliates,
       job_vacancies, league_tables, competition_rules, player_match_stats,
       player_season_stats, player_season_history, finances, sponsorships, facilities, staff, staff_lists, tactics,
       set_pieces, training, mentoring, experimental_span, close
```

## Experimental raw span

`Save.experimental_span()` is available for supported FM27 builds. It returns
partially decoded raw fixture cores and counted rules, with unsupported fields explicitly
identified. It is **not** the authoritative fixture calendar or semantic competition-rules
table. The validation report includes only its numeric coverage counts, never raw identities.

## FM27 finance interpretation

FM27 support retains the prior-month interpretation of finance snapshots. It does
not expose the current month's live income and expenditure. Snapshot timing and payroll
semantics still need independent FM27 validation. Money is returned in the save's stored
units without display-currency conversion; wages are weekly amounts. Comparing these rows
with the game's current finance overview requires matching the period and units.

## Save metadata

```{eval-rst}
.. autoclass:: fmsave.SaveInfo
.. autoclass:: fmsave.SectionInfo
```

## Competition names

`Competition.database_id` joins the id a name source keyed outside a save uses; this reads such
a source into the map `fmsave.open` takes.

```{eval-rst}
.. autofunction:: fmsave.read_competition_names
```

## Validation

```{eval-rst}
.. autofunction:: fmsave.validate_save
.. autoclass:: fmsave.ValidationReport
.. autoclass:: fmsave.ReaderValidation
.. autoclass:: fmsave.ReaderCheck
.. autoclass:: fmsave.GateResult
```

## Package metadata

```{eval-rst}
.. autodata:: fmsave.__version__
.. autodata:: fmsave.OUTPUT_SCHEMA_VERSION
```
