# Session log — RECALL-90

## Approach rationale
- **Issue:** #90
- **Approach chosen:** Implement the LLD reverse-index design: save() delegates the memory
  record to StorageAdapter (index=["content"]), then writes a reverse-index entry mapping
  id → {scope, project_id} into the raw store's ("_index", "_") namespace with index=False.
  get_by_id() reads the index entry to resolve the namespace, fetches the record via the
  adapter, and raises NotFoundError on any miss. Returns {"id", ...value} to match the
  MemoryResponse shape (Story 2.4 AC).
- **LLD deviations:** None on design — but note two implementation points: (1) the LLD save()
  code block omits the reverse-index write that its own design note and the issue AC require;
  (2) the reverse index namespace ("_index", "_") is outside the adapter's (scope, project_id)
  domain, so the service accesses the adapter's wrapped raw store (`self._storage._store`)
  for index entries only — the adapter stays a thin domain wrapper per its LLD boundary.
  NotFoundError added to errors.py per LLD §E1-errors (RecallError shape).
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
