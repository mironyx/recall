# LangMem v2 — Requirements

**Status:** draft for review
**Date:** 2026-04-08
**Supersedes:** the POC on `master`. This is a greenfield rewrite, not a refactor.

---

## Context

LangMem v1 was a proof of concept. It works but is over-built: ~10k LOC, 30+ MCP tools, three parallel server entrypoints, layers wrapping layers. We are rewriting it as a focused product.

### Who uses it
- **Coding agents** (Claude Code, Cursor, etc.) used by **engineers on a team**, running on **multiple machines**, sharing one memory backend.
- The agents — not humans — call the MCP tools. Tool design is therefore prompt design.
- **Terminology:** throughout this document, *agent* = the MCP client (Claude Code, Cursor, …); *user* = the human operator the agent is acting for, identified via auth for audit and multi-human project sharing.

### What it does
Gives those agents persistent, project-scoped memory across sessions and machines: architectural decisions, gotchas learned the hard way, how a component currently works, and self-improving instructions for the agent itself.

### Hard constraints
- **MCP transport:** Streamable HTTP (the current MCP standard). The old SSE-via-intermediate-service shim goes away.
- **Multi-user, multi-machine:** server is shared infrastructure, not local-only.
- **Postgres + pgvector** as the storage backend (keep what works from v1).

---

## Design principles

1. **Few tools, broad tools.** The agent should not have to choose between 30 lookalikes. Target: ≤ 6 MCP tools total.
2. **Two scopes: project and global.** A memory is either bound to a `project_id` or marked `scope=global` (no project). Global is for facts that would still be true and useful in *any* repo — brand-new or existing — tomorrow: user preferences, library/tool gotchas, cross-project lessons. No team/org hierarchy beyond this. Cross-project search is not supported: a search targets one project, global only, or project+global.
3. **Categories are data, not classes.** A memory has a `kind` field (`decision`, `episode`, `component`, `gotcha`, `instruction`, …). Adding a kind is a config change, not a new class + module + endpoint.
4. **One server, one transport, one entrypoint.** No parallel implementations.
5. **The agent is the user.** Optimize tool descriptions and return shapes for LLM comprehension, not human ergonomics.
6. **Boring storage.** LangGraph `AsyncPostgresStore` + pgvector + OpenAI embeddings. No bespoke abstractions on top until proven necessary.

---

## Epics

| # | Epic | Goal |
|---|---|---|
| E1 | Core memory store | Persist, search, update, delete memories with semantic + structured filters |
| E2 | Agent-facing MCP surface | A small, self-explanatory tool set the LLM can use without a manual |
| E3 | Project & identity scoping | Multi-user, multi-machine, multi-project isolation |
| E4 | Self-improving instructions | Agents read & evolve their own behavioral guidance per project |
| E5 | Deployment & operations | Run as shared infrastructure for a team |
| E6 | Quality, safety, observability | Tests, migrations, audit trail |

---

## E1 — Core memory store

**Goal:** one storage layer that handles every memory kind.

