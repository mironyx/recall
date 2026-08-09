# Session log — RECALL-87

## Approach rationale
- **Issue:** #87
- **Approach chosen:** Follow the LLD §E1.2 verbatim — module-level `PROJECT_ID_PATTERN` (`^[a-zA-Z0-9_-]{1,128}$`), `RESERVED_PROJECT_IDS` frozenset (`{"global", "_"}`), and a pure `validate_project_id_format()` raising `ValidationError` from the shared `errors.py` module. The LLD is already the ADR-0014-reconciled replacement for the dropped `ProjectRegistry`; any deviation would add complexity, not remove it.
- **LLD deviations:**
  1. `.fullmatch()` instead of the LLD's `.match()` — Python's `$` anchor matches just before a trailing `\n`, so `.match()` silently accepts `'global\n'` and a 129-char ID ending in newline, bypassing the reserved-name guard and the `{1,128}` bound. `.fullmatch()` rejects both (PR #111 review finding; regression test added).
  2. `ValidationError` is a bare `Exception` subclass for now, not `ValidationError(RecallError)` with `error`/`hint` attributes per LLD §E1.1. Deferred to #91 — E1.1 (#86) lands `RecallError` in this module in parallel, and the E1.6 error formatter (#91) is the consumer of the structured shape. Marked with `TODO(#91)` in `errors.py`.
  (Issue body names the function `validate_project_id()`; LLD and E1.6 router call `validate_project_id_format()` — implemented per LLD.)
- **Pressure:** standard — ~50 src lines across 2 source files (`validation.py`, `errors.py`), 1 test file.

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T13:05:00Z | $0.0000 | 0 | pressure: standard |
| 4bF  | 2026-08-09T13:10:00Z | $0.0000 | 0 | test-author complete (11 tests) |
| 4dF  | 2026-08-09T13:15:00Z | $0.0000 | 0 | implementation complete — 11/11 pass |
| 5    | 2026-08-09T13:30:00Z | $0.0000 | 0 | green on attempt 4 (mypy/ruff/format/11 tests). Full suite: 80/81 — pre-existing smoke-test fixture failure also fails on clean main (order-dependent: pg_conn teardown drops tables before test_container_boots runs; unrelated to #87) |
| 6    | 2026-08-09T13:35:00Z | $0.0000 | 0 | diag pass — exporter N/A (no .diagnostics in worktree); CodeScene 10.0/10.0; SonarQube N/A (repo not analyzed) |
| 6b   | 2026-08-09T13:40:00Z | $0.0000 | 0 | evaluator: PASS (0 adversarial; smoke failure independently confirmed pre-existing; stale docstring fixed) |
| 8    | 2026-08-09T13:45:00Z | $0.0000 | 0 | [PR #111](https://github.com/mironyx/recall/pull/111) |
| 9    | 2026-08-09T14:05:00Z | $0.0000 | 0 | pr-review blocker: `.match()` accepts trailing newline → fixed to `.fullmatch()`; regression tests added; ValidationError shape deferred to #91 (TODO marker) |
| 9b   | 2026-08-09T14:20:00Z | $0.0000 | 0 | re-review after fix: conformance clean; quality — Co-Authored-By "block" adjudicated false positive (no such rule in project CLAUDE.md/kb; harness mandates the trailer; history not rewritten), warn: LLD wave table wrongly claims E1.1/E1.2 share no files (both write errors.py) — flagged for lead + lld-sync |
