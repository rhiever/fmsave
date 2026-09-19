# CLI

The `fmsave` command line: `info`, `export` and `validate`. Each block below is the real
`--help` output of the command it follows.

## fmsave

```console
$ fmsave --help
usage: fmsave [-h] [--version] COMMAND ...

Read Football Manager 26 save files. fmsave never modifies a save.

positional arguments:
  COMMAND
    info      show the game, build and in-game date of a save
    export    write one table of a save as CSV, JSON or JSON Lines
    validate  report how each reader fares on a save, without any names or
              uids

options:
  -h, --help  show this help message and exit
  --version   show program's version number and exit
```

## fmsave info

```console
$ fmsave info --help
usage: fmsave info [-h] [--show-name] [--json] SAVE

Show save metadata.

positional arguments:
  SAVE         path to a .fm save file

options:
  -h, --help   show this help message and exit
  --show-name  include the save's name, and with --json the save summary
               texts, which hold names (hidden by default)
  --json       print JSON instead of text
```

## fmsave export

```console
$ fmsave export --help
usage: fmsave export [-h] (--club VALUE | --managed-club |
                     --competition VALUE | --nation VALUE | --all)
                     [--format {csv,json,jsonl}] [--columns NAMES]
                     [--competition-names PATH] [-o PATH] [--strict]
                     SAVE TABLE

Write one table of a save. Choose exactly one scope: --club, --managed-club,
--competition, --nation or --all.

positional arguments:
  SAVE                  path to a .fm save file
  TABLE                 the table to write: players, contracts, suspensions,
                        clubs, managed-clubs, stages, competitions, fixtures,
                        league-tables, transfer-windows, competition-rules,
                        player-match-stats, stadiums, finances, sponsorships,
                        facilities, affiliates, job-vacancies, staff, staff-
                        lists, injury-types, injuries, training, mentoring,
                        tactics, set-pieces; competition-rules (a rules
                        block's competition is read from the table stored
                        after it, so --competition returns only the blocks
                        that link to one); training (only the manager's own
                        club has these, so any other club returns no rows);
                        mentoring (only the manager's own club has these, so
                        any other club returns no rows); tactics (only the
                        manager's own club has these, so any other club
                        returns no rows); set-pieces (only the manager's own
                        club has these, so any other club returns no rows)

options:
  -h, --help            show this help message and exit
  --club VALUE          rows of one club, given as a club uid or a club name
                        or short name (any case)
  --managed-club        rows of the club the human manager runs
  --competition VALUE   rows of one competition, given as a competition id, or
                        as a name once --competition-names supplies one
  --nation VALUE        rows of one nation, by nation id
  --all                 every row
  --format {csv,json,jsonl}
                        output format (default: csv)
  --columns NAMES       comma-separated flat column names to write, in this
                        order
  --competition-names PATH
                        a UTF-8 CSV of database_id,name naming competitions,
                        which no save stores
  -o, --output PATH     write to this file instead of standard output
  --strict              stop rather than write when a reader's checks fail
                        (they warn by default)
```

## fmsave validate

```console
$ fmsave validate --help
usage: fmsave validate [-h] [--json] SAVE

Run every reader and report its checks, counts and coverage. The report holds
no names, uids or text from the save.

positional arguments:
  SAVE        path to a .fm save file

options:
  -h, --help  show this help message and exit
  --json      print JSON instead of text
```