- **S1.1** As the system, I store a memory record with: `id`, `scope` (`project` | `global`), `project_id` (non-null when `scope=project`, null when `scope=global`), `user_id` (identifies the human operator on whose behalf the agent acts, resolved from the request's auth token; audit-only, never part of the storage namespace), `kind`, `title`, `content`, `metadata{}`, `created_at`, `updated_at`, `embedding`.
- **S1.2** As the system, I generate embeddings on save and on content update only (not on metadata-only updates).
- **S1.3** As a caller, when I search with a `project_id`, results from that project **and** from `scope=global` are returned in a single ranked list, each result tagged with its scope. Project hits get a small ranking boost so they win ties; a high-confidence global hit can still outrank a weak project hit. Optional filters: `kind`, `user_id`, and `scope` (to restrict to only `project` or only `global`). Cross-project search is not supported.
- **S1.4** As a caller, I can fetch a memory by `id`.
- **S1.5** As a caller, I can update `content`, `metadata` of a memory by `id`.
- **S1.6** As a caller, I can delete a memory by `id`.
- **S1.7** As the system, I enforce a CHECK constraint: `(scope='project' AND project_id IS NOT NULL) OR (scope='global' AND project_id IS NULL)`. No other combinations.
- **S1.8** As the agent, I decide at save time whether a memory is project-scoped or global, guided by the rule in the `memory_save` tool description: *"If this fact would still be true and useful in any other repo — brand-new or existing — save it as global; otherwise project."* When in doubt, prefer project (narrower scope). The agent makes this call autonomously — no user confirmation required. A future garbage-collection pass (see E6) can reclassify or prune.
- **S1.9** As an operator, I can run `langmem db migrate` to create/upgrade the schema.

**Out of scope (v2):** graph relationships between memories, time-decay scoring, summarization of episodes, tags (dropped in favour of `kind` + semantic search; can be reintroduced later as an additive change if search quality demands it).

---

## E2 — Agent-facing MCP surface

**Goal:** ≤ 6 MCP tools, each with a clear purpose the LLM picks correctly without a manual. v1 ships **5 tools**.

Tools:

1. **`memory_save`** — `(scope, project_id?, kind, title, content, metadata?)` → `{id}`. `scope` is `"project"` or `"global"`. `project_id` is required when `scope="project"` and forbidden when `scope="global"`. The tool description carries the decision rule: *"global = still true and useful in any other repo tomorrow; project = otherwise. When in doubt, project."*
2. **`memory_search`** — `(project_id?, query, kind?, scope?, limit?)` → `[{id, scope, kind, title, snippet, score}]`. By default searches the given project **and** global; pass `scope="project"` or `scope="global"` to restrict. Cross-project search is not supported.
3. **`memory_get`** — `(id)` → full record.
4. **`memory_update`** — `(id, content?, metadata?)` → `{id}`.
5. **`memory_delete`** — `(id)` → `{ok}`.

`instructions_get` from earlier drafts has been removed: instructions are stored as `kind=instruction` and retrieved on demand via `memory_search` (see E4).

- **S2.1** As the agent, every tool's description tells me *when to call it* and gives one example. Tool descriptions are the API docs.
- **S2.2** As the agent, `kind` is a free-form string with a documented vocabulary (`decision`, `episode`, `component`, `gotcha`, `pattern`, `instruction`). I can introduce a new kind without server changes. **Note:** these kinds are a flat Recall-specific vocabulary; they do **not** map to LangMem's typed memory classes (Collection / Profile / Episodic / Procedural), which v2 does not use.
- **S2.3** As the agent, search results return short snippets (title + bounded content excerpt, default ~300 chars, configurable per call up to a hard cap), not full content, to keep my context window small. I call `memory_get` for the full record.
- **S2.4** As the system, all tools are exposed via **Streamable HTTP MCP transport** — no SSE shim.
- **S2.5** As the agent, errors come back as structured `{error, hint}` so I can recover.

---

## E3 — Project & identity scoping

**Goal:** safe multi-tenant use across machines.

- **S3.1** As an operator, I configure projects out-of-band (config file or `projects` table). Agents pass `project_id` on every project-scoped call.
- **S3.2** As the system, I authenticate the caller and resolve a `user_id` per request (the human operator behind the agent; mechanism in S3.5).
- **S3.3** As a user on machine A, memories I save are visible to my agent on machine B for the same `project_id`.
- **S3.4** As a user, memories saved by other users in the same project are visible to me by default. (Per-user privacy within a project is a v3 concern.)
- **S3.5** As an operator, v1 auth is a **shared bearer token per user**, configured out-of-band (env/config file). OIDC and mTLS are deferred beyond v1.
- **S3.6** As the system, I reject any request without a resolvable `user_id`. A resolvable `project_id` is required for all calls **except** `memory_save` / `memory_search` / `memory_get` operating on `scope=global` records.
- **S3.7** As the system, the storage namespace is `(scope, project_id)`. Project rows live under `("project", "<id>")`; global rows live under `("global", null)`. `user_id` is a column, not part of the namespace — it is audit-only.
- **S3.8** As the system, I reject any project config that tries to register a project named `global` (case-insensitive), to keep the scope vocabulary unambiguous.

---

## E4 — Self-improving instructions

**Goal:** the procedural-memory idea from v1, simplified. Instructions are **on-demand**, not auto-prepended. They are a normal memory `kind` and are retrieved via `memory_search`, complementing (not replacing) the host agent's static context files (e.g. `CLAUDE.md`).

**Rationale:** Claude Code and similar clients already have their own static, human-curated context mechanism (`CLAUDE.md`). Recall instructions fill a different niche: *agent-authored, evolving* guidance that the agent pulls when relevant. Auto-prepending on every session would duplicate CLAUDE.md, balloon context, and grow unboundedly.

- **S4.1** As the agent, when I learn a durable lesson, I save it as `kind=instruction` via `memory_save`, choosing `scope=global` for user/workflow preferences ("user wants terse PR descriptions") and `scope=project` for repo-specific rules ("always run `make fmt` before commit in this repo"). Same decision rule as S1.8.
- **S4.2** As the agent, when I need behavioural guidance (e.g. before a non-trivial decision, when starting work in an unfamiliar area), I retrieve relevant instructions via `memory_search(kind="instruction", query=..., scope=...)`. There is no dedicated `instructions_get` tool.
- **S4.3** As the agent, Recall instructions complement, not replace, the host client's static context (`CLAUDE.md` and equivalents). Static human-curated rules belong in `CLAUDE.md`; agent-authored evolving rules belong in Recall.
- **S4.4** As an operator, I can review and curate instructions (remove stale, merge duplicates) — initially via direct DB access; a CLI is a later story.
- **S4.5** As the agent, per-user-private instructions within a project remain deferred (v3). The `global` scope captures cross-project user/workflow preferences; the `project` scope captures repo-specific rules.
- **S4.6** As the system, an **LLM-driven instruction compaction job** runs on demand (CLI) or on schedule. It merges near-duplicates, drops stale entries, and maintains a `metadata.priority` field so on-demand search stays high-signal. The compaction LLM is configured via the `LLM_*` env vars in S5.1 and is separate from the embeddings provider.

---

## E5 — Deployment & operations

**Goal:** one team can stand up one shared LangMem server.

- **S5.1** As an operator, I deploy Recall as a single container configured via env vars:
  - `DATABASE_URL` — Postgres (with pgvector) connection string.
  - **Embeddings (required, no defaults):**
    - `EMBEDDINGS_PROVIDER` — `sentence-transformers` | `openai`.
    - `EMBEDDINGS_MODEL` — e.g. `BAAI/bge-base-en-v1.5` (768-dim) or `text-embedding-3-small` (1536-dim).
    - `EMBEDDINGS_DIM` — must match the model; checked against the schema's `vector(N)` at startup (hard-fail on mismatch).
    - `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_API_KEY` — OpenAI provider only; base URL allows any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, …).
    - `sentence-transformers` provider runs **in-process** in v1; a sidecar (e.g. HF `text-embeddings-inference`) is a documented upgrade path, not built.
  - **Compaction LLM (optional, required only when running the instruction compaction job from S4.6):**
    - `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` — any OpenAI-compatible endpoint.
  - **Auth:** shared bearer tokens configured out-of-band (see S3.5).
  - **Observability:** `LOG_LEVEL` and the standard `OTEL_*` variables (see S6.3).
