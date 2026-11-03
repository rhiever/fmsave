# Contributing to fmsave

Thanks for helping. fmsave is a hobby project maintained on a best-effort basis, so replies can take a while.

## How contributions work

fmsave does not merge pull requests from other people. Please open an issue instead. I implement
changes myself so the code stays consistent, and I credit everyone whose report, request, testing
or findings fed a shipped change:

- as a co-author on the commit that ships it,
- in that release's changelog entry,
- in the Contributors section of the [README](README.md#contributors).

I mention you on the pull request that ships it, so you'll get a notification. A pull request you
open anyway is read as a detailed issue and credited the same way. If you'd rather not be credited,
say so in the issue.

## Setup

fmsave uses [uv](https://docs.astral.sh/uv/) and [prek](https://github.com/j178/prek) for its commit hooks.

```console
uv sync
prek install
uv run pytest
```

Before committing, also run:

```console
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Guardrails

- **No real data in the repository.** Never commit real saves, save fragments, hex dumps,
  save-derived datasets or outputs, or real names, uids or values. This covers code, tests,
  fixtures, snapshots, docs, examples, notebook outputs, commit messages and the changes in pull
  requests. Keep them under `.local/`, which Git ignores. Issues and pull request discussion follow
  [Reporting a wrong value](#reporting-a-wrong-value).
- **Fictional examples only.** Use made-up names such as "Northbridge FC", "Alex Example" and "Example League".
- **Tests build their own inputs.** Tests create small in-memory fragments. They never build or ship a complete save.
- **Read-only.** fmsave never writes saves, reads game memory, connects to the network or decrypts anything. Changes that add any of these will not be accepted.
- **Local single-player analysis is supported.** Code and output-empty notebooks may read every row
  from your own save. Command-line exports keep the explicit `--all` gate. Do not use hidden data in
  a shared online career unless its rules and participants allow it.
- **No format write-ups.** Do not add prose descriptions of the save file format to the repository. Code and docstrings are enough.

The commit hooks check staged files and commit messages. Never skip them.

## Provenance

Knowledge of the save format may come only from observing your own saves and the in-game UI. Do not use decompilation, leaked material, material under a non-disclosure agreement, or code from unlicensed parsers. This applies to anything you share in an issue or by email too. Never share decompiled or disassembled game code, or executable bytes, anywhere.

## Reporting a wrong value

Use the bug report form, and name the field, such as `Player.contract.end` or the `contract_end`
column. `fmsave.field_status(fmsave.Player, "contract.end")` tells you whether its meaning is
verified or unconfirmed. What helps most, in order:

1. **A save sent privately**, the fastest route to a fix. Email a link to the address on
   [the maintainer's GitHub profile](https://github.com/rhiever), or a link shared only with him,
   and say in the issue that you sent one. Send only your own career, or one whose owner agreed.
   Saves are kept privately as regression tests to stop future breakage, never committed, published
   or shared, and deleted on request. Never post a save, or a link to one, publicly.
2. **Your own format findings**, posted in the issue: offsets, record layouts, counts and small hex
   snippets of about 256 bytes or less.
3. **`fmsave validate SAVE --json` output and screenshots.** The validate output holds only
   versions, counts, check results and coverage, with no names, uids or text from the save. Crop
   screenshots to the bug. A few example values or names to show the bug are fine.

Keep bulk decoded player data, such as squads, tables and CSVs, to a private email. Before posting,
remove personal details: your manager name if it is your real name, your OS username and file
paths, mod or DLL names, and platform IDs.
