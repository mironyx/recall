# Architecture

## Boundary rule

`src/recall/db/` must have zero imports from `src/recall/server.py` or any MCP transport code. Storage layer is a leaf — it depends on nothing in the application.

## API composition pattern

Single-container MCP server. `src/recall/server.py` is the composition root: it wires Auth → Tool Router → Memory Service → Embedder → Postgres. No DI framework — manual constructor injection at startup.

## Scope invariant (ADR-0001, ADR-0002)

Namespace is `(scope, project_id)`. `scope` is `"global"` or `"project"`. The CHECK constraint on `store` enforces `prefix = 'global._'` or `prefix LIKE 'project.%' AND prefix != 'project._'`. Never store project-specific data under `scope=global`.

## Migration strategy (ADR-0013)

Schema DDL runs in-app via `ensure_schema()`, not Alembic. Migrations are idempotent SQL files under `src/recall/migrations/` applied in order. The `AsyncPostgresStore.setup()` handles LangGraph-managed tables; recall-owned DDL uses raw `psycopg.AsyncConnection`.

## Tool budget

Maximum 6 MCP tools. Tool design is prompt design — each tool must be broad enough to cover a category of memory operations. Adding a tool requires updating the tool table in requirements.

## Test strategy (ADR-0012)

Integration tests hit real Postgres via testcontainers. Never mock the database. Unit tests for pure logic only; any code touching storage goes through integration tests.
