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
- Optional `pandas` and `polars` extras.
