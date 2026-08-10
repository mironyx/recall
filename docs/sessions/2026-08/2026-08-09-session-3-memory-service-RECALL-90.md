# Session log — RECALL-90

## Approach rationale
- **Issue:** #90
- **Approach chosen (revised — ADR-0015):** save() delegates the memory record to
  StorageAdapter (index=["content"]) in a **single write**; get_by_id(scope, project_id,
  id) is a **direct namespaced read** that raises NotFoundError on any miss and returns
  {"id", ...value} (MemoryResponse shape, Story 2.4 AC). The reverse-index design from the
  original LLD was **killed during PR review per user decision and ADR-0015**: id-only
  operations have no user-level use case — search results already carry scope — and the
  index turned save() into two non-atomic writes while widening the storage namespace
  beyond (scope, project_id) (ADR-0002) and requiring CHECK-constraint surgery.
  memory_get/memory_update/memory_delete are now scope-explicit.
- **LLD deviations:** the LLD §E1.5 design note ("memory_get ID resolution" — reverse index
  in ("_index", "_")) is superseded by ADR-0015; the LLD, requirements tool table + stories
  1.4/1.5/2.4, and implementation plan were updated in sync (get_by_id signature, design
  note, MEMORY_GET_SCHEMA, tasks table, BDD docstrings, sequence diagram, exit criterion).
  NotFoundError added to errors.py per LLD §E1-errors (RecallError shape). Schema CHECK
  constraint reverts to origin/main — no widening, no DROP+ADD.
