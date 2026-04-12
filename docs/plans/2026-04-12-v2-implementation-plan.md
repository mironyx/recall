# Recall v2 — Implementation Plan

**Date:** 2026-04-12
**Status:** draft for Gate 2 review
**HLD:** [docs/design/v2-design.md](../design/v2-design.md)
**Requirements:** [docs/requirements/v2-requirements.md](../requirements/v2-requirements.md)
**Load-bearing ADRs:** 0001–0004 (foundational), 0005–0013 (from v1 kickoff, adopted by v2)

This plan sequences the delivery of the **HLD's components and contracts**,
not activities. Every epic maps to one or more components from the HLD's
Level 2 decomposition and references the ADRs it depends on. `/architect`
will turn each epic into LLDs and enriched task issues at the time the phase
starts — only Phase 0 issues are created up-front (per ADR-0005).

---

## Phasing principle

A phase exists to deliver a **demonstrable, end-to-end vertical slice** of
the system. Horizontal phases ("first build all the storage, then all the
tools, then all the auth") delay integration risk to the worst possible
moment. Each phase below has a stated goal expressed as an observable
behaviour, and an exit criterion expressed as a test that runs in CI.

| Phase | Goal | Exit criterion |
|---|---|---|
| 0 | Repo, tooling, CI, container, real-Postgres test fixture all green on an empty server. | `uv run pytest -m integration` runs against testcontainers and passes the "server boots, /healthz returns ok" test. |
| 1 | A single agent can save and retrieve one project memory end-to-end over Streamable HTTP. | Integration test: bearer-auth a request, `memory_save` a memory, `memory_get` it back, both via real MCP transport. |
| 2 | Search works end-to-end across project + global with the ranking rule. | Integration test: ADR-0010 ranking properties hold against real pgvector + real (stub) embeddings. |
| 3 | Update, delete, and the full five-tool surface are wired and audited. | Integration test: every tool has at least one happy and one error path test. |
| 4 | Shared deployment is real: docker compose, env-var contract, structured logs, OTEL hooks, MCP config snippet. | Operator can `docker compose up` and point Claude Code at the server with the documented snippet. |
| 5 | Instructions round-trip, agent integration docs ship, operator polish. | Instruction `kind` round-trips through search; reference agent instructions and export are documented and tested. |

Phases are ordered so that **the next phase's exit test depends on the
previous phase's components existing**, not on activities being complete. A
phase can be split or merged during `/architect` if the LLD shows the slice
is too large or too small; the *order* should not change without revisiting
this plan.

---

## Phase 0 — Foundation

**Goal.** Empty server boots, real Postgres test fixture works, CI is green,
the container builds.

**Why first.** Every later phase's exit criterion is "an integration test
passes". That presupposes a test fixture (ADR-0012), a migration runner
(ADR-0013), and a container that boots. Building those after building
features means features get tested against a stub harness and re-tested
against the real one — exactly the LangMem v1 failure mode.

### E0.1 — Repository scaffolding and tooling
- **HLD reference:** CLI; cross-cutting.
- **ADRs:** none new (uses tooling already named in CLAUDE.md).
- **Rough tasks:**
  - `uv` workspace, `pyproject.toml` with dev extras (`ruff`, `mypy`,
    `pytest`, `pytest-asyncio`, `testcontainers`, `structlog`).
  - `ruff` config matching CLAUDE.md house style; `mypy --strict` baseline.
  - Empty `src/recall/__init__.py`, `tests/` skeleton,
    `tests/conftest.py` placeholder.
  - `recall` CLI entry point exposing `serve`, `db migrate`, with stubs
    that exit cleanly.
  - Pre-commit hooks (ruff + mypy + pytest fast tier).

### E0.2 — CI pipeline
- **HLD reference:** cross-cutting.
- **ADRs:** ADR-0012.
- **Rough tasks:**
  - GitHub Actions workflow: lint → typecheck → unit → integration, on
    every PR.
  - Docker available in the runner so testcontainers works.
  - Cache `uv` and the model directory for speed.
  - PR template referencing the issue, the LLD, and the relevant ADRs.

### E0.3 — Container image
- **HLD reference:** CLI; MCP Transport.
- **ADRs:** ADR-0006 (one entrypoint), ADR-0008 (provider env vars).
- **Rough tasks:**
  - `Dockerfile` (multi-stage, slim runtime) producing `recall serve` as
    the entrypoint.
  - Healthcheck instruction wired to `/healthz`.
  - Image build runs in CI (tag = commit sha).
  - `docker compose up` brings Postgres+pgvector and Recall together;
    documented in README.

### E0.4 — Migration runner and initial schema
- **HLD reference:** Migration Runner.
- **ADRs:** ADR-0001, ADR-0002, ADR-0013.
- **Rough tasks:**
  - In-app DDL runner (`apply_pending`) per ADR-0013.
  - `0001_initial.sql` creating the memories table honouring ADR-0001's
    flat value schema and ADR-0002's namespace shape, including the scope
    CHECK constraint.
  - `recall db migrate` CLI wrapper; `serve` startup hook (defaults on,
    env-flag to disable).
  - Unit test of the runner against an empty container; integration test
    of the initial schema's constraint behaviour.

### E0.5 — Real-Postgres test fixture
- **HLD reference:** cross-cutting test infra.
- **ADRs:** ADR-0012, ADR-0013.
- **Rough tasks:**
  - Session-scoped testcontainers Postgres+pgvector fixture.
  - Per-test isolation strategy (transactional rollback or per-test
    schema — LLD picks one).
  - `apply_pending` invoked once per session against the container.
  - Deterministic stub embeddings provider for use by integration tests.
  - Smoke integration test: container boots, schema applies, a row inserts.

### E0.6 — Health endpoints and structured logging skeleton
- **HLD reference:** Health Endpoints; Tool Router (logging).
- **ADRs:** ADR-0006, ADR-0011.
- **Rough tasks:**
  - `/healthz` (liveness) and `/readyz` (DB reachable, embeddings provider
    warm) on the same Streamable HTTP listener.
  - `structlog` configured per ADR-0011, contextvars for
    `request_id`/`trace_id`/`span_id`.
  - Library logging bridged into structlog.
  - OTEL initialised in no-op mode unless `OTEL_EXPORTER_OTLP_ENDPOINT`
    is set.
  - Integration test: server boots, `/healthz` returns ok, one structured
    log line is emitted with the expected field set.

**Phase 0 exit criterion.** `uv run pytest -m integration` passes against
testcontainers, including the boot-and-health smoke test. CI is green on a
PR that adds a no-op change.

---

## Phase 1 — One memory, end-to-end

**Goal.** A bearer-authenticated agent can save a single project-scoped
memory and retrieve it by id, over real Streamable HTTP, against real
Postgres, with one structured log line per call.

**Why this slice.** It is the smallest possible vertical that touches every
component on the request path: MCP Transport, Auth, Project Registry, Tool
Router, Memory Service, Embedder (stub), Postgres. After Phase 1 the
architecture is real, not sketched.

### E1.1 — Auth component (bearer tokens)
- **HLD reference:** Auth.
- **ADRs:** ADR-0007.
- **Rough tasks:** token-file loader, header parsing, contextvar binding,
  hard-reject path with structured error, integration tests for
  accept/reject.

### E1.2 — Project registry
- **HLD reference:** Project Registry.
- **ADRs:** ADR-0009.
- **Rough tasks:** `0002_projects.sql` migration, in-memory cache with
  single-refresh-on-miss, `recall projects add|list|remove` CLI, reserved
  name CHECK constraint.

### E1.3 — Embedder skeleton + stub provider
- **HLD reference:** Embedder.
- **ADRs:** ADR-0008.
- **Rough tasks:** `EmbeddingsProvider` interface, deterministic stub
  provider for tests, sentence-transformers provider behind a feature flag
  (full wiring can land in Phase 4), `EMBEDDINGS_DIM` startup check.

### E1.4 — Storage adapter (put/get)
- **HLD reference:** Memory Service (storage layer).
- **ADRs:** ADR-0001, ADR-0002, ADR-0004.
- **Rough tasks:** thin wrapper over `AsyncPostgresStore` honouring the
  namespace shape, put and get only at this stage, defence-in-depth check
  of the (scope, project_id) invariant.

### E1.5 — Memory Service (save / get)
- **HLD reference:** Memory Service.
- **ADRs:** ADR-0001, ADR-0008.
- **Rough tasks:** `save` orchestrating embed-then-put, `get_by_id`.

### E1.6 — Tool Router + `memory_save` + `memory_get`
- **HLD reference:** Tool Router; MCP Transport.
- **ADRs:** ADR-0006.
- **Rough tasks:** MCP tool declarations with agent-oriented descriptions,
  request validation, structured error envelopes, integration tests against
  the real Streamable HTTP server.

**Phase 1 exit criterion.** Integration test: with a valid bearer token, an
agent calls `memory_save` for a project memory, then `memory_get` with the
returned id, and the round-trip succeeds. One `mcp_call` structured log
line per call. The same test fails with `unauthenticated` if the token is
omitted.

---

## Phase 2 — Search

**Goal.** `memory_search` returns a single ranked list across project +
global with the ADR-0010 ranking rule, against real pgvector.

### E2.1 — Storage adapter vector search
- **HLD reference:** Memory Service (storage layer).
- **ADRs:** ADR-0002, ADR-0004.
- **Rough tasks:** vector search wrapper exposing only the filter operators
  that work, namespace-scoped, returning raw similarity scores.

### E2.2 — Memory Service search and ranking
- **HLD reference:** Memory Service.
- **ADRs:** ADR-0010.
- **Rough tasks:** concurrent project + global queries, additive boost
  merge, snippet construction (default + hard cap), `scope` shortcut
  handling, `kind`/`user_id` filter passthrough.

### E2.3 — `memory_search` tool
- **HLD reference:** Tool Router.
- **ADRs:** ADR-0010.
- **Rough tasks:** schema, description, integration tests for the ranking
  properties from ADR-0010.

**Phase 2 exit criterion.** Integration test using planted data: a "weak"
project hit, a "strong" global hit, and a tied pair are arranged so that the
ADR-0010 rules are observably enforced.

---

## Phase 3 — Update, delete, the full tool surface

**Goal.** All five tools are live and integration-tested. The "embed only on
content change" rule is exercised.

### E3.1 — `memory_update`
- **HLD reference:** Memory Service; Tool Router.
- **ADRs:** ADR-0001, ADR-0008.
- **Rough tasks:** content-vs-metadata update path, content-change
  detection, integration tests proving metadata-only updates do not
  re-embed.

### E3.2 — `memory_delete`
- **HLD reference:** Memory Service; Tool Router.
- **ADRs:** ADR-0002.
- **Rough tasks:** delete-by-id, idempotency, integration tests.

### E3.3 — Full structured-error vocabulary
- **HLD reference:** Tool Router.
- **ADRs:** ADR-0011.
- **Rough tasks:** documented error codes (`unauthenticated`,
  `unknown_project`, `embedding_failed`, `not_found`, `validation_error`),
  one place defining them, tests asserting the envelopes.

**Phase 3 exit criterion.** Every tool has at least one happy-path and one
error-path integration test.

---

## Phase 4 — Real deployment story

**Goal.** Recall is deployable as shared infrastructure with the documented
env-var contract. OTEL works when turned on. The full embeddings provider
matrix works.

### E4.1 — Real embeddings providers
- **HLD reference:** Embedder.
- **ADRs:** ADR-0008.
- **Rough tasks:** sentence-transformers fully wired (cold start blocks
  `/readyz`), OpenAI-compatible HTTP provider with timeout + single retry,
  contract tests against real endpoints gated to nightly CI.

### E4.2 — OTEL exporter activation
- **HLD reference:** Tool Router (logging invariant).
- **ADRs:** ADR-0011.
- **Rough tasks:** auto-instrumentation for HTTP, asyncpg, outbound HTTP;
  off-by-default check; trace_id/span_id correlation in logs verified
  end-to-end.

### E4.3 — Deployment artefacts and operator docs
- **HLD reference:** CLI; MCP Transport.
- **ADRs:** ADR-0006, ADR-0007.
- **Rough tasks:** `docker-compose.yml` polish, README, MCP client config
  snippet, env-var reference page.

**Phase 4 exit criterion.** A second machine can `docker compose up`, point
a real Claude Code client at the server with the documented snippet, save
and search a memory, and observe traces if `OTEL_EXPORTER_OTLP_ENDPOINT` is
set.

---

## Phase 5 — Instructions, export, and polish

**Goal.** `kind=instruction` round-trips through search, agent integration
docs ship, project export works. Everything needed for a team to adopt
Recall.

### E5.1 — Instruction kind end-to-end
- **HLD reference:** Memory Service; Tool Router.
- **ADRs:** none new.
- **Rough tasks:** documenting the kind in tool descriptions, integration
  tests for the global vs project instruction retrieval via
  `memory_search(kind="instruction")`, verifying the ADR-0010 project
  boost gives project instructions natural precedence. No new code unless
  something is missing — the whole point is that this is data, not code.

### E5.2 — Project export
- **HLD reference:** CLI; Memory Service.
- **Rough tasks:** `recall export <project_id>` streams JSON, integration
  test of round-trip.

### E5.3 — Reference agent instructions and MCP config
- **HLD reference:** C9 (Agent guidance).
- **Rough tasks:** sample CLAUDE.md snippet showing when to store/retrieve
  memories, MCP connection configuration for Claude Code and Cursor,
  instruction scope decision rule documented, at least one example of a
  save call and a search call.

### E5.4 — Audit and operational hardening
- **HLD reference:** Tool Router (logging); Auth.
- **Rough tasks:** ensuring the ADR-0011 field set is complete on every
  code path, auth-rejection log line audit, `LOG_LEVEL` knob exercised in
  tests.

### E5.5 — Documentation pass
- **HLD reference:** CLI.
- **Rough tasks:** README sweep, runbook for common ops (rotate token, add
  project, restore from backup), CLAUDE.md cross-references audited.

**Phase 5 exit criterion.** All v2 requirements (excluding explicitly
deferred items) have at least one integration test or documented operator
procedure. `kind=instruction` round-trips end-to-end.

---

## Cross-phase dependencies

- **Phase 0 must complete before any other phase.** Every later phase's
  exit criterion presupposes the test fixture and CI from Phase 0.
- **Phase 1 must complete before Phases 2–5.** Search, update, deployment,
  and instructions all depend on the request path Phase 1 establishes.
- **Phase 2 and Phase 3 can in principle interleave** within Phase 1's
  foundation, but Phase 2 should land first because the search ranking
  ADR-0010 is the highest-risk product call and benefits from real-world
  tuning time.
- **Phase 4 can start as soon as Phase 1 lands** — the deployment story
  does not depend on every tool being complete — but its *exit* test
  depends on at least save+search+get being available.
- **Phase 5 depends on Phase 3** (the full tool surface, including update
  for instruction refinement).

---

## Out of scope (explicitly deferred)

These appear in requirements but are deferred per the requirements
themselves or per ADRs:

- Instruction compaction / LLM-driven merge (v2.1 — Story 3.5)
- Garbage collection of global memories (v2.1 — C11 deferred)
- LLM-driven scope reclassification (v2.1)
- Per-user-private memories within a project (v3)
- OIDC / mTLS auth (Wave 2 — ADR-0007)
- Custom OTEL spans / metrics dashboards (ADR-0011)
- Down-migrations (ADR-0013)
- Cross-encoder re-ranking (ADR-0010)
- Tag filtering (ADR-0004 amendment)
- Helm chart / k8s manifest

---

## Cross-references

- HLD: [docs/design/v2-design.md](../design/v2-design.md)
- Requirements: [docs/requirements/v2-requirements.md](../requirements/v2-requirements.md)
- ADRs: [0001](../adr/0001-flat-value-schema.md),
  [0002](../adr/0002-namespace-shape.md),
  [0003](../adr/0003-ttl-sweeper-ownership.md),
  [0004](../adr/0004-filter-limitations.md),
  [0005](../adr/0005-project-bootstrap-pipeline.md),
  [0006](../adr/0006-streamable-http-mcp-transport.md),
  [0007](../adr/0007-shared-bearer-token-auth.md),
  [0008](../adr/0008-embeddings-provider-abstraction.md),
  [0009](../adr/0009-project-registry-table.md),
  [0010](../adr/0010-search-ranking-union-with-project-boost.md),
  [0011](../adr/0011-observability-structlog-otel-auto.md),
  [0012](../adr/0012-test-strategy-real-postgres-no-mocks.md),
  [0013](../adr/0013-in-app-ddl-migrations-no-alembic.md)
