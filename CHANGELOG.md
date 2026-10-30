# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-10-30

### Added

- FM27 build `27.0.0+2486695` opens through the normal library, command line, and web app reader. Other FM27 builds and unregistered layouts are rejected.
- FM27 readers use strict checks and conservative memory budgets. Unsupported tables reject, and unconfirmed or unsupported fields keep their explicit status. This does not establish that every FM27 value is decoded correctly.
- The app identifies FM27's unconfirmed field meanings and the reader version needed for FM27. Documentation now covers both editions and their coverage limits.
- Fuzzing exercises a fictional FM27 seed through the real raw-span parser while retaining decompression caps.

### Fixed

- FM27 sponsorship lists retain boundary-date rows instead of losing the whole club's list. Rejected FM27 rows in a structurally located list now fail an explicit check, even when overall coverage passes. FM26 date boundaries and failure behavior remain unchanged; rejected lists gain a diagnostic count.

- League-table points below zero, after a points deduction, read as negative instead of about 65,000.
- `league_tables()` no longer returns one-club tables that hold an earlier state of a row kept in another table, which reported a stale record in first place. Validation counts them as `superseded_blocks`.
- League-table match slots that do not hold one match whose score agrees with its result, such as slots counting two meetings or scoring hundreds of goals, keep their slot and side with the other fields empty. Validation counts them as `unreadable_match_slots`.
- `read_competition_names()` and `--competition-names` accept a file Excel saved as "CSV UTF-8". Its byte order mark no longer hides the first row. A file that is not UTF-8 raises an error that names it.
- Opening a save refuses metadata sections far larger than any save writes, and `player_season_stats()` and `player_season_history()` keep to the total decompression cap, so a small damaged or crafted file cannot take minutes and gigabytes to read.
- The web app's CSV downloads put an apostrophe before text a spreadsheet would run as a formula, as its list download already did. A CSV button no longer stays on "Writing" after another save is opened.

### Changed

- Validation reports `edited_attribute_players` for players stored past the 1 to 100 raw attribute scale, and the club-table rows that give no club by reason: `extended_table_rows`, `unanchored_table_rows` and `rejected_table_rows`.

## [0.7.0] - 2026-10-28

### Added

- A [web app](https://rhiever.github.io/fmsave/app/) reads your save in the browser, with squad and player views, filters, shortlists, and CSV downloads. No Python installation is needed, and your save stays on your computer.
- The web app uses the latest published fmsave release.
- Shared links to the web app and docs include page previews. The docs also provide a sitemap and `llms.txt`.
- `nations()` pairs save-local nation IDs with game database IDs for looking up names in an external list. The `nations` CLI export provides the same table.
- `Club.gender` identifies men's and women's clubs. Unknown codes retain their original value in exports.

### Fixed

- Valid clubs at the start of the club list are included, with their database IDs and team links. Club uid 0 is valid; use `is not None` when checking whether a club reference resolved.
- Club team lists use the club's recorded teams, fixing missing or incorrect squad links.
- Clubs with long names are included.
- `Club.unique_id` matches the game's club database ID. Re-export club IDs saved with earlier versions.
- `clubs()` includes clubs whose nation ID is 0. Their players, contracts, staff, and fixtures join to them.
- Fixtures, match records, and league tables include rows involving team 0, a national team.

Thanks to @kdr6989 for the report.

## [0.6.0] - 2026-10-24

### Added

- `player_season_history()` returns archived player statistics with the counts and computed rates of current-season rows. Each row carries an unconfirmed candidate season year and competition reference. Stored order may be nonchronological, and imported history may omit detailed counts.
- `PlayerSeasonHistory` and the `player-season-history` CLI export table support the new reader. Club and nation scopes select players by current membership and retain their rows for previous teams.
- Validation reports historical ownership counts and unresolved teams. Malformed or ambiguous history ownership raises `ReaderCheckError`.

### Fixed

- Missing player details stay empty when only another person's data is available. Players no longer borrow that person's name or other personal details, and archived statistics use the same ownership boundary.
- Failed reader caches release decompressed save sections. Repeated calls raise the saved failure without decoding again.

Thanks to @thaffy for the feature request. Refs #13.

## [0.5.11] - 2026-10-19

### Fixed

- `clubs()` now includes clubs whose valid nation references differ, including clubs playing across borders. Their teams are available to readers that join through the club index.
- Club unique IDs and affiliate-parent links can now resolve through previously omitted clubs.
- `tactics()` and `set_pieces()` no longer warn or fail strict validation solely because a managed club team has no stored tactics block. Checks for malformed, duplicate, or unread blocks remain enforced.
- The `Sponsorship.annual_value` and `sponsorships()` docs no longer say an ended contract's annual value is zero. Ended contracts often keep a non-zero annual value, so filter on `end` to find running contracts.

Refs #11.

## [0.5.10] - 2026-10-10

### Fixed

- `finances()`, `sponsorships()` and `facilities()` no longer give a club the data of a club record stored after it that the club scan does not accept, such as a club playing in another nation's league. Such data was reported under the wrong club, or failed `finance_clubs_with_two_chains` when both clubs stored a series. Other readers are unaffected and no slower.

Refs #20.

## [0.5.9] - 2026-10-10

### Fixed

- Name pools are found when their header stores nonzero values in a field that most saves leave at zero. Every other header byte, each pool entry and the uniqueness check are still verified.
- The stage table is found however far it sits from the end of `game_db`. Longer careers move it further back, which made stages, competitions, fixtures, league tables, competition rules, match stats, stadiums and job vacancies fail.
- Tactics validation accepts managers who also run national teams, whose tactic blocks the section stores alongside the club's.
- Newly generated players stored with object kind 3, and newly generated staff whose ability codes are outside the observed code set, are read instead of being dropped.

Refs #20.

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
