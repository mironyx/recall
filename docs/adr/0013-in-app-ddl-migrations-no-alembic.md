# 0013. Schema migrations: in-app DDL runner for v1, no Alembic

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

Recall has a single Postgres database and a small, well-bounded schema: the memories table backing `AsyncPostgresStore` (shape fixed by ADR-0001 and ADR-0002), the `projects` table from ADR-0009, and whatever indexes those need. The schema will evolve — pgvector index types change, new columns get added for compaction metadata, the access-time column for the prune-unread pass (S6.7) does not exist yet — but it will not evolve fast, and it will never have a hundred tables.

The Migrations component (HLD Level 2) needs a concrete mechanism. The two realistic choices are:

1. **A grown-up migration framework** — Alembic is the obvious one in Python.
2. **An in-app DDL runner** — a directory of numbered SQL files, a `schema_migrations` table that records which have been applied, and a small piece of Python that walks the directory and applies anything new inside a single transaction.

Alembic is the right answer for a service with thirty tables, fifteen contributors, and a long migration history. Recall is none of those things. The cost of Alembic is real: an extra dependency, an `alembic.ini`, an `env.py`, autogeneration that frequently produces wrong migrations against pgvector columns, a separate `alembic upgrade head` step that has to be wired into every entrypoint and every test fixture, and a mental model contributors need to learn before they can add a column.

S5.5 says migrations "run automatically on startup behind a flag, or via an explicit CLI command". S1.9 mandates `recall db migrate`. The HLD's Migrations component is built around a single component owning DDL — there is no separate "migrations service".

We need to decide before any code lands, because the test fixture (ADR-0012) needs to call into the migration runner on every container boot, and that integration is much simpler if the runner is a single Python function we own.

## Decision

Recall v1 ships its own **in-app DDL runner**. The shape is deliberately small:

- Migrations live in `src/recall/migrations/` as numbered SQL files: `0001_initial.sql`, `0002_projects.sql`, …. Each file is a single SQL script that runs inside one transaction. Filename ordering is the apply order.
- A `schema_migrations(version text primary key, applied_at timestamptz not null default now())` table records which migrations have been applied. The runner creates this table itself if it does not exist.
- The runner is a pure Python function: `apply_pending(connection) -> list[str]`. It locks the `schema_migrations` table (`LOCK TABLE ... IN ACCESS EXCLUSIVE MODE`), reads applied versions, walks the migrations directory, applies anything not yet applied in filename order inside a single transaction per file, and inserts the version row on success. On failure, the transaction rolls back and the runner raises — partial application is impossible.
- `recall db migrate` is a thin CLI wrapper around `apply_pending`.
- `recall serve` runs `apply_pending` automatically on startup unless `RECALL_DB_MIGRATE_ON_STARTUP=false`. The default is **on**, because the audience is small teams who deploy by `docker compose up` and would rather have migrations "just happen".
- The integration test fixture (ADR-0012) calls the same `apply_pending` against the testcontainers Postgres before any test runs. There is exactly one migration code path.
- Down-migrations are **not** supported in v1. Rolling back means restoring from backup. We can revisit if real demand appears.

`AsyncPostgresStore`'s own `setup()` call (which creates its internal tables) is invoked from within the relevant migration file, not as a parallel mechanism. There is one place schema changes happen.

## Consequences

**Positive.**
- One mechanism, ~50 lines of Python, no external dependency.
- The test fixture, the CLI, and the server startup all hit the same function — there is no "ran in tests but not in prod" failure mode.
- Reviewers can read a migration as plain SQL, no autogen guessing.
- pgvector DDL (`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`) is written as the operator wants it, not as Alembic infers it.
- "Add a column" is: write a SQL file, commit, done.

**Negative / accepted trade-offs.**
- **No down-migrations.** Accepted. Down-migrations are usually wrong anyway; restore-from-backup is the honest recovery path for anything that touches data.
- **No autogeneration from SQLAlchemy models.** Recall does not use SQLAlchemy. There is nothing to autogenerate from.
- **No schema diffing tooling.** If a future contributor wants `migra` or `pgsanity`, they can run it locally; we do not bake it into CI in v1.
- **The in-app runner is one more thing we own.** Real, but small enough that the maintenance cost is dwarfed by the cost of Alembic ceremony.
- **`MIGRATE_ON_STARTUP=true` by default** means a misbehaving migration takes the whole startup down. That is the right failure mode — the alternative is silently running on a wrong schema. The flag exists so operators with formal change management can disable it.

**Not chosen, and why.**
- **Alembic.** Right tool, wrong scale. The ceremony tax is paid on every contributor onboarding and every test fixture invocation, in exchange for features (autogen, branching, down-migrations) Recall does not use.
- **`yoyo-migrations` or `dbmate`.** Smaller than Alembic, but still an external dependency for a problem that is genuinely 50 lines of Python.
- **Hand-applied DDL via runbook.** Drift between environments by Tuesday.
- **Schema embedded in application startup with `CREATE TABLE IF NOT EXISTS`.** Works for the first version. Falls over the moment a column needs to be added to existing data.

## References

- REQUIREMENTS.md — S1.9, S5.5
- docs/design/v1-design.md — Migrations component; Operator CLI
- ADR-0001 (flat value schema): the shape the initial migration creates
- ADR-0002 (namespace shape): the index that initial migration must create
- ADR-0009 (projects table): the second migration file
- ADR-0012 (test strategy): the integration test fixture is the primary user of `apply_pending`
