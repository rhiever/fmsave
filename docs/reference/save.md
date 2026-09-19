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
       competitions, fixtures, stadiums, transfer_windows, injury_types, injuries, affiliates,
       job_vacancies, league_tables, competition_rules, player_match_stats, finances,
       sponsorships, facilities, staff, staff_lists, tactics, set_pieces, training, mentoring,
       close
```

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
