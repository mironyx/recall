# Session log — REC-12

## Approach rationale

- **Issue:** REC-12
- **Approach chosen:** `ErrorCode(StrEnum)` registry in `errors.py`, `EmbeddingError`, and a
  `guarded_embed(provider)` closure at the embed seam wired into `server._build_store` and a shared
  `conftest._open_store` helper — as LLD §3.4. Alternatives (wrapping in the router by exception type,
  or a decorator provider subclass) either can't distinguish provider errors from other errors or add a class.
- **LLD deviations:** none planned
- **Pressure:** standard — ~40 src lines across 4 source files (2 test files + conftest)

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-23T20:33:22Z | $0.65 | 2,571 in / 2,872 out | pressure: standard — ~40 src lines, 4 src files [models: claude-opus-5-5 $0.65, claude-haiku-5-5 $0.00] |
| 4bF | 2026-11-23T20:36:48Z | $1.71 | 10,873 in / 23,386 out | test-author complete — 13 BDD properties, all covered (kb doc AC untested) — brief: used as-is [models: claude-opus-5-5 $1.71, claude-haiku-5-5 $0.00] |
| 4dF | 2026-11-23T20:37:20Z | $1.99 | 10,885 in / 28,902 out | implementation complete — second challenge pass: none found [models: claude-opus-5-5 $1.99, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-23T20:38:01Z | $2.16 | 10,899 in / 30,412 out | green on attempt 1 (460/460, mypy+ruff clean; e2e skip — no E2E tests; audit: PRE-EXISTING) [models: claude-opus-5-5 $2.16, claude-haiku-5-5 $0.00] |
| 6 | 2026-11-23T20:38:50Z | $2.62 | 11,640 in / 34,957 out | diag pass — test_errors.py arg-count fixed (10.0); tool_router 8.03 pre-existing untouched fns; sonar skipped (no analysis tool) [models: claude-opus-5-5 $2.62, claude-haiku-5-5 $0.00] |
| 6b | 2026-11-23T20:39:32Z | $3.09 | 11,656 in / 38,566 out | evaluator: PASS WITH WARNINGS (retry deferred to E4.1) — brief: used as-is [models: claude-opus-5-5 $3.09, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- CodeScene `tool_router.py` 8.03: complex-method/conditional/arg-count smells sit in `_parse_search_params`,
  `_check_update_types`, `_check_text`, `_log_call` — untouched by this change (one constant swapped).
  Not refactored here: outside the task's scope and lines; candidate for a router-tidy refactor issue.
- SonarQube diag skipped — the MCP exposes no analysis tool in this session.
- `kb/architecture.md`: the LLD `kb/ additions` block lists four entries (AC says three); all four added,
  since the update/delete entries from REC-9/REC-11 were never written.
- Evaluator warning: Story 1.3 AC5 retry-once-before-failing is not implemented; LLD §3.4 defers retry and
  timeout policy to E4.1's real providers. Track under E4.1.
