# Session log — RECALL-87

## Approach rationale
- **Issue:** #87
- **Approach chosen:** Follow the LLD §E1.2 verbatim — module-level `PROJECT_ID_PATTERN` (`^[a-zA-Z0-9_-]{1,128}$`), `RESERVED_PROJECT_IDS` frozenset (`{"global", "_"}`), and a pure `validate_project_id_format()` raising `ValidationError` from the shared `errors.py` module. The LLD is already the ADR-0014-reconciled replacement for the dropped `ProjectRegistry`; any deviation would add complexity, not remove it.
- **LLD deviations:** none. (Issue body names the function `validate_project_id()`; LLD and E1.6 router call `validate_project_id_format()` — implemented per LLD.)
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
