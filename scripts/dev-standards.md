## Shared development rules (v1)

- Start edits in an isolated worktree from a verified base. A managed cloud checkout counts as isolation.
- Before cleanup, preserve commits, changes, and artifacts. Verify the merge or handoff, stop associated processes, and remove only the finished worktree.
- Require a PR and passing CI for default-branch changes. Route checks from the complete PR diff. Include affected contracts and dependencies. Run full checks for unknown scope.
- Use pinned tools and locked installs. Use the same repo checks in CI and dev. Add focused regressions and report checks that skipped.
- Keep private inputs, credentials, and artifacts out of Git and cloud setup. Use synthetic fixtures and disposable services in CI. Scan for secrets and minimize CI permissions.
- Keep dependency changes focused. Test public compatibility floors separately from the dev runtime.
- Follow the repo's release rules. Treat a merge that deploys as a release. Verify the live revision and record the rollback target.

### Scope, implement, and verify

- For a small, low-risk edit, confirm scope, inspect the diff, and run targeted checks.
- For behavior changes, agree on scope and design. Use test-driven development. For multi-step work, keep a short implementation checklist of outcomes, dependencies, and acceptance checks. Write down the design for complex or risky changes.
- Work inline for cohesive changes. Delegate distinct pieces when each benefits from independent checks for spec compliance and code quality.
- Before a behavior change lands on `main`, have a fresh agent that did no implementation check the final diff against the agreed scope. Fix blocking findings and verify the fixes. If delegation is unavailable, do a separate self-check and record it as such.
- For planning, implementation, and verification, use Opus in Claude Code and the current GPT Sol workhorse in Codex. Resolve the family from the live harness. If it is unavailable, use the configured day-to-day coding model. When delegating, choose an appropriate reasoning effort and set it explicitly when supported. Use premium tiers such as Astra or Fable only when the user explicitly selects them.