- **S5.2** As an operator, `docker compose up` brings up Postgres + pgvector + LangMem locally for development.
- **S5.3** As an operator, a `helm` chart or k8s manifest is provided for shared deployment. *(stretch — could be v2.1)*
- **S5.4** As an operator, the server exposes `/healthz` and `/readyz`.
- **S5.5** As an operator, schema migrations run automatically on startup behind a flag, or via an explicit CLI command.
- **S5.6** As an agent developer, I get a one-line MCP config snippet to point Claude Code / Cursor at the server.

---

## E6 — Quality, safety, observability

- **S6.1** As a maintainer, every MCP tool has integration tests against a real Postgres (testcontainers), not mocks.
- **S6.2** As a maintainer, the test suite covers: save, search (semantic + filter), update, delete, project isolation, auth rejection.
- **S6.3** As an operator, every MCP call emits a **structured JSON log event** (one event per line, stdout) with fields: `timestamp`, `level`, `request_id`, `user_id`, `project_id`, `tool`, `latency_ms`, `result_status`, `trace_id`, `span_id`, plus free-form `extra` for tool-specific detail. Implemented via `structlog`. Log level is configurable via `LOG_LEVEL`. Log shipping/aggregation is out-of-scope; operators pipe stdout to whatever they use.
- **S6.3a** As an operator, **OpenTelemetry tracing** is wired via auto-instrumentation only — HTTP (Streamable HTTP MCP), `asyncpg`, and outbound HTTP (embeddings / LLM). No hand-rolled spans in v1. Exporter is **off by default**: tracing activates only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, with zero runtime cost otherwise. Custom metrics are deferred beyond v1. `trace_id` and `span_id` appear in every structured log line so logs and traces correlate whether or not exports are on.
- **S6.4** As an operator, I can dump a project's memories to JSON for backup / inspection.
- **S6.5** As the system, embeddings calls have a timeout and a single retry; failure surfaces as a structured error, never a silent empty result.
- **S6.6** As a maintainer, CI runs lint + tests on every PR.
- **S6.7** As an operator, a garbage-collection job (CLI command, run on demand or on a schedule) reviews memories and can: (a) delete entries the agent never re-reads, (b) flag near-duplicates for merge, (c) demote a global memory to a specific project if its content turned out to be project-specific, (d) run the instruction-compaction pass from S4.6. v1 ships the delete + duplicate-flag + compaction pieces; LLM-driven reclassification (c) can land later.
---

## What we are explicitly NOT building in v2

- Visibility hierarchy (personal/team/org)
- The 4 typed memory classes (Collection / Profile / Episodic / Procedural) as Python class hierarchy — replaced by `kind` field
- The `mcp/modules/` adapter layer
- Multiple MCP server entrypoints
- LiteLLM proxy (deferred; if we need LLM-driven instruction compaction, it goes in its own service)
- Per-user-private memories within a project (deferred to v3)
- Memory graph / relationships
- Temporal decay / forgetting
- A web UI

---

## Suggested next step

Once you've marked this up: I'll turn the agreed Epics into a sequenced delivery plan (which stories ship together, in what order), and only then start writing code.
