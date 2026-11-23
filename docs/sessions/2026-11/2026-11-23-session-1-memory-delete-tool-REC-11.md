# Session log — REC-11

## Approach rationale

- **Issue:** REC-11
- **Approach chosen:** Thin pass-through per the LLD: `StorageAdapter.delete` builds the
  namespace (scope invariant) then `adelete`; `MemoryService.delete` delegates with no
  existence check; `_handle_memory_delete` validates the three locators with
  `_missing_fields` + `_check_text` and returns `{"ok": true}`. Embedding rows go via the
  `store_vectors` FK cascade.
- **LLD deviations:** `_check_text` type-checks the locators (non-string id →
  `validation_error`, not `internal_error`), carried over from the REC-10 review.
- **Pressure:** standard — ~55 src lines across 4 source files (3 test files); most of it is
  the tool description and schema in `server.py`.

## Cost checkpoints
| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-23T20:04:09Z | $0.74 | 2,502 in / 3,225 out | pressure: standard — ~55 src lines, 4 src files, 3 test files [models: claude-opus-5-5 $0.74, claude-haiku-5-5 $0.00] |
| 4bF | 2026-11-23T20:07:16Z | $1.65 | 12,333 in / 20,548 out | test-author complete — 15 BDD properties, all covered — brief: used as-is [models: claude-opus-5-5 $1.65, claude-haiku-5-5 $0.00] |
| 4dF | 2026-11-23T20:07:49Z | $1.78 | 12,339 in / 22,920 out | implementation complete — second challenge pass: none found (delete hits PK; idempotent by design) [models: claude-opus-5-5 $1.77, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-23T20:09:18Z | $2.12 | 13,930 in / 27,307 out | green on attempt 2 (stale unknown-tool test); typecheck via mypy (wrapper wants pyright, not installed); audit: PRE-EXISTING; e2e: skip [models: claude-opus-5-5 $2.11, claude-haiku-5-5 $0.00] |
| 6 | 2026-11-23T20:10:51Z | $2.68 | 13,956 in / 33,374 out | diag pass — no smells on changed lines; split service delete tests to own file (8.03→7.78 drop); sonar skipped (no MCP analysis tool); justification ok [models: claude-opus-5-5 $2.68, claude-haiku-5-5 $0.00] |
| 6b | 2026-11-23T20:11:29Z | $3.09 | 13,970 in / 35,486 out | evaluator: PASS, 0 adversarial — brief: used as-is [models: claude-opus-5-5 $3.08, claude-haiku-5-5 $0.00] |
| 8 | 2026-11-23T20:12:01Z | $3.25 | 13,980 in / 37,774 out | [PR #133](https://github.com/mironyx/recall/pull/133) [models: claude-opus-5-5 $3.24, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- `tests/test_tool_router.py:356` used `memory_delete` as its "unknown tool" example; once
  the tool was wired it failed. Switched to `memory_purge` (assertion unchanged).
- CodeScene: `tests/test_memory_service.py` dropped 8.03→7.78 (function count); moved `TestMemoryServiceDelete` to `tests/test_memory_service_delete.py` (issue named the old file). Other yellow scores unchanged from main, no smell on changed lines.
- CI `mypy` (bare, covers `tests/`) failed on `assert await x.delete(...) is None`
  (`func-returns-value`); CLAUDE.md lists `mypy --strict src` only. Dropped the `is None` asserts.
- Review warn: duplicated `_vector_rows` test helper → reuse `_vector_row_count` from
  `tests/test_memory_service.py`. Fix: 0 source lines — self-checked, skipped re-review.
- Deferred: MCP tool annotations (`idempotentHint`, `destructiveHint`) — none of the 5 tools
  set them; would be an all-tools change, not this PR (surface review, PR #133).
