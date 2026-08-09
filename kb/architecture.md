# Architecture

## Boundary rule

`src/recall/db/` must have zero imports from `src/recall/server.py` or any MCP transport code. Storage layer is a leaf — it depends on nothing in the application.

## API composition pattern

Single-container MCP server. `src/recall/server.py` is the composition root: it wires Auth → Tool Router → Memory Service → Embedder → Postgres. No DI framework — manual constructor injection at startup.

- `src/recall/validation.py` — `validate_project_id_format()` (pure function, ADR-0002/ADR-0014). Reuse it for any project_id format check; do not re-implement the `^[a-zA-Z0-9_-]{1,128}$` regex inline.
- `src/recall/storage_adapter.py` — `StorageAdapter` (thin wrapper over `AsyncPostgresStore`: builds the `(scope, project_id)` namespace, enforces the scope invariant, delegates `put`/`get`). Reuse it for any memory storage access; do not call the raw store directly.

## Scope invariant (ADR-0001, ADR-0002)

Namespace is `(scope, project_id)`. `scope` is `"global"` or `"project"`. The CHECK constraint on `store` enforces `prefix = 'global._'` or `prefix LIKE 'project.%' AND prefix != 'project._'`. Never store project-specific data under `scope=global`.

## Migration strategy (ADR-0013)

Schema DDL runs in-app via `ensure_schema()`, not Alembic. Migrations are idempotent SQL files under `src/recall/migrations/` applied in order. The `AsyncPostgresStore.setup()` handles LangGraph-managed tables; recall-owned DDL uses raw `psycopg.AsyncConnection`.

## Tool budget

Maximum 6 MCP tools. Tool design is prompt design — each tool must be broad enough to cover a category of memory operations. Adding a tool requires updating the tool table in requirements.

## Test strategy (ADR-0012)

Integration tests hit real Postgres via testcontainers. Never mock the database. Unit tests for pure logic only; any code touching storage goes through integration tests.

Deterministic test embeddings live in `src/recall/embeddings/stub.py`
(`StubEmbeddingsProvider`), wired into the `store` fixture's index config via
`PostgresIndexConfig(dims=..., embed=_embed)`. Reuse it for index-backed tests
instead of re-implementing a stub embedder.

The `EmbeddingsProvider` ABC and `validate_dim(provider, configured_dim)`
live in `src/recall/embeddings/provider.py` (ADR-0008) — the embedder contract
every provider implements (stub now, HTTP in E4). `validate_dim` is the
fail-fast EMBEDDINGS_DIM check; it is wired at store creation (E1.6, issue #91).
Reuse both when adding providers or index-backed wiring.
