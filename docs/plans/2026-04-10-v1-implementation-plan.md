# Recall v1 — Implementation Plan

**Date:** 2026-04-10
**Status:** draft for Gate 2 review
**HLD:** [docs/design/v1-design.md](../design/v1-design.md)
**Load-bearing ADRs:** 0001–0004 (carried forward), 0006–0013 (drafted in kickoff)

This plan sequences the delivery of the **HLD's components and contracts**, not activities. Every epic maps to one or more components from the HLD's Level 2 decomposition and references the ADRs it depends on. `/architect` will turn each epic into LLDs and enriched task issues at the time the phase starts — only Phase 0 issues are created up-front (per ADR-0005).

---

## Phasing principle

A phase exists to deliver a **demonstrable, end-to-end vertical slice** of the system. Horizontal phases ("first build all the storage, then all the tools, then all the auth") delay integration risk to the worst possible moment. Each phase below has a stated goal expressed as an observable behaviour, and an exit criterion expressed as a test that runs in CI.

| Phase | Goal | Exit criterion |
|---|---|---|
| 0 | Repo, tooling, CI, container, real-Postgres test fixture all green on an empty server. | `uv run pytest -m integration` runs against testcontainers and passes the "server boots, /healthz returns ok" test. |
| 1 | A single agent can save and retrieve one project memory end-to-end over Streamable HTTP. | Integration test: bearer-auth a request, `memory_save` a memory, `memory_get` it back, both via real MCP transport. |
| 2 | Search works end-to-end across project + global with the ranking rule. | Integration test: ADR-0010 ranking properties hold against real pgvector + real (stub) embeddings. |
| 3 | Update, delete, and the full five-tool surface are wired and audited. | Integration test: every tool from S2 has at least one happy and one error path test. |
| 4 | Shared deployment is real: docker compose, env-var contract, structured logs, OTEL hooks, MCP config snippet. | Operator can `docker compose up` and point Claude Code at the server with the documented snippet. |
| 5 | Self-improving instructions and the compaction / GC job land. | CLI compaction run reduces a planted near-duplicate set; instruction kind round-trips through search. |
| 6 | Project export and the operator polish items from S5/S6 not yet covered. | Backup-export round-trip; CI runs lint+mypy+tests on every PR. |

Phases are ordered so that **the next phase's exit test depends on the previous phase's components existing**, not on activities being complete. A phase can be split or merged during `/architect` if the LLD shows the slice is too large or too small; the *order* should not change without revisiting this plan.

---

## Phase 0 — Foundation

**Goal.** Empty server boots, real Postgres test fixture works, CI is green, the container builds.

**Why first.** Every later phase's exit criterion is "an integration test passes". That presupposes a test fixture (ADR-0012), a migration runner (ADR-0013), and a container that boots. Building those after building features means features get tested against a stub harness and re-tested against the real one — exactly the LangMem v1 failure mode.

### E0.1 — Repository scaffolding and tooling
- **HLD reference:** Operator CLI; cross-cutting.
- **ADRs:** none new (uses tooling already named in CLAUDE.md).
- **Rough tasks:**
  - `uv` workspace, `pyproject.toml` with dev extras (`ruff`, `mypy`, `pytest`, `pytest-asyncio`, `testcontainers`, `structlog`).
  - `ruff` config matching CLAUDE.md house style; `mypy --strict` baseline.
  - Empty `src/recall/__init__.py`, `tests/` skeleton, `tests/conftest.py` placeholder.
  - `recall` CLI entry point exposing `serve`, `db migrate`, with stubs that exit cleanly.
  - Pre-commit hooks (ruff + mypy + pytest fast tier).

### E0.2 — CI pipeline
- **HLD reference:** cross-cutting (S6.6).
- **ADRs:** ADR-0012.
- **Rough tasks:**
  - GitHub Actions workflow: lint → typecheck → unit → integration, on every PR.
  - Docker available in the runner so testcontainers works.
  - Cache `uv` and the model directory for speed.
  - PR template referencing the issue, the LLD, and the relevant ADRs.

