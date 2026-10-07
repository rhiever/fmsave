# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.8] - 2026-10-07

### Fixed

- Unrecognized FM26 builds can open saves that use an already observed metadata layout, including older metadata variants, without requiring a build-specific registration.
- Metadata detection rejects ambiguous or malformed candidates. Other readers retain their existing compatibility checks.

Refs #18.

## [0.5.7] - 2026-10-06

### Fixed

- Name pools accept longer UTF-8 names, including names exceeding 64 bytes, while retaining entry IDs, section bounds and a 1,024-byte safety ceiling.
- Injury labels accept Unicode space separators, including fullwidth and nonbreaking spaces used in localized text. Invalid UTF-8 and control characters remain rejected.

Refs #14.

## [0.5.6] - 2026-10-06

### Fixed

- Continued careers with variable metadata now open without false build or date errors, including saves using Russian localization.
- Localized names and larger player and staff populations read without rejecting valid tables.
- Player, staff and injury readers handle additional record variants; tactics validation accepts the broader valid range.

Refs #5.

## [0.5.5] - 2026-10-04

### Added

- `player_season_stats()` adds `possession_lost` and `non_penalty_expected_goals`, with `possession_lost_per_90` and `non_penalty_expected_goals_per_90`. All four are unconfirmed.
- Saves from build 26.3.1 are read as a known build with the 26.3.2 layouts.
- Saves from build 26.1.0 read the in-game date, so players, contracts, staff, injuries, finances and most other tables load. Fixtures, league tables, tactics and set pieces still fail their checks there, and the build is still reported as unknown.

### Fixed

- `job_vacancies()` reads job-centre records that store a list of ids; such saves no longer fail the section size check.
- `set_pieces()` reads user routines whose tail flag differs from the usual value instead of merging them into the next routine.
- `finances()` validation accepts a club's first month when its oldest row holds the opening balance, as series begun with the career do. Early-career saves no longer fail `finance_balance_continuity`. New anomaly `opening_balance_steps`.
- `league_tables()` validation applies `double_round_robin_divisions` only once the fixture calendar shows enough divisions under way, so preseason saves no longer fail it. New anomaly `started_calendar_divisions`.
- `facilities()` counts a club that stores no corporate-facilities rating (a zero in an all-zero block) as unset instead of out of range. Saves tracking many nations no longer fail its checks. New check `facility_unset_ratings` and anomaly `unset_ratings`.
- The "game_info does not match build" error says which build check failed.

## [0.5.4] - 2026-09-30

### Fixed

- `tactics()` reads presets and alternate tactics. `tactics()` and `set_pieces()` support more continued careers. Validation checks complete team lists, including empty lists, with `tactic_records_count_matching`; unrelated tactics cannot fill gaps.
- `stadiums()` excludes a spurious ground. Validation drops `stadiums.template_rows`.
- `staff_lists()` keeps valid members beside empty references.
- Player and staff readers recover missed people, contracts and season-stat joins. Club data no longer appears as staff contracts.
- Retained contracts without substantive terms no longer count as current paid contracts when registration is absent and no independent current end date exists. Raw chains remain available.
- `competition_rules()` recovers missed rounds, including in continued careers. Legacy `match_count` stays raw and is no longer a verified fixture count.
- `fixtures()` recovers missing scores, rejects ambiguous or conflicting joins, keeps distinct fixtures with proven ownership, separates final scores from penalties, and leaves unplayed matches unscored.
- `fixtures()` recovers omitted calendar rows, including unplayed and trailing fixtures, corrects played statuses, and excludes proven cached copies. Calendar checks still apply; neutral-venue flags use recovered fixtures.
- `player_match_stats()` recovers stored histories with missing team references, excludes unrelated data, and detects incomplete or unresolved histories. Empty output passes validation only when every player explicitly has no stored history. Malformed histories no longer cause repeated scans.
- `suspensions()` recovers entries with attached match records when the full list can be read.
- `sponsorships()` respects each club's primary list, including empty lists, and retains historical contracts. Other sponsor-shaped data cannot replace an empty or invalid list.

## [0.5.3] - 2026-09-29

### Fixed

- `set_pieces()` recovers missed routines, including multiple user routines per slot, and checks complete groups with `set_piece_blocks_complete`.
- `players()` reads complete records with 0 current ability; their contracts no longer appear as staff contracts.
- Fixture validation distinguishes stub teams from missing club joins with `fixture_club_teams_resolved`, without lowering the join threshold.

## [0.5.2] - 2026-09-29

### Added

- `Club.unique_id` helps match clubs across careers. `Club.uid` still joins within a save.