- **Pressure:** standard — ~100 src lines across 2 source files (memory_service.py, errors.py), 1 test file.

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T17:35:00Z | $1.0450 | 130,261 in / 3,189 out / 627,840 cache-read | pressure: standard |
| 4bF  | 2026-08-09T17:41:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | test-author complete |
| 4dF  | 2026-08-09T17:43:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | implementation complete; schema fix (constraint) landed |
| 5    | 2026-08-09T17:52:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | green on attempt 3 (attempt 1: fixture-order flake — fixed via dedicated schema-test DB; attempt 2: EDF starter pyright mismatch — ran project mypy/ruff) |
| 6    | 2026-08-09T17:56:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | diag pass — CodeScene: memory_service 9.68 (LLD-pinned 8-arg save signature, documented), test_memory_service 10 (unused fixture param removed), test_schema 9.38 (pre-existing dup, documented); SonarQube N/A (no project for recall) |
| 6b   | 2026-08-09T18:01:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | evaluator: PASS WITH WARNINGS — 1 adversarial test added (free-form kind), 0 failed; 3 silent risks noted (non-atomic save, empty project_id layering, CHECK DROP+ADD scan) |
| 8    | 2026-08-09T18:08:00Z | $5.6494 | 206,193 in / 73,796 out / 5,547,008 cache-read | [PR #115](https://github.com/mironyx/recall/pull/115) |
| 9    | 2026-08-09T18:21:00Z | $14.2821 | 433,542 in / 191,027 out / 14,677,376 cache-read | pr-review: 0 blockers, 3 warns (schema namespace widening without ADR; raw-store access LLD-prescribed; CHECK DROP+ADD scan — all deferred, TODO #90 + PR body) |
| 10   | 2026-08-09T18:22:00Z | $14.2821 | 433,542 in / 191,027 out / 14,677,376 cache-read | CI reconcile: quality job red on 24 markdownlint errors — 23 pre-existing on main (5 consecutive failing main runs), 1 introduced here (MD058 session log) — fixed + verified locally; branch protection off, merge not blocked |
| 10b  | 2026-08-10T09:45:00Z | $19.6986 | 548,065 in / 266,383 out / 20,597,376 cache-read | design pivot (user): reverse index killed — ADR-0015 written; LLD/requirements/plan updated; service simplified (single-write save, scope-explicit get); schema CHECK reverted to origin/main; tests reworked (14 → 14, 2 reverse-index tests removed) |

## Work completed

- **Issue #90 (E1.5): Memory Service — save + get_by_id**, PR [#115](https://github.com/mironyx/recall/pull/115).
- Implemented `src/recall/memory_service.py` (new, ~100 lines): `save()` builds the flat
  10-field value (ADR-0001), delegates to `StorageAdapter.put(scope, project_id, key,
  value, index=["content"])` in a **single write**, returns the generated UUIDv4;
  `get_by_id(scope, project_id, id)` is a **direct namespaced read** raising
  `NotFoundError` on any miss (ADR-0015).
- Added `NotFoundError` (structured `{error, hint}` shape) to `src/recall/errors.py`
  per LLD §E1-errors.
- Tests: `tests/test_memory_service.py` (14 integration tests — save flat value,
  timestamps, tags/metadata defaults, free-form kind, content embedding + semantic
  search, global round-trip, scope-invariant violations, embedding-failure persists
  nothing, get-by-id full record + not-found); `tests/test_schema.py` scope-constraint
  suite retained. Full suite 172/172 green, mypy strict + ruff clean.
- Design pivot (user decision, mid-review): reverse index `("_index", "_")` killed —
  ADR-0015 written; LLD/requirements/plan updated in sync; schema CHECK constraint
  reverted byte-identical to origin/main.
- Commit `705cbd6` (9 files, +175/−167) pushed; PR title updated to
  "E1.5: Memory Service — save + get_by_id, scope-explicit (ADR-0015)".

## Decisions made

- **Scope-explicit id operations (ADR-0015).** `memory_get`/`update`/`delete` take
  `(scope, project_id, id)`; no reverse index. Rationale: no user-level id-only use
  case (search results carry scope); single-write atomicity on save; namespace stays
  exactly `(scope, project_id)` per ADR-0002; no CHECK-constraint surgery.
- **Single-write save.** `index=["content"]` on the one `put` — if embedding fails or
  the invariant is violated, nothing is persisted (Story 1.3 AC4).
- **LLD-pinned 8-arg `save()` signature** kept as designed (positional scope/project_id/
  user_id/kind/title/content + optional tags/metadata) — simplifies the later router
  call; flagged but not changed (CodeScene 9.68).
- **Empty `project_id` validation deferred to E1.6 (#91)** — `validate_project_id_format`
  call-site lands with the tool router; `StorageAdapter` invariant handles `'_'` cases
  now (TODO in `storage_adapter.py`).

## Review feedback addressed

- `edf:pr-review` (Step 9): **0 blockers, 3 warns** — (1) storage-namespace widening
  without an ADR, (2) raw-store access LLD-prescribed, (3) CHECK DROP+ADD scan. All
  three were resolved by the ADR-0015 pivot: the namespace no longer widens, the raw
  `aput` goes away (single namespaced `put`), and the CHECK constraint reverts to
  origin/main with no DROP+ADD. Documented in PR comment
  [issuecomment-5234456813](https://github.com/mironyx/recall/pull/115#issuecomment-5234456813).
- Evaluator (Step 6b): PASS WITH WARNINGS — 1 adversarial test added (free-form kind);
  3 silent risks (non-atomic save, empty project_id layering, CHECK DROP+ADD scan) all
  closed by the pivot.
- CI: quality job red on 24 markdownlint errors — 23 pre-existing on main (lld-e1
  anchors, load-bearing — not converted), 1 introduced (session-log MD058) — fixed
  and verified locally; zero errors from changed files in run 31342541518.

## LLD Sync report

## LLD Sync — Issue #90: E1.5 Memory Service — save + get_by_id

### Corrections (spec was wrong)
- **Reverse index for id resolution — dropped per ADR-0015:** the LLD §E1.5 design note prescribed an id-only `memory_get` contract resolved via a reverse index in `("_index", "_")`, which turned save() into two non-atomic writes. Built instead: scope-explicit `get_by_id(scope, project_id, id)` as a direct namespaced read, `save()` as a single write with `index=["content"]`. Why: there is no user-level use case for id-only operations (search results already carry the scope); the index made save() non-atomic, widened the storage namespace beyond `(scope, project_id)` (ADR-0002), and required CHECK-constraint surgery. The design note was rewritten during implementation; this sync adds the Document Control row and confirms no stale `("_index", "_")` references remain.
- **Code-block drift — synced to shipped code:** the §E1.5 code block used `datetime.timezone` (`from datetime import datetime, timezone`); shipped code uses the Python 3.11+ `UTC` singleton. `get_by_id` in the block also lacked the Returns docstring (MemoryResponse shape, Story 2.4 AC1) that shipped code carries. Class docstring wording aligned ("direct get-by-id").

### Additions (not in spec)
- None beyond what the implementation already recorded — `NotFoundError` (structured `{error, hint}` shape) was LLD-specified in §E1-errors and built as specified.

### Omissions (in spec but not built)
- None. No `## Pending changes — Rev N` blocks exist in this LLD; nothing was deferred or descoped from §E1.5.

### Confirmations (notable)
- Flat 10-field value at root (ADR-0001) built exactly as specified — the model IS the stored shape.
- `index=["content"]` on the single write; embedding handled by `AsyncPostgresStore` via `PostgresIndexConfig`.
- Scope invariant enforced by `StorageAdapter` before any write (ValidationError on violation).
- `get_by_id` returns `{"id": ..., **value}` satisfying the `MemoryResponse` shape.

### LLD updated
File: `docs/design/v2/lld-e1-one-memory-e2e.md` §B — `src/recall/memory_service.py` (anchor `LLD-e1-memory-service`)
Version: 0.1 → 0.2 (Document Control row added; Status already `Revised`)
Manifest: `docs/design/v2/coverage-e1.yaml` — `REQ-story-11-store-a-memory` and `REQ-story-24-retrieve-a-memory-by-id` flipped `Approved` → `Revised` (anchors verified OK)
kb: no changes — `MemoryService`/`NotFoundError` are feature units, not cross-feature helpers catalogued in `kb/architecture.md`

## Cost retrospective

- **Cost summary:** PR-creation cost (Step 8 checkpoint) $14.2821 → final $24.2957
  (629,649 in / 305,949 out / 26,997,504 cache-read). Post-PR spend ≈ $10.01, in two
  buckets: the design pivot (user decision) ≈ $5.42 — ADR-0015 writing, doc sync (LLD 9
  edits, requirements 5, plan 2), service simplification, schema revert, test rework
  (14 → 14), full re-verification, PR/issue body updates; and the feature-end session
  ≈ $4.60 (lld-sync, session log, cost query, merge + cleanup), which is cost-registered
  under the same RECALL-90 ID.
- **Cost drivers:** the 8 → 10b gap ($14.28 → $19.70) is the review-feedback → pivot
  cycle: 3 pr-review warns became the catalyst for re-examining the reverse-index design,
  and the user correctly judged it overengineering. Cheaper than it could have been:
  the pivot reused the existing tests (14 → 14) rather than rewriting the suite.
  The 10b → final gap is the feature-end wrap-up itself — a fixed overhead of ~$4.60.
- **Improvement actions:**
  - Reverse-index-style "clever" storage tricks should be challenged at LLD review, not
    at PR review — a namespace-widening, non-atomic write pattern was visible in the
    design note before implementation. Add "single write / namespace purity (ADR-0002)"
    to the LLD self-critique checklist.
  - ADR-0015's pattern — "operations are scope-explicit because search results carry
    scope" — should be reused in E1.6 router design and any future id-exposed tool.

## Next steps

- Merge PR #115 (squash), then E1.6 (#91): Tool Router + MCP wiring — `memory_save` /
  `memory_get` handlers, MEMORY_GET_SCHEMA gains scope/project_id per ADR-0015, empty
  `project_id` validation call-site, NotFoundError → structured MCP error response
  (Story 4.3).
- E1.6 also owns: `validate_dim` wiring at store creation, RECALL_AUTH_FILE wiring.
- Board: E1.5 → Done; next open task via `gh issue list --label kind:task --state open`.
