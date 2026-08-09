# Session log — RECALL-89

## Approach rationale
- **Issue:** #89
- **Approach chosen:** Thin StorageAdapter wrapper over AsyncPostgresStore per LLD §E1.4 — build (scope, project_id) namespace, enforce scope invariant, delegate aput/aget. Flat MemoryRecord/MemoryResponse Pydantic models (ADR-0001).
- **LLD deviations:** none
- **Pressure:** standard — ~80 src lines across 2 source files, 1 test file

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T15:33:24Z | unavailable | unavailable | pressure: standard |
| 4bF  | 2026-08-09T15:37:14Z | unavailable | unavailable | test-author complete |
| 4dF  | 2026-08-09T15:40:04Z | unavailable | unavailable | implementation complete |
| 5    | 2026-08-09T15:41:50Z | unavailable | unavailable | green on attempt 2 |
| 6    | 2026-08-09T15:42:53Z | unavailable | unavailable | diag pass |
| 6b   | 2026-08-09T15:46:47Z | unavailable | unavailable | evaluator: PASS |
| 8    | 2026-08-09T15:47:21Z | unavailable | unavailable | [PR #114](https://github.com/mironyx/recall/pull/114) |
| 9    | 2026-08-09T15:51:40Z | unavailable | unavailable | review clean |
| 10   | 2026-08-09T15:53:51Z | $12.25 | 337479/131796/14533504 | report done — PR #114, CI red on pre-existing main errors |

## Work completed

- `src/recall/storage_adapter.py` — `StorageAdapter` thin wrapper: `put()`/`get()` build the `(scope, project_id)` namespace and delegate to `store.aput`/`store.aget`; scope invariant enforced on both paths as defence-in-depth (`ValidationError`); three-state `index` argument forwarded verbatim.
- `src/recall/models.py` — `MemoryRecord` (10 flat fields, ADR-0001) and `MemoryResponse` (`id` first).
- `tests/test_storage_adapter.py` — 25 tests (integration + unit): round trip, namespace construction via raw-store reads, invariant both directions, cross-project isolation, index forwarding incl. `index=False` (no vector row), model defaults/required/free-form kind.
- `tests/conftest.py` — `store` fixture resolves embedder dims to match `ensure_schema` (`RECALL_EMBEDDING_DIMS`, default 1536); fixes "expected 1536 dimensions, not 384" for index-enabled `aput` (first tests in repo history to embed through the store).
- PR: https://github.com/mironyx/recall/pull/114

## Decisions made

- Thin-wrapper approach per LLD §E1.4 — no deviations in the adapter itself; the LLD was accurate for `storage_adapter.py` and `models.py` (built as specified).
- `validate_dim` wiring deferred: LLD placed the call site in E1.4 "store creation", but E1.4 has no store-creation site (adapter wraps an injected store). Re-attributed to E1.6 (#91) via `TODO(#91)` in `provider.py`; LLD + kb corrected by lld-sync.
- Index-forwarding tests assert real vector-row counts via psycopg against `store_vectors` — keeps the "never mock the database" rule.

## Review feedback addressed

- No blockers from the two-agent review (Quality + Design Conformance).
- Warning — conftest/schema dim-resolution duplication: documented with `TODO(#89)` in `conftest.py`, deferred (failures are loud — dim mismatch at `aput`).
- Warning — `validate_dim` attribution: corrected to #91 (TODO + PR body Design deviations + lld-sync).
- Own markdownlint error (MD058 in this session log) fixed pre-review; remaining CI failures are pre-existing on main (20× MD033 in `lld-e1-one-memory-e2e.md`, MD028 in `lld-e06-health-logging.md`, MD034 in session-1 log) — outside this PR's file set.

## LLD Sync report

## LLD Sync — Issue #89: Storage adapter — put/get with namespace construction

### Corrections (spec was wrong)
- **validate_dim call-site attribution (LLD §E1.3):** the spec said the startup call site "lands in E1.4 (store creation, issue #89)" → actually E1.4's `StorageAdapter` wraps an *injected* `AsyncPostgresStore` and has no store-creation site; store creation lives at the composition root (E1.6, issue #91). Note rewritten with an implementation-note callout; the same stale E1.4 reference in `kb/architecture.md` was corrected.

### Additions (not in spec)
- **`validate_dim` in the provider.py code block:** the LLD listed the function in Key details and the decomposition table but never showed it in the code block — added, making the section faithful to the module.
- **`StorageAdapter` in `kb/architecture.md`:** new reusable component catalogued under API composition pattern (bar: future memory operations must route through it, not the raw store).

### Omissions (in spec but not built)
- None — every §E1.4 and §E1-models item shipped.

### Confirmations (notable)
- `StorageAdapter` (`put`/`get`/`_build_namespace`, `GLOBAL_SENTINEL`, three-state `index` signature, exact `ValidationError` messages) built as specified.
- `MemoryRecord` (10 flat fields, ADR-0001) and `MemoryResponse` (id first) built as specified — the model IS the stored shape.

### LLD updated
File: docs/design/v2/lld-e1-one-memory-e2e.md §E1.3 (provider) + Document Control row
kb/architecture.md — call-site correction + StorageAdapter entry
Version: n/a (doc uses dated Revised rows; one appended)

## Cost retrospective

- **Summary:** $8.12 at PR creation (PR body Usage) → $13.92 final cumulative (`ai-cost-final` label); ~$5.8 post-PR (review fixes, CI re-runs, lld-sync, feature-end). Checkpoint table rows 3c–10 above.
- **Drivers:** (1) first index-enabled integration tests exposed a real fixture gap (stub embedder dim 384 vs schema dim 1536) — one fix cycle in conftest, sound fix verified by evaluator; (2) two review warnings → TODO documentation, force-push, CI re-run; (3) pre-existing main CI breakage (markdownlint) consumed repeated verification cycles.
- **Improvements:** promote `_DEFAULT_DIMS`/dim resolution to a shared helper (`TODO(#89)` in conftest); fix main's markdownlint debt in a dedicated cleanup PR so CI stops failing for every feature; keep PRs small enough that review warnings are cheap to absorb.

## Next steps

- E1.5 (#90): MemoryService — save + get_by_id with reverse index (namespace `("_index", "_")`, `index=False`).
- E1.6 (#91): composition root — store creation + `validate_dim` wiring, tool router + MCP wiring.
- Fix pre-existing markdownlint errors on main (`lld-e1-one-memory-e2e.md` MD033, `lld-e06-health-logging.md` MD028, session-1 MD034) — unblocks CI for all future PRs.