### E0.3 — Container image
- **HLD reference:** Deployment artefacts; Operator CLI.
- **ADRs:** ADR-0006 (one entrypoint), ADR-0008 (provider env vars).
- **Rough tasks:**
  - `Dockerfile` (multi-stage, slim runtime) producing `recall serve` as the entrypoint.
  - Healthcheck instruction wired to `/healthz`.
  - Image build runs in CI (tag = commit sha).
  - `docker compose up` brings Postgres+pgvector and Recall together; documented in README.

### E0.4 — Migration runner and initial schema
- **HLD reference:** Migrations; Storage Adapter.
- **ADRs:** ADR-0001, ADR-0002, ADR-0013.
- **Rough tasks:**
  - In-app DDL runner (`apply_pending`) per ADR-0013.
  - `0001_initial.sql` creating the memories table honouring ADR-0001's flat value schema and ADR-0002's namespace shape, including the S1.7 CHECK constraint.
  - `recall db migrate` CLI wrapper; `serve` startup hook (defaults on, env-flag to disable).
  - Unit test of the runner against an empty container; integration test of the initial schema's constraint behaviour.

### E0.5 — Real-Postgres test fixture
- **HLD reference:** cross-cutting test infra.
- **ADRs:** ADR-0012, ADR-0013.
- **Rough tasks:**
  - Session-scoped testcontainers Postgres+pgvector fixture.
  - Per-test isolation strategy (transactional rollback or per-test schema — LLD picks one).
  - `apply_pending` invoked once per session against the container.
  - Deterministic stub embeddings provider for use by integration tests.
  - Smoke integration test: container boots, schema applies, a row inserts.

### E0.6 — Health endpoints and structured logging skeleton
- **HLD reference:** Transport; Observability.
- **ADRs:** ADR-0006, ADR-0011.
- **Rough tasks:**
  - `/healthz` (liveness) and `/readyz` (DB reachable, embeddings provider warm) on the same Streamable HTTP listener.
  - `structlog` configured per ADR-0011, contextvars for `request_id`/`trace_id`/`span_id`.
  - Library logging bridged into structlog.
  - OTEL initialised in no-op mode unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
  - Integration test: server boots, `/healthz` returns ok, one structured log line is emitted with the expected field set.

**Phase 0 exit criterion.** `uv run pytest -m integration` passes against testcontainers, including the boot-and-health smoke test. CI is green on a PR that adds a no-op change.

---

## Phase 1 — One memory, end-to-end

**Goal.** A bearer-authenticated agent can save a single project-scoped memory and retrieve it by id, over real Streamable HTTP, against real Postgres, with one structured log line per call.

**Why this slice.** It is the smallest possible vertical that touches every component on the request path: Transport, Auth, Project Registry, Tool Router, Memory Service, Embedder (stub), Storage Adapter, Observability. After Phase 1 the architecture is real, not sketched.

### E1.1 — Auth component (bearer tokens)
- **HLD reference:** Auth.
- **ADRs:** ADR-0007.
- **Rough tasks:** token-file loader, header parsing, contextvar binding, hard-reject path with structured error, integration tests for accept/reject.

### E1.2 — Project registry
- **HLD reference:** Project Registry.
- **ADRs:** ADR-0009.
- **Rough tasks:** `0002_projects.sql` migration, in-memory cache with single-refresh-on-miss, `recall projects add|list|remove` CLI, S3.8 reserved-name CHECK.

### E1.3 — Embedder skeleton + stub provider
- **HLD reference:** Embedder.
- **ADRs:** ADR-0008.
- **Rough tasks:** `EmbeddingsProvider` interface, deterministic stub provider for tests, sentence-transformers provider behind a feature flag (full sentence-transformers wiring can land in Phase 4 if it slows Phase 1), `EMBEDDINGS_DIM` startup check.

### E1.4 — Storage Adapter (put/get)
- **HLD reference:** Storage Adapter.
- **ADRs:** ADR-0001, ADR-0002, ADR-0004.
- **Rough tasks:** thin wrapper over `AsyncPostgresStore` honouring the namespace shape, put and get only at this stage, defence-in-depth check of the (scope, project_id) invariant.

### E1.5 — Memory Service (save / get)
- **HLD reference:** Memory Service.
- **ADRs:** ADR-0001, ADR-0008.
- **Rough tasks:** `save` orchestrating embed-then-put, `get_by_id`, the S1.2 "embed only on content change" rule (exercised by Phase 3 update tests, not yet here).

