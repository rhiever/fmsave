# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `fmsave.open()` and the `Save` object, used as a context manager, with `Save.info`: game, build, database version and in-game date.
- Readers for players, contracts, suspensions, clubs and managed clubs: `Save.players()`, `Save.contracts()`, `Save.suspensions()`, `Save.clubs()` and `Save.managed_clubs()`.
- `Table`, an immutable sequence of records with `where`, `filter`, `find`, `by_uid`, `get_by_uid` and `coverage`, and export through `to_dicts`, `to_columns`, `to_pandas`, `to_polars`, `write_csv`, `write_json` and `write_jsonl`.
- A stable flat output schema, versioned as `fmsave.OUTPUT_SCHEMA_VERSION`.
- `fmsave.field_status`, which tells whether a field's meaning is verified or unconfirmed.
- Reader checks that reject a save whose layout does not match, and `fmsave.validate_save`, a report of checks, counts and coverage with no names or uids.
- The `fmsave info`, `fmsave export` and `fmsave validate` commands. `export` requires a scope.
- Affiliate teams: a player registered with a team another club controls, such as a B team the save stores as a club of its own, is a player of the controlling club, keeps the club storing his team in `team_club_uid`, and is not on loan. A club's `teams` list the teams it controls after its own slots, and an affiliate club's row carries its `parent_club_uid`.
- `Player.contract` and `contracts()` rows are the contract in effect at the save's in-game date, taken whole from one chain record; agreed future moves such as pre-contracts stay in the chain but never fill it. `on_loan` marks a real loan, with the club of that contract as the parent club.
- Optional `pandas` and `polars` extras.
