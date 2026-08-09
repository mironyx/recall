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
