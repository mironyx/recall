# Session 5 — Dependabot grouping for uv

Chore, no tracker issue. PR [#137](https://github.com/mironyx/recall/pull/137), branch
`chore/dependabot-grouping`. Follow-up to session 4 (PR #136).

## Approach rationale

Per-package Dependabot PRs each rewrite `uv.lock`, so they conflict as soon as one merges. That
is how #94–#110 all went stale. Grouping produces one PR per update type.

## Work completed

- Added `.github/dependabot.yml`: `uv` ecosystem, weekly schedule, `chore(deps)` commit prefix,
  and two groups (`uv-version-updates` and `uv-security-updates`, both covering `*`).

## Decisions made

- Security updates get their own group, separate from version updates, so a security fix is
  never held back by an unrelated major bump in the same PR.
- The `github-actions` ecosystem is out of scope (uv only, as asked).

## Review feedback addressed

None.

## LLD Sync report

Skipped — no LLD covers this issue.

## Cost retrospective

Not measured; there is no tracker issue. Single-file change with no fix cycles. No CI ran because
`.github/dependabot.yml` is paths-ignored.

## Next steps

- After the merge, confirm Dependabot accepts the config (Insights → Dependency graph →
  Dependabot) and that the stale PRs #94–#110 close.
