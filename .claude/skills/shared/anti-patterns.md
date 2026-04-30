# Known Anti-Patterns (Static Checklist)

Scan the diff for these regardless of which files changed. This list is the
institutional memory of "things we've learned the hard way."

Add new anti-patterns here as the team discovers them.

## General

- **DRY violation — duplicate store query or service logic.** A new service, helper, or
  tool handler reimplements data-fetching or business logic that already exists in a
  sibling module. Detected by: a new file that calls `AsyncPostgresStore` methods
  (`asearch`, `aput`, `aget`, `adelete`) for the same purpose as an existing file without
  importing from it.
  Fix: extract the shared logic into a dedicated service or query module and import from
  both call sites. Severity: **warn** — two diverging code paths for the same data,
  maintenance burden, and risk of behavioural inconsistency.

## Storage namespace & scoping

- **Widening the store namespace beyond `(scope, project_id)`** — e.g. prepending
  `user_id`, appending a sub-key, or using a three-element tuple. The invariant is
  enforced by REQUIREMENTS.md S3.7 and ADR-0002. Severity: **block**. Fix: keep the
  namespace exactly `(scope, project_id)` and put any extra dimension in the record's
  value or metadata.
- **Writing a `scope=global` row that references project-specific state** (e.g. a
  repo path, a local file, a PR number tied to one project). See REQUIREMENTS.md S1.8
  decision rule. Severity: **warn**. Fix: use `scope=project` instead.
- **Creating a `scope=project` record without a non-null `project_id`**, or a
  `scope=global` record with a non-null `project_id`. The DB CHECK constraint from
  S1.7 will reject it at write time, but the bug should be caught in review first.
  Severity: **block**.

## Store access

- **Mocking `AsyncPostgresStore` (or any of its methods) in integration tests.** See
  CLAUDE.md "Things to never do" and ADR-0012. Integration tests must use
  `testcontainers` against real Postgres. Severity: **block**. Fix: use the
  real-Postgres fixture; if the test is fundamentally a unit test, move it to
  `tests/unit/` and test the pure code path without the store.
- **Raw SQL against the memory tables bypassing `AsyncPostgresStore`** in
  application code. `asearch`, `aput`, `aget`, `adelete` are the only supported
  entry points for memory records. Raw SQL is acceptable only in migrations and
  the bootstrap DDL path (ADR-0013). Severity: **warn**.
- **Assuming nested-key filters work on `AsyncPostgresStore.asearch`** — the filter
  API only matches on top-level keys of the stored value. See
  `docs/reference/asyncpostgresstore-notes.md` and ADR-0004. Severity: **warn**.
- **Numeric comparison in store filters** — store filters compare values
  lexicographically, so `{"created_at": {"$gt": 1712000000}}` will not do what you
  think. Use ISO-8601 strings for dates (ADR-0004). Severity: **warn**.

## MCP tool surface

- **Adding a new MCP tool without updating REQUIREMENTS.md E2** and confirming
  the ≤ 6 tool budget still holds (v1 ships 5). Tool design is prompt design — new
  tools need a product decision, not just an implementation. Severity: **block**.
- **Restoring a tool that REQUIREMENTS.md v1 removed** (`instructions_get`,
  anything tags-related). Instructions are on-demand via `memory_search`; tags
  were dropped. If you need these back, it is a spec change, not an
  implementation detail. Severity: **block**.
- **Adding `ttl`, `expires_at`, or any time-based auto-expiry** to memories. See
  ADR-0003: v1 has no TTL. Severity: **block**.

## Secrets & env

- Any hardcoded secret, API key, or bearer token not referencing `os.environ`
  (or equivalent). Severity: **block**.
- `os.environ["FOO"]` accessed at module import time without a default or error
  path — crashes tests and tools that import the module for unrelated reasons.
  Severity: **warn**. Fix: read env vars lazily inside the function or at startup
  in `main()`.
- Printing request/response bodies that may contain user content to stdout
  without a structured log call. Structured logs go via `structlog` per ADR-0011
  so fields stay queryable. Severity: **warn**.

## Error handling

- `except:` (bare) or `except Exception:` without re-raise or structured log.
  Silent swallowing is always a bug — see REQUIREMENTS.md S6.5 and the
  silent-swallow gate in `/feature-core`. Severity: **block**. Fix: narrow the
  exception, log with `logger.exception(...)`, and either recover or re-raise.
- `try` block around an entire function body — almost always too broad. Severity:
  **warn**.

## Python / typing

- `typing.Any` or `# type: ignore` without a justification comment.
  `mypy --strict` is the contract; escape hatches need a one-line explanation of
  the specific constraint that forced them. Severity: **warn**.
- `cast(...)` used to paper over a type mismatch rather than fix it. Severity:
  **warn**.
- Sync IO (`time.sleep`, blocking `requests.get`, blocking `psycopg` calls) inside
  an `async def`. Blocks the event loop. Severity: **block**. Fix: use the async
  counterpart (`asyncio.sleep`, `httpx.AsyncClient`, `asyncpg` / the async store
  method).
