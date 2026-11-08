## Shared development rules (v1)

- Start edits in an isolated worktree from a verified base. A managed cloud checkout counts as isolation.
- Before cleanup, preserve commits, changes, and artifacts. Verify the merge or handoff, stop associated processes, and remove only the finished worktree.
- Require a PR and passing CI for default-branch changes. Route checks from the complete PR diff. Include affected contracts and dependencies. Run full checks for unknown scope.
- Use pinned tools and locked installs. Use the same repo checks in CI and dev. Add focused regressions and report checks that skipped.
- Keep private inputs, credentials, and artifacts out of Git and cloud setup. Use synthetic fixtures and disposable services in CI. Scan for secrets and minimize CI permissions.
- Keep dependency changes focused. Test public compatibility floors separately from the dev runtime.
- Follow the repo's release rules. Treat a merge that deploys as a release. Verify the live revision and record the rollback target.
