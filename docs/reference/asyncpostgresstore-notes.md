# AsyncPostgresStore — Distilled Reference

Last fetched: 2026-04-09

Scope: the LangGraph `AsyncPostgresStore` as it applies to Recall. Source is the upstream
repo; this file is a local crib sheet.

Upstream base path:
<https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/>

Primary files referenced:

- `base.py` — schema DDL, migrations, query builders, sync `PostgresStore`.
  <https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py>
- `aio.py` — `AsyncPostgresStore` (what we actually use).
  <https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/aio.py>

Line numbers below match the commit on `main` at the "last fetched" date. Re-check before
citing in an ADR.

## Schema (verbatim)

### `store` table — `base.py` lines ~61-72

```sql
CREATE TABLE IF NOT EXISTS store (
  prefix text NOT NULL,
  key text NOT NULL,
  value jsonb NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP WITH TIME ZONE,
  ttl_minutes INT,
  PRIMARY KEY (prefix, key)
);
```

- `prefix` is the dotted/encoded namespace tuple. For Recall that's
  `<scope>.<project_id>` (or equivalent encoding — exact delimiter is an implementation
  detail of LangGraph; do not assume it in queries).
- `value jsonb` is the entire memory payload. `kind`, tags, etc. live here.
- `expires_at` / `ttl_minutes` drive TTL sweeps (see below).

### `store_vectors` table — `base.py` lines ~140-151

```sql
CREATE TABLE IF NOT EXISTS store_vectors (
  prefix text NOT NULL,
  key text NOT NULL,
  field_name text NOT NULL,
  embedding vector(dims),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (prefix, key, field_name),
  FOREIGN KEY (prefix, key) REFERENCES store(prefix, key) ON DELETE CASCADE
);
```

- One row per `(memory, embedded field)`. If `index.fields=["text", "summary"]`, a single
  memory produces two embedding rows.
- `ON DELETE CASCADE` means deleting a `store` row frees its vectors; we don't have to
  clean up manually.
- `dims` is interpolated from `PostgresIndexConfig.dims` at `setup()` time — it is baked
  into the column type, so changing embedding model dims requires a migration.

### Indexes — `base.py`

- `store_prefix_idx` (line ~75): B-tree on `prefix` with text pattern ops — supports
  prefix / `LIKE` scans used by `list_namespaces`.
- `idx_store_expires_at` (line ~88): partial index on `expires_at WHERE expires_at IS NOT
  NULL` — TTL sweeper uses this.
- `store_vectors_embedding_idx` (line ~155): HNSW or IVFFlat ANN index depending on
  `ann_index_config.kind`.

### Migrations

`base.py` lines ~58-96 define the store migrations (initial table, prefix index, TTL
columns, TTL index). Lines ~98-176 define vector migrations (pgvector extension, vectors
table, ANN index). Version tracking lives in `store_migrations` and `vector_migrations`
meta-tables, advanced idempotently by `setup()`.

## API surface

### `AsyncPostgresStore.__init__` — `aio.py` lines ~138-165

```python
def __init__(
    self,
    conn: _ainternal.Conn,
    *,
    pipe: AsyncPipeline | None = None,
    deserializer: Callable[[bytes | orjson.Fragment], dict[str, Any]] | None = None,
    index: PostgresIndexConfig | None = None,
    ttl: TTLConfig | None = None,
) -> None:
```

### `from_conn_string` — `aio.py` lines ~177-225

```python
@classmethod
@asynccontextmanager
async def from_conn_string(
    cls,
    conn_string: str,
    *,
    pipeline: bool = False,
    pool_config: PoolConfig | None = None,
    index: PostgresIndexConfig | None = None,
    ttl: TTLConfig | None = None,
) -> AsyncIterator[AsyncPostgresStore]:
```

Use this as the async context manager in Recall's server startup. Pool config is
forwarded to psycopg; pipeline mode is an optional performance tweak.

### `setup()` — `aio.py` lines ~227-240

```python
async def setup(self) -> None: ...
```

Idempotent. Runs every pending migration on both `store_migrations` and
`vector_migrations`. Recall's `recall db migrate` CLI must call this.

### Core data ops

`AsyncPostgresStore` implements the `BaseStore` async contract. Canonical signatures
(see LangGraph `BaseStore` in
`libs/langgraph/langgraph/store/base.py`):

```python
async def aput(
    self,
    namespace: tuple[str, ...],
    key: str,
    value: dict[str, Any],
    index: list[str] | None | Literal[False] = None,
    *,
    ttl: float | None = None,  # minutes
) -> None: ...

async def aget(
    self,
    namespace: tuple[str, ...],
    key: str,
    *,
    refresh_ttl: bool | None = None,
) -> Item | None: ...

async def asearch(
    self,
    namespace_prefix: tuple[str, ...],
    *,
    query: str | None = None,
    filter: dict[str, Any] | None = None,
    limit: int = 10,
    offset: int = 0,
    refresh_ttl: bool | None = None,
) -> list[SearchItem]: ...

async def alist_namespaces(
    self,
    *,
    prefix: tuple[str, ...] | None = None,
    suffix: tuple[str, ...] | None = None,
    max_depth: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[str, ...]]: ...
```