### E1.6 — Tool Router + `memory_save` + `memory_get`
- **HLD reference:** Tool Router; Transport.
- **ADRs:** ADR-0006.
- **Rough tasks:** MCP tool declarations with descriptions that carry the S1.8 decision rule and the S2.2 vocabulary, request validation, structured error envelopes, integration tests against the real Streamable HTTP server.

**Phase 1 exit criterion.** Integration test: with a valid bearer token, an agent calls `memory_save` for a project memory, then `memory_get` with the returned id, and the round-trip succeeds. One `mcp_call` structured log line per call. The same test fails with `unauthenticated` if the token is omitted.

---

## Phase 2 — Search

**Goal.** `memory_search` returns a single ranked list across project + global with the ADR-0010 ranking rule, against real pgvector.

### E2.1 — Storage Adapter vector search
- **HLD reference:** Storage Adapter.
- **ADRs:** ADR-0002, ADR-0004.
- **Rough tasks:** vector search wrapper exposing only the filter operators that work, namespace-scoped, returning raw similarity scores.

### E2.2 — Memory Service search and ranking
- **HLD reference:** Memory Service.
- **ADRs:** ADR-0010.
- **Rough tasks:** concurrent project + global queries, additive boost merge, snippet construction (default + hard cap), `scope` shortcut handling, `kind`/`user_id` filter passthrough.

### E2.3 — `memory_search` tool
- **HLD reference:** Tool Router.
- **ADRs:** ADR-0010.
- **Rough tasks:** schema, description, integration tests for the ranking properties from ADR-0010.

**Phase 2 exit criterion.** Integration test using planted data: a "weak" project hit, a "strong" global hit, and a tied pair are arranged so that the ADR-0010 rules are observably enforced.

---

## Phase 3 — Update, delete, the full tool surface

**Goal.** All five tools from S2 are live and integration-tested. The S1.2 "embed only on content change" rule is exercised.

### E3.1 — `memory_update`
- **HLD reference:** Memory Service; Tool Router.
- **Rough tasks:** content-vs-metadata update path, content-change detection, integration tests proving metadata-only updates do not re-embed.

### E3.2 — `memory_delete`
- **HLD reference:** Memory Service; Tool Router.
- **Rough tasks:** delete-by-id, idempotency, integration tests.

### E3.3 — Full structured-error vocabulary
- **HLD reference:** Tool Router.
- **ADRs:** ADR-0011.
- **Rough tasks:** documented error codes (`unauthenticated`, `unknown_project`, `embedding_failed`, `not_found`, `validation_error`), one place defining them, tests asserting the envelopes.

**Phase 3 exit criterion.** Every tool in S2 has at least one happy-path and one error-path integration test.

---

## Phase 4 — Real deployment story

**Goal.** Recall is deployable as shared infrastructure with the documented env-var contract. OTEL works when turned on. The full embeddings provider matrix works.

### E4.1 — Real embeddings providers
- **HLD reference:** Embedder.
- **ADRs:** ADR-0008.
- **Rough tasks:** sentence-transformers fully wired (cold start blocks `/readyz`), OpenAI-compatible HTTP provider with timeout + single retry from S6.5, contract tests against real endpoints gated to nightly CI.

### E4.2 — OTEL exporter activation
- **HLD reference:** Observability.
- **ADRs:** ADR-0011.
- **Rough tasks:** auto-instrumentation for HTTP, asyncpg, outbound HTTP; off-by-default check; trace_id/span_id correlation in logs verified end-to-end.

### E4.3 — Deployment artefacts and operator docs
- **HLD reference:** Deployment artefacts; Operator CLI.
- **ADRs:** ADR-0006, ADR-0007.
- **Rough tasks:** `docker-compose.yml` polish, README, MCP client config snippet (S5.6), env-var reference page.

