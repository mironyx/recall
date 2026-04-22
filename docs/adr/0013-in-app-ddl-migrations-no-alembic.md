# 0013. Schema setup: idempotent DDL on startup, no migration framework

**Date:** 2026-04-10 (revised 2026-04-22)
**Status:** Accepted (supersedes original ADR-0013)
**Deciders:** LS / Claude

## Context

Recall has a small, well-bounded schema: the `store` and `store_vectors` tables owned by `AsyncPostgresStore` (shape fixed by ADR-0001 and ADR-0002), and the `projects` table from ADR-0009. That is three tables total, two of which are created by upstream code we do not control.

The original ADR-0013 chose an in-app DDL runner: numbered SQL files, a `schema_migrations` ledger table, advisory locking, concurrency retry loops, and file-discovery machinery. When implemented, this produced ~140 lines of runner code, ~580 lines of tests, and a maintenance surface disproportionate to the problem: applying two idempotent DDL statements on top of `AsyncPostgresStore.setup()`.

Additional context: we are evaluating Supabase as a deployment target (container for small teams, cloud for larger installations). Supabase is Postgres + pgvector and is compatible with `AsyncPostgresStore`, but introducing our own migration framework makes a future Supabase migration harder — it is one more thing to reconcile or rip out.

The schema will evolve slowly. When it does, the right response is to evaluate what tooling is needed at that point — not to pre-build a framework for a future that may never arrive.

## Decision

Recall uses **idempotent DDL executed on startup** instead of a migration framework. The shape is minimal:

- A single async function `ensure_schema(conn_string)` that:
  1. Calls `AsyncPostgresStore.setup()` — creates `store`, `store_vectors`, and their internal migration ledgers. This is the upstream contract and is non-negotiable.
  2. Adds the scope CHECK constraint on the `store` table (ADR-0001, ADR-0002) using a `DO $$ ... EXCEPTION WHEN duplicate_object` block for idempotency.
  3. Creates the `projects` table with `CREATE TABLE IF NOT EXISTS` (ADR-0009).
- `recall db migrate` calls `ensure_schema`. Name kept for operator familiarity.
- `recall serve` calls `ensure_schema` on startup unless `RECALL_DB_MIGRATE_ON_STARTUP=false`.
- The integration test fixture calls the same `ensure_schema` function.
- There is **no `schema_migrations` table**, no advisory locks, no file discovery, no numbered SQL files.

When a schema change is needed in the future (new column, new index), we will evaluate at that point whether to:
- Extend `ensure_schema` with another idempotent statement.
- Adopt a lightweight migration tool (dbmate, Supabase migrations, etc.).
- Write a one-shot migration script.

## Consequences

**Positive.**
- ~30 lines of production code instead of ~140. ~100 lines of tests instead of ~580.
- One function, no framework. Nothing to maintain.
- Supabase-compatible: if we move to Supabase, we drop `ensure_schema` and manage DDL in Supabase's dashboard/migrations. No framework to rip out.
- The test fixture, the CLI, and the server startup all hit the same function.
- Reviewers can read the DDL inline — no indirection through SQL files.

**Negative / accepted trade-offs.**
- **No migration ordering or history.** Accepted. With 2 idempotent statements there is nothing to order or track.
- **No down-migrations.** Same as the original ADR — restore from backup.
- **If we accumulate many schema changes, idempotent DDL stops scaling.** Accepted. We will adopt proper tooling when that happens, not before.
- **`ensure_schema` re-runs all DDL on every startup.** Acceptable. The statements are `IF NOT EXISTS` / `EXCEPTION WHEN duplicate_object` — they are no-ops on an already-correct schema. The cost is negligible.

**Not chosen, and why.**
- **In-app DDL runner (original ADR-0013).** Over-engineered for the current schema size. Maintenance cost exceeded the cost of the problem it solved.
- **Alembic.** Still wrong scale. Same reasoning as the original ADR.
- **dbmate / yoyo-migrations.** External dependency for a problem that is currently ~30 lines of Python.

## References

- REQUIREMENTS.md — S6.2 (database migrations story)
- docs/design/v2-design.md — Migrations component
- ADR-0001 (flat value schema): the CHECK constraint enforces this
- ADR-0002 (namespace shape): the scope invariant
- ADR-0009 (projects table): created by `ensure_schema`
- ADR-0012 (test strategy): integration test fixture calls `ensure_schema`
