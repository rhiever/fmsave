# Contributing to fmsave

Thanks for helping. fmsave is a hobby project maintained on a best-effort basis, so replies can take a while.

## Setup

fmsave uses [uv](https://docs.astral.sh/uv/) and [prek](https://github.com/j178/prek) for its commit hooks.

```console
uv sync
prek install
uv run pytest
```

Before opening a pull request, also run:

```console
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Guardrails

- **No real data, anywhere.** Never commit or post real saves, save fragments, hex dumps, or real player, staff, club or competition names, uids or values. This covers code, tests, fixtures, snapshots, docs, examples, commit messages, issues and pull requests.
- **Fictional examples only.** Use made-up names such as "Northbridge FC", "Alex Example" and "Example League".
- **Tests build their own inputs.** Tests create small in-memory fragments. They never build or ship a complete save.
- **Read-only.** fmsave never writes saves, reads game memory, connects to the network or decrypts anything. Changes that add any of these will not be accepted.
- **Scoped export.** Examples and docs lead with squads, wages and contracts, and never advertise exporting a whole game database.
- **No format write-ups.** Do not add prose descriptions of the save file format to the repository, issues or pull requests. Code and docstrings are enough.

The commit hooks check staged files and commit messages. Never skip them.

## Provenance

Knowledge of the save format may come only from observing your own saves and the in-game UI. Do not use decompilation, leaked material, material under a non-disclosure agreement, or code from unlicensed parsers. The pull request template asks you to confirm this.

## Reporting a wrong value

You can report a wrong value without sharing any real data:

1. Run `fmsave validate SAVE --json` and paste the output. It holds only versions, counts, check results and coverage, with no names, uids or text from the save.
2. Name the field, such as `Player.contract.end` or the `contract_end` column. `fmsave.field_status(fmsave.Player, "contract.end")` tells you whether its meaning is verified or unconfirmed.
3. Describe what the game shows in general terms. For example: "for a few players at my club, the game shows a contract end date one year later than fmsave". Leave out names, uids and exact values.

Use the bug report form for this. Never attach a save file or a screenshot.
