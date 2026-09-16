# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `fmsave.open()` and the `Save` object, used as a context manager, with `Save.info`: game, build, database version and in-game date.
- Readers for players, contracts, suspensions, clubs, managed clubs, stages and competitions: `Save.players()`, `Save.contracts()`, `Save.suspensions()`, `Save.clubs()`, `Save.managed_clubs()`, `Save.stages()` and `Save.competitions()`.
- Stage and competition rows: a stage is one part of a competition, such as a league season, a cup round or one leg of a two-legged tie, and its id is what fixtures, league tables and per-match records join through. `Save.competitions()` lists every competition the stage table names with the ids of its stages. The save stores no competition names, so those rows carry none until a name map is supplied, and `export` does not offer the two tables yet.
- Competition names from a map you supply: `fmsave.open(path, competition_names=...)` takes either a mapping of editor database id to name or the path of a two-column CSV, and `fmsave.read_competition_names()` reads such a file on its own. The key is the editor database id because that value is the same in every save and is what name sources outside a save are keyed on. A name fills `Competition.name` and every denormalised `competition_name`. fmsave ships no names, reads no game install and makes no network call.
- `Table`, an immutable sequence of records with `where`, `filter`, `find`, `by_uid`, `get_by_uid` and `coverage`, and export through `to_dicts`, `to_columns`, `to_pandas`, `to_polars`, `write_csv`, `write_json` and `write_jsonl`.
- A stable flat output schema, versioned as `fmsave.OUTPUT_SCHEMA_VERSION`.
- `fmsave.field_status`, which tells whether a field's meaning is verified or unconfirmed.
- Reader checks that reject a save whose layout does not match, and `fmsave.validate_save`, a report of checks, counts and coverage with no names or uids.
- The `fmsave info`, `fmsave export` and `fmsave validate` commands. `export` requires a scope.
- Affiliate teams: a player registered with a team another club controls, such as a B team the save stores as a club of its own, is a player of the controlling club, keeps the club storing his team in `team_club_uid`, and is not on loan. A club's `teams` list the teams it controls after its own slots, and an affiliate club's row carries its `parent_club_uid`.
- `Player.contract` and `contracts()` rows are the contract in effect at the save's in-game date, taken whole from one chain record; agreed future moves such as pre-contracts stay in the chain but never fill it. `on_loan` marks a real loan, with the club of that contract as the parent club and the loan's own dates in `loan_start` and `loan_end`. For a player away from the club that pays him, the parent club is the club of his oldest running record that carries something of a contract, so an offer from another club is never mistaken for it, whether it was made after that record or days before it.
- Optional `pandas` and `polars` extras.