### Fixed

- `stages()` and dependent readers find older stage tables in continued careers.

## [0.5.1] - 2026-09-28

### Added

- `player_season_stats()` adds 44 computed rates, including `expected_goals_per_90`, `pass_completion_percent` and `save_percent`. Every export includes them.

## [0.5.0] - 2026-09-28

### Added

- `player_season_stats()` and the `player-season-stats` export: 56 current-season stats per competition type and team, including minutes, rating, xG, xA, passes, tackles, cards and saves. Types cover league, cup, continental, international, non-competitive, overall and 2 calendar-year totals.

## [0.4.8] - 2026-09-28

### Fixed

- Careers started before a game update open without a false "game_info does not match build" error.
- `stages()` and dependent readers find stage tables with more data stored after them.

## [0.4.7] - 2026-09-27

### Fixed

- `finances()` labels months correctly on saves taken on a month's last day.

## [0.4.6] - 2026-09-27

### Fixed

- `finances()`, `sponsorships()` and `facilities()` read clubs with only 1 or 2 months of finance history, including histories begun mid-career. Short histories must balance and show money movement.
- Smaller databases, including FM26 Console saves, now supply most competition database IDs and no longer falsely fail competition validation.

## [0.4.5] - 2026-09-26

### Fixed

- `fixtures()`, `league_tables()` and `player_match_stats()` handle dates around 2048. Fixtures were affected from 2040; player match statistics would have failed from 2047.

## [0.4.4] - 2026-09-26

### Added

- `Player.unique_id` and `Staff.unique_id` identify people across careers started from the same database, directly after `uid` in exports. Deleted people's IDs may be reused.

### Fixed

- `Player.uid` and `Staff.uid` are documented as save-local join IDs, rather than database IDs. Values and joins are unchanged.

## [0.4.3] - 2026-09-25

### Fixed

- Windows saves, including FM26 Console saves, no longer falsely fail with "game_info does not match build".
- Smaller databases no longer fail name-pool checks that blocked players, contracts, staff and other name-resolving readers. Name IDs and lengths remain checked.

## [0.4.2] - 2026-09-24

### Fixed

- Stage-table misreads no longer cause false duplicate-stage errors, including on saves with many playable nations. This restores stages, competitions, fixtures, league tables and player match statistics.

## [0.4.1] - 2026-09-21

### Fixed

- Pre-Continue saves use the summary date when the normal clock is absent.
- Fresh saves no longer falsely fail checks for player attributes, complete join dates or matches without statistics.

### Changed

- Local single-player whole-save analysis is supported. `--all` remains explicit; save-derived data stays out of the repository, and support accepts no save uploads.

## [0.4.0] - 2026-09-18

The initial public release; earlier versions were never published.

### Added

- `fmsave.open(path)` opens an FM26 save as a read-only context manager. `Save.info` exposes game, build, database version and in-game date.
- 26 readers returning `Table` records: `players()`, `contracts()`, `suspensions()`, `staff()`, `staff_lists()`; `clubs()`, `managed_clubs()`, `finances()`, `sponsorships()`, `facilities()`, `stadiums()`, `affiliates()`, `job_vacancies()`; `stages()`, `competitions()`, `fixtures()`, `league_tables()`, `competition_rules()`, `transfer_windows()`, `player_match_stats()`; `injury_types()`, `injuries()`; and managed-club `training()`, `mentoring()`, `tactics()`, `set_pieces()`.
- Immutable `Table` queries: `where()`, `filter()`, `sorted_by()`, `find()`, `by_uid()`, `by_id()` and `coverage`. Exports: `to_dicts()`, `to_columns()`, `to_pandas()`, `to_polars()`, `write_csv()`, `write_json()` and `write_jsonl()`. Slices remain tables; records survive closing the save.
- `fmsave.field_status` distinguishes verified and unconfirmed fields. `fmsave.OUTPUT_SCHEMA_VERSION` versions flat output.
- User-supplied competition names through `competition_names=` and `fmsave.read_competition_names()`, keyed by database ID.
- Reader checks warn by default; `strict=True` raises. `fmsave.validate_save` reports checks, counts and coverage without names, UIDs or save text.
- `fmsave info`, `export` and `validate`, plus optional `pandas` and `polars` extras.

### Notes

- Requires Python 3.12+. Never modifies saves, connects to the network or reads the game install.
- The 0.x API may change. Only 1 game build has been read; compatibility across format changes is untested.
- Unreadable values are `None`; money keeps the save's unit; unidentified numbers remain raw.
- Most competition, league, nation, city and ground names come from the game's installed database and are not shipped. See the README for coverage limits.
