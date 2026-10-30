# Agent instructions

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for setup, guardrails and checks.

## Keeping main in sync

- Branch from a fresh `origin/main`: run `git fetch origin` first.
- Land changes through a pull request, squash-merged.
- After every merge, fast-forward the local `main` checkout (the main worktree, not a linked one):
  `git pull --ff-only origin main`.
- If that checkout is off `main`, has uncommitted changes, or cannot fast-forward, stop and report.
  Never reset, stash or force it.
