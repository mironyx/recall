# Session 4 — Dependency upgrade (Dependabot sweep)

Chore, no tracker issue. PR [#136](https://github.com/mironyx/recall/pull/136), branch
`chore/deps-upgrade-lock`.

## Approach rationale

12 Dependabot PRs (#94–#110) all failed CI on lockfiles stale against main, and about 40
security alerts were open (certifi critical; mcp, pyjwt, filelock, virtualenv high). One
`uv lock --upgrade` PR replaces rebasing 12 PRs one by one. The project is pre-release, so every
direct dependency floor was raised to the locked version as well.

## Work completed

- `uv.lock`: full upgrade. Every open alert on main, all pages, was checked against the new lock
  and is resolved.
- `pyproject.toml`: raised the floor of every runtime and dev dependency to the current locked
  version; Markdown excluded from `ruff format`.
- `.pre-commit-config.yaml`: ruff rev v0.15.11 → v0.17.6, in lockstep with the lock.
- `tests/conftest.py`: removed the stale `type: ignore[import-untyped]`, since testcontainers
  4.15 ships type hints.
- Verification: ruff, format check, `mypy`, 225 unit and 246 integration tests; CI green on all
  4 jobs.

## Decisions made

- ruff 0.17 formats Python blocks inside Markdown. `*.md` is excluded from `ruff format` rather
  than reformatting the snippets in 7 LLDs, because those snippets are illustrative, not source.
- Major bumps were accepted with no code changes: openai 2→3, mypy 1→2, structlog 25→26 and
  langgraph-checkpoint-postgres 3.0.5→3.2.1. The 3.2.1 upgrade includes the 3.1.3 fix for a
  namespace-dot leak across store namespaces, which is relevant to ADR-0002 scoping.

## Review feedback addressed

- [ci] `tests/conftest.py:39` — unused `type: ignore` flagged by CI's bare `uv run mypy`, which
  also covers `tests/`; fixed in d9c7470. The local check had used `mypy --strict src` only.

## LLD Sync report

Skipped — no LLD covers this issue.

## Cost retrospective

Not measured; there is no tracker issue to label. One driver: an extra CI round trip because the
local type check (`mypy --strict src`) was narrower than CI (`uv run mypy`). Run the CI command
verbatim before pushing.

## Next steps

- Confirm Dependabot auto-closes #94–#110 after the merge; close any stragglers by hand.
- Consider grouping Dependabot uv updates (`groups:` in `dependabot.yml`) so future bumps arrive
  as one PR.