- `namespace` is always a tuple. Recall uses exactly 2 segments: `(scope, project_id)`.
- `index=False` on `aput` explicitly skips embedding even if the store has an index
  configured — useful for structural memories we don't want in ANN results.
- `asearch` without a `query` falls back to a pure metadata/filter scan (no ANN).

### TTL

- `TTLConfig` (sync and async): `sweep_interval_minutes` (default 5),
  `default_ttl` (minutes), `refresh_on_read` (bool).
- Write path: `PUT` sets `expires_at = NOW() + (ttl_minutes || ' minutes')::interval`.
- Read path: if `refresh_ttl=True`, `aget`/`asearch` bump `expires_at` on hit.
- Sweep: `sweep_ttl()` (`aio.py` lines ~331-336) deletes where `expires_at < NOW()` and
  returns the row count.
- Background sweeper: `start_ttl_sweeper()` (lines ~338-376) and `stop_ttl_sweeper()`
  (lines ~378-411). Async task, cancellable. Recall should start this in server
  lifespan and stop it on shutdown.
- `__aenter__` / `__aexit__` at lines ~413-425 — wires up the sweeper if configured.

Source: `base.py` / `aio.py` as cited above.

## Filter operators

From `BasePostgresStore._get_filter_condition` (`base.py` lines ~734-746). Supported
MongoDB-style operators on `value jsonb`:

- `$eq`
- `$ne`
- `$gt`
- `$gte`
- `$lt`
- `$lte`

Plain scalar equality (e.g. `filter={"kind": "decision"}`) is sugar for `$eq`.

### Gotcha 1 — top-level keys only

The filter compiler walks only the first level of the `value` JSON. Nested paths
(`filter={"meta.kind": ...}`) are **not** translated into `jsonb_path_query` and will
silently match nothing. If you need to filter on a nested field, lift it to the top
level of the stored `value` at write time.

Implication for Recall: keep `kind`, `tags`, `scope`, `project_id`, `created_by`, etc.
as top-level keys in the stored memory JSON. Do not nest under `"meta": {...}`.

### Gotcha 2 — lexicographic comparison on stringified numbers

`$gt` / `$lt` are translated to direct JSONB operand comparisons. When the stored value
is a string that happens to contain digits (e.g. `"created_at": "2026-04-09"` vs
`"10"` vs `"9"`), Postgres compares them **lexicographically**, not numerically. This
bites in two ways:

1. Numeric fields stored as strings — `"9" > "10"` is `true`.
2. ISO-8601 timestamps are safe because lexicographic == chronological, but any other
   date/time format (e.g. `"M/D/YYYY"`) is not.

Implication for Recall: store numbers as JSON numbers, and store timestamps as ISO-8601
UTC strings (`YYYY-MM-DDTHH:MM:SSZ`). REQUIREMENTS.md already assumes the latter —
don't drift.

## Index config

`PostgresIndexConfig` — `base.py` lines ~321-333. Fields:

- `dims: int` — embedding dimension. Baked into `vector(dims)` column type.
- `embed: Embeddings` — LangChain Embeddings instance (OpenAI, etc.).
- `fields: list[str] | None` — value keys to embed. `None` means embed the whole value
  serialized. For Recall, embed a curated field (e.g. `["text"]`) to keep the vector
  stable and cheap.
- `distance_type: Literal["l2", "inner_product", "cosine"]` — default cosine is the
  usual pick for OpenAI embeddings.
- `ann_index_config: ANNIndexConfig` — `{kind: "hnsw" | "ivfflat" | "flat", ...}`, with
  HNSW taking `m` / `ef_construction`, IVFFlat taking `nlist`, flat taking nothing.

## `setup()` / migrations gotchas

- `setup()` is the only sanctioned migration path. Do not hand-write ALTER TABLE against
  the `store` schema — future LangGraph versions will add migrations and collide.
- Migrations are additive and versioned per table group; there is no down-migration. If
  we need a destructive change (e.g. `dims` bump), we have to either drop
  `store_vectors` or provision a second store and backfill.
- `store_migrations` / `vector_migrations` live in the same database. Back them up with
  the rest of the data.

## Cross-references

- ADR 0001 — Storage namespace `(scope, project_id)` invariant.
- ADR 0004 — Scope semantics (global vs project) and write rules.
- REQUIREMENTS.md S1.7 / S1.8 / S3.7 — scope invariant and project-state rule.
- LangMem notes: `/home/leonid/projects/recall/docs/reference/langmem-notes.md` —
  how memory tools are wired on top of this store.

## Source links

- `base.py` (schema, migrations, query builders, sync store):
  <https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py>
- `aio.py` (`AsyncPostgresStore`):
  <https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/aio.py>
- `BaseStore` contract:
  <https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/store/base.py>
