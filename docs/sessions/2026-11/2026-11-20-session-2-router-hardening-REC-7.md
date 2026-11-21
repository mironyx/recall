# Session log — REC-7

## Approach rationale
- **Issue:** REC-7
- **Approach chosen:** Add `except Exception` in `handle_tool_call` (log.exception, general `internal_error`); extend `_log_call` with `kind`, `scope`, optional `result_count`; `request_id` via structlog contextvars.
- **LLD deviations:** none
- **Pressure:** light — ~20 src lines, 1 source file (3 test files).

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-20T10:18:12Z | $0.41 | 2,106 in / 5,537 out | pressure: light — ~20 src lines, 1 file [models: claude-sonnet-5-5 $0.41, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-20T10:18:12Z | $0.41 | 2,106 in / 5,537 out | green on attempt 1 (290 tests, mypy, ruff) [models: claude-sonnet-5-5 $0.41, claude-haiku-5-5 $0.00] |
| 9 | 2026-11-20T10:20:33Z | $0.71 | 2,129 in / 9,910 out | review clean [models: claude-sonnet-5-5 $0.71, claude-haiku-5-5 $0.00] |
| 10 | 2026-11-20T10:20:33Z | $0.71 | 2,129 in / 9,910 out | report done; CI pass [models: claude-sonnet-5-5 $0.71, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- `test_unexpected_service_error_propagates` (E1) asserted the old propagate behaviour; replaced by `TestRouterHardening.test_internal_error_is_generalised`.
- `captured_logs` merges contextvars (structlog `capture_logs` does not), so `request_id` is assertable.

## Work completed
- PR #127: catch-all `internal_error` and fuller `mcp_call` event in `src/recall/tool_router.py`
- Tests: `TestRouterHardening` (4 added), `captured_logs` fixture in `tests/conftest.py`
- LLD wording fixed (invariant 3: `result_count` only when a `results` list is present)

## Decisions made
- The `internal_error` hint advises a retry. No LLD or ADR specifies that, so it was recorded in LLD §2.5; revisit if non-idempotent calls (`memory_save`) risk duplicate writes.

## Review feedback addressed
- Review was clean; the post-merge claims ledger flagged `result_count` wording — fixed in the LLD, not the code.

## LLD Sync report
## LLD Sync — Issue REC-7: Tool Router hardening

### Corrections (spec was wrong)
- Invariant 3 said the event always carries `result_count`; it is omitted unless the result has a `results` list (§2.5 invariants).

### Additions (not in spec)
- Exact internal-error hint text and its retry advice recorded in §2.5.

### Omissions (in spec but not built)
- None. `result_count` for search awaits REC-6 (`memory_search`).

### Confirmations (notable)
- `request_id` arrives via structlog context, as specified.

### LLD updated
File: docs/design/v2/lld-e2-search.md (status line, §2.5, invariant 3, task table)

## Cost retrospective
- PR-creation cost $0.44 (PR body); checkpoints show $0.71 at review. Final-cost query returned $0.00 (no Prometheus data), so no final figure is recorded.
- Drivers: none notable — green on attempt 1, review clean.

## Next steps
- REC-6: `memory_search` MCP tool (also needs GH #91 landed).
