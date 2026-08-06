# Session Log — 2026-05-11 — Real-Postgres Test Fixture (#77)

## Approach rationale

Issue #77 (E0.5) delivers the real-Postgres integration test infrastructure
mandated by ADR-0012: a session-scoped testcontainers fixture, per-test
TRUNCATE isolation, a deterministic stub embeddings provider (ADR-0008), and a
smoke test proving the whole stack. Every later phase's integration tests
build on these fixtures, so the LLD spec (`docs/design/lld-e05-test-fixture.md`)
was followed closely, with corrections where the design had drifted from
ADR-0013 (idempotent schema setup) and ADR-0014 (deferred `projects` table).

## Work completed

- Added `src/recall/embeddings/stub.py` — deterministic `StubEmbeddingsProvider`
  (hash → uint32 → `[-1, 1)` → L2-normalised), plus `__init__.py` package marker
- Extended `tests/conftest.py` with the E0.5 fixture chain: session-scoped
  container (`postgres_container`), session `ensure_schema` run
  (`_migrated_db_sess`), per-test `store` fixture with TRUNCATE isolation and
  `PostgresIndexConfig` wired to the stub
- Added `tests/test_stub_embeddings.py` — 13 unit tests (determinism, dimension,
  distinctness, batch, empty input, L2 norm, `dim` attribute)
- Added `tests/test_smoke.py` — integration tests: container boots + schema
  applies, TRUNCATE isolation (insert / no-leak), `aput`/`aget` round-trip,
  scope CHECK-constraint enforcement
- PR #93 created, reviewed (all review agents returned no issues), merged

## Decisions made

- **Schema setup via `ensure_schema()`** — the LLD referenced `apply_pending`
  (pre-ADR-0013 migration runner); by implementation time ADR-0013 had replaced
  it with the idempotent in-app schema setup in `recall.db.schema`.
- **`psycopg` for raw DB access** — TRUNCATE and schema checks use
  `psycopg.AsyncConnection`, not asyncpg (matches the store's own driver).
- **TRUNCATE only `store`, `store_vectors`** — the LLD's `projects` table does
  not exist yet (deferred per ADR-0014), so it is not truncated.
- **uint32 → `[-1, 1)` for stub vectors** — unpacking hash bytes directly as
  IEEE-754 floats produces NaN/inf bit patterns; mapping as unsigned ints is
  always finite before L2-normalisation.
- **Native `PostgresIndexConfig(embed=...)`** — no LangChain adapter needed;
  the store accepts an `embed` callable delegating to the stub.
- **Windows event loop policy** — `WindowsSelectorEventLoopPolicy()` installed
  in conftest so `psycopg` async works on win32.

## Review feedback addressed

All review agents (CLAUDE.md compliance, bug scan, etc.) returned no issues.
One lint fix commit (`fix: ruff format in test_smoke.py`) landed after the main
implementation commit.

## LLD Sync report

## LLD Sync — Issue #77: E0.5 — Real-Postgres test fixture

### Corrections (spec was wrong)
- **Migration entrypoint**: spec referenced `apply_pending` (pre-ADR-0013 migration runner) → built with `ensure_schema()` from `recall.db.schema`, the idempotent in-app schema setup that replaced the migration runner (ADR-0013).
- **Raw DB access**: spec said raw `asyncpg` connection → built with `psycopg.AsyncConnection` for TRUNCATE and schema checks.
- **TRUNCATE table list**: spec said `TRUNCATE store, store_vectors, projects CASCADE` → built truncates only `store, store_vectors`; the `projects` table does not exist yet (deferred per ADR-0014).
- **Stub vector generation**: spec proposed unpacking hash bytes directly as IEEE-754 floats (`struct.unpack(f'{dim}f', ...)`) → raw hash bytes frequently form NaN/inf bit patterns, corrupting normalisation; built unpacks as unsigned 32-bit ints mapped into `[-1, 1)` then L2-normalises.
- **Fixture names**: spec named `pg_container` / `_migrated_db` → built as `postgres_container` / `_migrated_db_sess`; session conn string is `pg_conn_string` (alias over the pre-existing `postgres_dsn`).
- **Store index config**: spec hedged "LangChain-compatible adapter (or native embedding support)" → built uses the store's native `PostgresIndexConfig(dims=stub.dim, embed=_embed)`; no LangChain adapter needed.

### Additions (not in spec)
- **`postgres_dsn` normalisation**: testcontainers emits `postgresql+psycopg2://`; the DSN is normalised to bare `postgresql://` for psycopg/asyncpg.
- **Windows event loop policy**: `asyncio.WindowsSelectorEventLoopPolicy()` installed on win32 — psycopg async requires a selector-based loop.
- **Two-test TRUNCATE isolation**: spec had one `test_truncate_isolation`; built as `test_truncate_isolation` (insert) + `test_truncate_isolation_no_leak` (asserts empty at start).
- **Expanded stub unit suite**: 13 tests vs the 5 BDD specs — adds custom-dimension, empty-input, and public `dim`-attribute coverage.

### Omissions (in spec but not built)
- None. All acceptance criteria shipped.

### Confirmations (notable)
- Container image `pgvector/pgvector:pg16` as specified.
- Stub lives in `src/recall/embeddings/stub.py` (not `tests/`) — confirmed correct for the index-config path and local dev.
- Session-scoped container + single `ensure_schema` run per session, per-test TRUNCATE isolation.
- Scope CHECK-constraint smoke test (`test_scope_check_enforced`) as specified.

### LLD updated
File: `docs/design/lld-e05-test-fixture.md` (legacy flat)
Version: 0.1 → 0.2
kb: `kb/architecture.md` — catalogue entry added for `StubEmbeddingsProvider`
Coverage manifest: none exists for epic E0 — skipped.

## Cost retrospective

| Metric | Value |
|---|---|
| PR-creation cost | (not recorded in PR body — "Cost: unavailable") |
| Final cost | $0.0000 |
| Tokens | 0 input / 0 output (no usage telemetry captured for this session) |
| Time to PR | 44 min |

**Cost drivers:**
- Usage telemetry returned 0 tokens — no Prometheus data was captured for the
  `recall-77` session. The PR-creation cost capture also failed (PR body shows
  "Cost: unavailable"), consistent with the issue flagged in the #75 session
  ("PR-creation cost not recorded — script failed").
- Two commits on the branch (implementation + `fix: ruff format`) indicate a
  small post-implementation lint fix cycle.

**Improvement actions:**
- Investigate why cost telemetry returns 0 for this session (session predates
  textfile registration, or Prometheus query gap) — fix the `create-feature-pr.sh`
  cost capture so PR bodies carry usage (recurring issue from #75).
- Ruff format drifted on `test_smoke.py` after the main commit — run
  `ruff format` as part of the verification pass, not just `ruff check`.

## Next steps

- Verify remaining Phase 0 board items are closed (E0.5 done; E0.3, E0.6
  already merged per #75 session log).
- Start Phase 1: Memory Service, Auth, MCP transport wiring.
