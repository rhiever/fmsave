# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-18

The first public release. Nothing before it was ever published, so this entry says what fmsave is rather than what changed.

### Added

- `fmsave.open(path)`, a read-only view of a Football Manager 26 save, used as a context manager. `Save.info` carries the game, the build, the database version and the in-game date.
- Twenty-six readers, each returning a `Table` of records: `players()`, `contracts()`, `suspensions()`, `staff()` and `staff_lists()`; `clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`, `stadiums()`, `affiliates()` and `job_vacancies()`; `stages()`, `competitions()`, `fixtures()`, `league_tables()`, `competition_rules()`, `transfer_windows()` and `player_match_stats()`; `injury_types()` and `injuries()`; and `training()`, `mentoring()`, `tactics()` and `set_pieces()`, which only the club you manage stores.
- `Table`, an immutable sequence with `where()`, `filter()`, `sorted_by()`, `find()`, `by_uid()`, `by_id()` and `coverage`, and export through `to_dicts()`, `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv()`, `write_json()` and `write_jsonl()`. A slice of a table is a table, and records keep working after the save is closed.
- `fmsave.field_status`, which says whether a field's meaning is verified against the game or still unconfirmed, and a flat output schema versioned as `fmsave.OUTPUT_SCHEMA_VERSION`.
- Competition names from a map you supply, through `fmsave.open(path, competition_names=...)` and `fmsave.read_competition_names()`, keyed on the editor database id every outside name source uses.
- Reader checks that measure a decode against loose bounds drawn from a couple of careers. A missed bound is a warning and the table is returned anyway; `fmsave.open(path, strict=True)` raises instead. `fmsave.validate_save` reports checks, counts and coverage, holding no names, uids or text from the save.
- The `fmsave info`, `fmsave export` and `fmsave validate` commands, and optional `pandas` and `polars` extras.

### Notes

- fmsave needs Python 3.12 or newer. It is read-only: it never modifies a save, makes no network connection, and reads nothing from your game install.
- This is a 0.x release and the names it exports may still move. fmsave has read one game build, so the dispatch that would carry it across a change of format has not yet had to work, and a 1.0.0 would promise a stability nothing has tested. That promise is earned rather than scheduled.
- A value fmsave cannot read is `None` rather than a guess, money stays in the unit the save stores it in, and a number the game never displayed ships as a raw number rather than as a label fmsave invented.
- Names the game renders from its own installed database, which is most competition, league, nation, city and ground names, are not in a save and none are shipped. The README has the rest of what a save keeps only in part.
