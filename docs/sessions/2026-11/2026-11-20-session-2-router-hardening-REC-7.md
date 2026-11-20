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

## Concerns & Deferred Items

- `test_unexpected_service_error_propagates` (E1) asserted the old propagate behaviour; replaced by `TestRouterHardening.test_internal_error_is_generalised`.
- `captured_logs` merges contextvars (structlog `capture_logs` does not), so `request_id` is assertable.
