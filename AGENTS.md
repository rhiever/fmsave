# Agent instructions

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for setup, guardrails and checks.

## Local save testing

Run 1 local save parser at a time across all worktrees. Wait for it to exit before starting another save check or corpus sweep. After an interruption, check for a leftover parser before retrying.

## Keeping main in sync

- Branch from a fresh `origin/main`: run `git fetch origin` first.
- Land changes through a pull request, squash-merged.
- Check `Code scanning results / CodeQL` in PR Checks and inline annotations before merging, even when the check is advisory. Fix confirmed findings introduced by the PR and report any unresolved findings with the reason.
- For dependency changes, check the advisory Dependency audit job in PR Checks before merging.
  Read warnings in the job summary or step log and report confirmed vulnerabilities to the maintainer.
- After every merge, fast-forward the local `main` checkout (the main worktree, not a linked one):
  `git pull --ff-only origin main`.
- If that checkout is off `main`, has uncommitted changes, or cannot fast-forward, stop and report.
  Never reset, stash or force it.
- Once a branch's work is on `main`, remove its worktree (`git worktree remove`) and delete the
  branch locally and on origin. Squash merges need `git branch -D`. Never remove a worktree with
  uncommitted changes or a branch holding work not on `main`; stop and report instead.

## Crediting contributors

fmsave does not merge outside pull requests (see [CONTRIBUTING.md](CONTRIBUTING.md#how-contributions-work)).
Instead, anyone whose issue, comment, pull request, testing or findings fed a change that ships is
credited. One rule for everyone, with no tiers. Apply it to every change that came from someone
else:

1. Work out who fed the change: the issue author, commenters whose information was used, and anyone
   the maintainer names. Leave out "+1" and thanks-only comments. Never match an email address to a
   GitHub login; someone who helped only by email is credited only when the maintainer gives their
   login. Skip anyone who asked not to be credited.
2. Look up each person with `gh api users/<login> --jq '.id, .type'`. Credit only `User` accounts.
3. Extend the single `Thanks to ...` line at the end of the `[Unreleased]` changelog entry, in the
   form `Thanks to @a for the report and @b for help testing. Refs #12.` Keep the wording neutral:
   "for the report", "for the feature request", "for help testing", "for researching <topic>".
   Never say someone shared or emailed a save, and never include save data or format details. Stick to
   these phrasings, since the commit guard rejects internal planning words. If a login itself trips
   the guard, stop and ask the maintainer.
4. Add each new person to the Contributors avatar wall in [README.md](README.md#contributors), keeping it
   alphabetical by login, ignoring case. Each entry is one line:
   `<a href="https://github.com/LOGIN" title="@LOGIN"><img src="https://github.com/LOGIN.png?size=80" width="40" height="40" alt="@LOGIN"></a>`.
5. @mention each credited person in the pull request description.
6. Merge with co-author trailers, squash only:
   - Write the squash message to a file. Its last paragraph holds the trailers, one per person, as
     `Co-authored-by: <login> <ID+login@users.noreply.github.com>`, next to any other trailers.
   - Run `uv run --frozen python scripts/guard.py --commit-msg FILE`. It can take a minute.
   - Merge with `gh pr merge N --squash --body-file FILE`.
   - After `git fetch origin`, check
     `git log -1 --format='%(trailers:key=Co-authored-by)' origin/main` lists everyone. History is
     never rewritten, so a dropped trailer cannot be added later.
7. When creating a GitHub release, copy the changelog entry's thanks line into the release notes.
   Release notes before 0.6.0 were never updated with backfilled thanks lines; leave them.

Closing or commenting on someone's pull request is outward-facing: ask the maintainer first.

<!-- shared-dev-standards:start -->
## Shared development rules (v1)

- Start edits in an isolated worktree from a verified base. A managed cloud checkout counts as isolation.
- Before cleanup, preserve commits, changes, and artifacts. Verify the merge or handoff, stop associated processes, and remove only the finished worktree.
- Require a PR and passing CI for default-branch changes. Route checks from the complete PR diff. Include affected contracts and dependencies. Run full checks for unknown scope.
- Use pinned tools and locked installs. Use the same repo checks in CI and dev. Add focused regressions and report checks that skipped.
- Keep private inputs, credentials, and artifacts out of Git and cloud setup. Use synthetic fixtures and disposable services in CI. Scan for secrets and minimize CI permissions.
- Keep dependency changes focused. Test public compatibility floors separately from the dev runtime.
- Follow the repo's release rules. Treat a merge that deploys as a release. Verify the live revision and record the rollback target.
<!-- shared-dev-standards:end -->