**Phase 4 exit criterion.** A second machine can `docker compose up`, point a real Claude Code client at the server with the documented snippet, save and search a memory, and observe traces if `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

---

## Phase 5 — Instructions and compaction

**Goal.** `kind=instruction` round-trips, the on-demand compaction job from S4.6 / S6.7 runs.

### E5.1 — Instruction kind end-to-end
- **HLD reference:** Tool Router; Memory Service.
- **ADRs:** none new.
- **Rough tasks:** documenting the kind in tool descriptions, integration tests for the global vs project decision rule on instructions, no new code unless something is missing — the whole point of S2.2 is that this is data, not code.

### E5.2 — Compactor
- **HLD reference:** Compactor; Operator CLI.
- **ADRs:** none new (uses ADR-0008 for the compaction LLM provider shape).
- **Rough tasks:** compaction LLM provider behind the same OpenAI-compatible interface, near-duplicate flagging, prune-unread pass (S6.7(a)), `metadata.priority` maintenance, `recall compact` CLI subcommand, tests against planted near-duplicates.

**Phase 5 exit criterion.** `recall compact` reduces a planted set of near-duplicate instructions; an instruction saved with `scope=global` is retrievable via search from a different project.

---

## Phase 6 — Operator polish

**Goal.** Everything in S5/S6 not yet shipped. This phase exists so earlier phases can stay narrowly scoped without dropping requirements.

### E6.1 — Project export
- **HLD reference:** Exporter; Operator CLI.
- **Rough tasks:** `recall export <project_id>` streams JSON, integration test of round-trip.

### E6.2 — Audit and operational hardening
- **HLD reference:** Observability; Auth.
- **Rough tasks:** ensuring the S6.3 field set is complete on every code path, auth-rejection log line audit, `LOG_LEVEL` knob exercised in tests.

### E6.3 — Documentation pass
- **HLD reference:** Deployment artefacts.
- **Rough tasks:** README sweep, runbook for common ops (rotate token, add project, run compaction, restore from backup), CLAUDE.md cross-references audited.

**Phase 6 exit criterion.** All requirements S1–S6 (excluding the explicitly deferred items) have at least one integration test or documented operator procedure.

---

## Cross-phase dependencies

- **Phase 0 must complete before any other phase.** Every later phase's exit criterion presupposes the test fixture and CI from Phase 0.
- **Phase 1 must complete before Phases 2–5.** Search, update, deployment, and compaction all depend on the request path Phase 1 establishes.
- **Phase 2 and Phase 3 can in principle interleave** within Phase 1's foundation, but Phase 2 should land first because the search ranking ADR-0010 is the highest-risk product call and benefits from real-world tuning time.
- **Phase 4 can start as soon as Phase 1 lands** — the deployment story does not depend on every tool being complete — but its *exit* test depends on at least save+search+get being available.
- **Phase 5 depends on Phase 3** (the full tool surface, including update for instruction priority changes).
- **Phase 6 depends on whatever Phase 5 leaves unfinished.**

## Out of scope (explicitly deferred)

These appear in REQUIREMENTS.md but are deferred per the requirements themselves or per ADRs above:

- Helm chart / k8s manifest (S5.3)
- Per-user-private memories within a project (S4.5, deferred to v3)
- LLM-driven scope reclassification (S6.7(c), explicit "can land later")
- OIDC / mTLS auth (ADR-0007)
- Custom OTEL spans / metrics dashboards (ADR-0011)
- Down-migrations (ADR-0013)
- Cross-encoder re-ranking (ADR-0010)

## Cross-references

- HLD: [docs/design/v1-design.md](../design/v1-design.md)
- ADRs: [0001](../adr/0001-flat-value-schema.md), [0002](../adr/0002-namespace-shape.md), [0003](../adr/0003-ttl-sweeper-ownership.md), [0004](../adr/0004-filter-limitations.md), [0006](../adr/0006-streamable-http-mcp-transport.md), [0007](../adr/0007-shared-bearer-token-auth.md), [0008](../adr/0008-embeddings-provider-abstraction.md), [0009](../adr/0009-project-registry-table.md), [0010](../adr/0010-search-ranking-union-with-project-boost.md), [0011](../adr/0011-observability-structlog-otel-auto.md), [0012](../adr/0012-test-strategy-real-postgres-no-mocks.md), [0013](../adr/0013-in-app-ddl-migrations-no-alembic.md)
- Requirements: [REQUIREMENTS.md](../../REQUIREMENTS.md)
