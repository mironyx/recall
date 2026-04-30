# Session Log — 2026-04-30 — Schema Setup (E0.4)

## Issue / PR
- Issue: #76 — E0.4: Migration runner and initial schema
- PR: #83 — feat: idempotent schema setup replacing migration runner (#76)
- Parent epic: #72 — E0: Phase 0: Foundation

## Work completed

### Core feature (commit `9896ea9`)
Replaced the over-engineered migration runner (PR #82) with a ~65-line `ensure_schema()` function
using idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `DO $$ ... EXCEPTION WHEN duplicate_object`).

- `src/recall/db/schema.py` — new `ensure_schema()`: calls `AsyncPostgresStore.setup()` to create
  `store` and `store_vectors`, then adds the scope CHECK constraint via an idempotent PL/pgSQL block.
- `src/recall/cli.py` — wires `recall db migrate` and auto-migrate on `recall serve` (controlled by
  `RECALL_DB_MIGRATE_ON_STARTUP`, default true).
- `docs/adr/0013-in-app-ddl-migrations-no-alembic.md` — rewritten to document the simplified
  idempotent DDL approach (no Alembic, no migration framework, no `schema_migrations` table).
- `docs/design/lld-e04-migration-runner.md` — simplified LLD aligned to `ensure_schema`.
- `tests/test_schema.py` — integration tests: schema creation, idempotency, constraints, CLI.
- `tests/test_cli.py` — unit test for missing `DATABASE_URL`.
- `tests/evaluation/test_e01_scaffolding_eval.py` — fixed Windows `uv` PATH resolution.
- `tests/evaluation/test_e06_health_logging_eval.py` — replaced `grep` subprocess with Python
  `rglob` to fix Windows compatibility.
- `README.md` — local setup and test commands.

### Project registry deferral (commits `4bb8cec`, `1cbabe0`)
ADR-0014 created: dropped the `projects` table from `ensure_schema`. Projects are now inferred
from `SELECT DISTINCT prefix FROM store WHERE prefix LIKE 'project.%'`. No pre-validation of
`project_id` — any well-formed ID is accepted on first write.

## Decisions made

1. **Idempotent DDL over migration runner** — the original PR #82 implemented a full `apply_pending`
   runner with a `schema_migrations` ledger table, locking, and ordered SQL files. For Phase 0 with
   two tables and one constraint, this was excess machinery. Replaced with a direct `ensure_schema()`
   function that is safe to call repeatedly.

2. **ADR-0014: defer project registry** — ADR-0009 specified a `projects` allowlist table. On
   review, it creates friction (operators must register before agents can write) for zero real gain
   in the Phase 0 self-hosted target. The scope CHECK constraint on `store.prefix` still enforces
   namespace shape; phantom projects are visible and deletable. ADR-0014 supersedes ADR-0009.

3. **Windows test fixes** — eval tests used `grep` and `uv` as subprocesses, which fail on Windows
   without PATH adjustment. Fixed by using Python stdlib (`rglob`, `shutil.which`).

## Review feedback addressed

No reviewer comments — PR had no formal reviews (repo does not require them).

## LLD sync

lld-sync run post-implementation. Key sync notes:
- Removed `_PROJECTS_TABLE_SQL` and projects table DDL step from LLD spec (ADR-0014 deferral).
- Removed `TestProjectsTable` BDD spec class; added `test_constraint_exists` test.
- Updated startup mermaid sequence: removed projects table step.
- Bumped LLD version 0.1 → 0.2, status Draft → Revised.

## Cost retrospective

Session tagging was not run for this feature (`query-feature-cost.py` found no data for RECALL-76).
Cost data unavailable for retrospective.

**Likely cost drivers (estimated):**
- Prior failed attempt (PR #82) before the simplified approach was chosen — represents wasted
  design-and-implement cycles. Mitigation: validate complexity of spec against LOC before
  implementing; prefer the simplest approach that satisfies acceptance criteria.
- ADR-0014 deferral required a second implementation pass after the first commit. Mitigation:
  review ADR backlog and open design issues before starting implementation.

## Next steps

- Issue #76 complete; epic #72 checklist updated.
- Integration tests (requiring Docker + pgvector) not run in CI — marked with a note in PR test
  plan. Run locally with `uv run pytest -m integration` once Docker is available.
- Consider Epic 1 (memory tools) as the next phase — ADR-0014 noted that the `global`-as-project
  insight should be revisited when designing the memory tool layer.
