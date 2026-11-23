# Session log — REC-12

## Approach rationale

- **Issue:** REC-12
- **Approach chosen:** `ErrorCode(StrEnum)` registry in `errors.py`, `EmbeddingError`, and a
  `guarded_embed(provider)` closure at the embed seam wired into `server._build_store` and a shared
  `conftest._open_store` helper — as LLD §3.4. Alternatives (wrapping in the router by exception type,
  or a decorator provider subclass) either can't distinguish provider errors from other errors or add a class.
- **LLD deviations:** log event `embedding_provider_failed`; `_open_store` takes `dims`; four kb entries (see LLD Sync report)
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
| 8 | 2026-11-23T20:40:05Z | $3.22 | 11,664 in / 40,135 out | [PR #135](https://github.com/mironyx/recall/pull/135) [models: claude-opus-5-5 $3.22, claude-haiku-5-5 $0.00] |
| 9 | 2026-11-23T20:41:03Z | $3.89 | 12,397 in / 46,827 out | review clean — 0 findings [models: claude-opus-5-5 $3.89, claude-haiku-5-5 $0.00] |
| 10 | 2026-11-23T20:41:41Z | $3.99 | 12,403 in / 47,844 out | report done — CI pass, review clean, PR ready [models: claude-opus-5-5 $3.98, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- CodeScene `tool_router.py` 8.03: complex-method/conditional/arg-count smells sit in `_parse_search_params`,
  `_check_update_types`, `_check_text`, `_log_call` — untouched by this change (one constant swapped).
  Not refactored here: outside the task's scope and lines; candidate for a router-tidy refactor issue.
- SonarQube diag skipped — the MCP exposes no analysis tool in this session.
- `kb/architecture.md`: the LLD `kb/ additions` block lists four entries (AC says three); all four added,
  since the update/delete entries from REC-9/REC-11 were never written.
- Evaluator warning: Story 1.3 AC5 retry-once-before-failing is not implemented; LLD §3.4 defers retry and
  timeout policy to E4.1's real providers. Track under E4.1.
- Approach-rationale "LLD deviations: none planned" is stale — three deviations are listed in the PR #135
  body (log event name, `_open_store` `dims` arg, four kb entries). Reconcile at lld-sync.
- pr-review Step 5 cost query reported REC-13's session (shared prom tag with the parallel teammate); the
  checkpoint rows are the reliable cost record for REC-12.
- `tag-session.py` wrote REC-13's title into this transcript (file lookup, not `CLAUDE_CODE_SESSION_ID`);
  the Prometheus tag (92b0970f → REC-12) is correct.
- `update-coverage-manifest.py --verify-anchors` reports every `coverage-e3.yaml` anchor as "file not found"
  (path resolution, pre-existing for REC-9/10/11 entries too); anchors exist in the LLD.

## Work completed

- [PR #135](https://github.com/mironyx/recall/pull/135): `ErrorCode` registry, `EmbeddingError`, `guarded_embed`.
- Source: `src/recall/errors.py`, `embeddings/provider.py`, `server.py`, `tool_router.py`.
- Tests: `tests/test_errors.py` (31 new); `tests/conftest.py` gains `_open_store`, `failing_embedding_store`.
- `kb/architecture.md`: four E3 entries; suite 460/460, CI green.

## Decisions made

- Provider failure is wrapped at the embed seam only, so search inherits `embedding_failed` with no router code.
- Envelope test fixtures bundled into `_EnvelopeSources` to clear the CodeScene arg-count smell.

## Review feedback addressed

- None — [pr-review](https://github.com/mironyx/recall/pull/135#issuecomment-7113408890) returned 0 findings.

## LLD Sync report

## LLD Sync — Issue REC-12: E3.3a: Error vocabulary — ErrorCode registry and embedding_failed

### Corrections (spec was wrong)

- `guarded_embed` log event: `log.exception("embedding_failed")` → `"embedding_provider_failed"` with
  `provider=` — the literal fails the LLD's own invariant-1 grep. Implementation note added in Part B.
- `conftest._open_store(dsn, embed)` → `_open_store(dsn, embed, dims)` so both store fixtures share `_embedding_dims()`.

### Additions (not in spec)

- `_RecordingProvider` in conftest: `store` wraps it with `guarded_embed` so `embed_calls` still records batches.
- `kb/architecture.md`: all four LLD kb entries (update/delete entries from REC-9/REC-11 were never written).

### Omissions (in spec but not built)

- None. Embed retry/timeout is left to E4.1 by the LLD itself.

### Confirmations (notable)

- `ErrorCode(StrEnum)` with `RecallError.error: str` — wire strings unchanged, no serialisation changes.
- Search embeds through the same seam, so `embedding_failed` covers save, update and search without per-tool code.

### LLD updated

File: docs/design/v2/lld-e3-update-delete-errors.md §3.4 Part B and kb/ additions heading
Version: Revised row extended (REC-12: §3.4); `coverage-e3.yaml` REQ-story-43 → `Revised`, files populated

## Cost retrospective

| Bucket | Cost |
|--------|------|
| 3c → 5 (design, test-author, implement) | $1.51 |
| 5 → 8 (diag, evaluator, PR) | $1.06 |
| 8 → 9 (review) | $0.67 |
| PR creation → final (incl. feature-end) | $3.22 → $4.73 |

- Green on attempt 1, no review fixes; the largest bucket was test-author (~$1.06), proportionate for 31 tests.
- Feature-end overhead (~$0.74) is mostly lld-sync and session log; no rework.

## Next steps

- E4.1: retry-once and timeout policy for real embedding providers (Story 1.3 AC5).
- Router tidy refactor: `_parse_search_params`, `_check_update_types` complexity (CodeScene 8.03).
- Fix `update-coverage-manifest.py --verify-anchors` path resolution for `v2/…` manifest paths.
