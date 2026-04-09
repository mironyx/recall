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

### What it does
Gives those agents persistent, project-scoped memory across sessions and machines: architectural decisions, gotchas learned the hard way, how a component currently works, and self-improving instructions for the agent itself.

### Hard constraints
- **MCP transport:** Streamable HTTP (the current MCP standard). The old SSE-via-intermediate-service shim goes away.
- **Multi-user, multi-machine:** server is shared infrastructure, not local-only.
- **Postgres + pgvector** as the storage backend (keep what works from v1).

---

## Design principles

1. **Few tools, broad tools.** The agent should not have to choose between 30 lookalikes. Target: ≤ 6 MCP tools total.
2. **Two scopes: project and global.** A memory is either bound to a `project_id` or marked `scope=global` (no project). Global is for facts that would still be true and useful in a brand-new empty repo tomorrow: user preferences, library/tool gotchas, cross-project lessons. No team/org hierarchy beyond this. Cross-project search across multiple specific projects is opt-in.
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

- **S1.1** As the system, I store a memory record with: `id`, `scope` (`project` | `global`), `project_id` (non-null when `scope=project`, null when `scope=global`), `user_id`, `kind`, `title`, `content`, `tags[]`, `metadata{}`, `created_at`, `updated_at`, `embedding`.
- **S1.2** As the system, I generate embeddings on save and on content update only (not on metadata-only updates).
- **S1.3** As a caller, when I search with a `project_id`, results from that project **and** from `scope=global` are returned in a single ranked list, each result tagged with its scope. Project hits get a small ranking boost so they win ties; a high-confidence global hit can still outrank a weak project hit. Optional filters: `kind`, `tags`, `user_id`, and `scope` (to restrict to only `project` or only `global`).
- **S1.4** As a caller, I can fetch a memory by `id`.
- **S1.5** As a caller, I can update `content`, `tags`, `metadata` of a memory by `id`.
- **S1.6** As a caller, I can delete a memory by `id`.
- **S1.7** As the system, I enforce a CHECK constraint: `(scope='project' AND project_id IS NOT NULL) OR (scope='global' AND project_id IS NULL)`. No other combinations.
- **S1.8** As the agent, I decide at save time whether a memory is project-scoped or global, guided by the rule in the `memory_save` tool description: *"If this fact would still be true and useful in a brand-new empty repo tomorrow, save it as global; otherwise project."* When in doubt, prefer project (narrower scope). The agent makes this call autonomously — no user confirmation required. A future garbage-collection pass (see E6) can reclassify or prune.
- **S1.9** As an operator, I can run `langmem db migrate` to create/upgrade the schema.

**Out of scope (v2):** graph relationships between memories, time-decay scoring, summarization of episodes.

---

## E2 — Agent-facing MCP surface

**Goal:** ≤ 6 MCP tools, each with a clear purpose the LLM picks correctly without a manual.

Proposed tools:

1. **`memory_save`** — `(scope, project_id?, kind, title, content, tags?, metadata?)` → `{id}`. `scope` is `"project"` or `"global"`. `project_id` is required when `scope="project"` and forbidden when `scope="global"`. The tool description carries the decision rule: *"global = still true in a brand-new empty repo tomorrow; project = otherwise. When in doubt, project."*
2. **`memory_search`** — `(project_id, query, kind?, tags?, scope?, limit?)` → `[{id, scope, kind, title, snippet, score}]`. Searches the given project **and** global by default; pass `scope="project"` or `scope="global"` to restrict.
3. **`memory_get`** — `(id)` → full record
4. **`memory_update`** — `(id, content?, tags?, metadata?)` → `{id}`
5. **`memory_delete`** — `(id)` → `{ok}`
6. **`instructions_get`** — `(project_id)` → layered self-improving instructions: global user-level instructions composed with project-level instructions (see E4)

- **S2.1** As the agent, every tool's description tells me *when to call it* and gives one example. Tool descriptions are the API docs.
- **S2.2** As the agent, `kind` is a free-form string with a documented vocabulary (`decision`, `episode`, `component`, `gotcha`, `pattern`, `instruction`). I can introduce a new kind without server changes.
- **S2.3** As the agent, search results return short snippets, not full content, to keep my context window small. I call `memory_get` for the full record.
- **S2.4** As the system, all tools are exposed via **Streamable HTTP MCP transport** — no SSE shim.
- **S2.5** As the agent, errors come back as structured `{error, hint}` so I can recover.

**Open question:** do we need `memory_list_kinds(project_id)` so the agent can discover what's been stored? Or is that noise?

---

## E3 — Project & identity scoping

**Goal:** safe multi-tenant use across machines.

- **S3.1** As an operator, I configure projects out-of-band (config file or `projects` table). Agents pass `project_id` on every call.
- **S3.2** As the system, I authenticate the caller and resolve a `user_id` per request (mechanism in S3.5).
- **S3.3** As a user on machine A, memories I save are visible to my agent on machine B for the same `project_id`.
- **S3.4** As a user, memories saved by other users in the same project are visible to me by default. (Per-user privacy is a v3 concern unless you push back.)
- **S3.5** As an operator, I configure auth via one of: shared bearer token per user, OIDC, or mTLS. **Decision needed — see open questions.**
- **S3.6** As the system, I reject any request without a resolvable `user_id`. A resolvable `project_id` is required for all calls **except** `memory_save` / `memory_search` / `memory_get` operating on `scope=global` records.
- **S3.7** As the system, the storage namespace is `(scope, project_id)`. Project rows live under `("project", "<id>")`; global rows live under `("global", null)`. `user_id` is a column, not part of the namespace. (Reverses ADR-0008's user-namespacing for procedural — see E4 discussion.)
- **S3.8** As the system, I reject any project config that tries to register a project named `global` (case-insensitive), to keep the scope vocabulary unambiguous.

---

## E4 — Self-improving instructions

**Goal:** the procedural-memory idea from v1, simplified. Instructions are **layered**: a global "how this user likes to work" layer composed with a project-level "how to behave in this repo" layer. The agent reads the composed result at session start and proposes edits to either layer over time.

- **S4.1** As the agent, at the start of a session I call `instructions_get(project_id)` and prepend the result to my working context. The returned blob is the global instructions layer concatenated with the project instructions layer, in that order (global first, project second so project can override).
- **S4.2** As the agent, when I learn a durable lesson, I save it as `kind=instruction` via `memory_save`, choosing `scope=global` for user/workflow preferences ("user wants terse PR descriptions") and `scope=project` for repo-specific rules ("always run `make fmt` before commit in this repo"). Same decision rule as S1.8.
- **S4.3** As the system, `instructions_get(project_id)` returns instructions from both `scope=global` and the given project, each layer ordered by recency or a `priority` metadata field, with clear section markers between the two layers so the agent (and a human reviewer) can tell them apart.
- **S4.4** As an operator, I can review and curate instructions in either layer (remove stale, merge duplicates) — initially via direct DB access; a CLI is a later story.
- **S4.5** As the agent, the global layer captures cross-project user preferences; the project layer captures repo-specific rules. Per-user-private instructions within a project remain deferred (v3). (This refines, rather than reverses, the ADR-0008 reversal.)

**Open question:** do we want an LLM-driven "instruction compactor" that periodically merges/dedupes instructions? v1 was reaching for this with the LiteLLM proxy. I'd defer it to v2.1 unless you want it in v2.

---

## E5 — Deployment & operations

**Goal:** one team can stand up one shared LangMem server.

- **S5.1** As an operator, I deploy LangMem as a single container with a `DATABASE_URL` and `OPENAI_API_KEY` (or compatible) env vars.
- **S5.2** As an operator, `docker compose up` brings up Postgres + pgvector + LangMem locally for development.
- **S5.3** As an operator, a `helm` chart or k8s manifest is provided for shared deployment. *(stretch — could be v2.1)*
- **S5.4** As an operator, the server exposes `/healthz` and `/readyz`.
- **S5.5** As an operator, schema migrations run automatically on startup behind a flag, or via an explicit CLI command.
- **S5.6** As an agent developer, I get a one-line MCP config snippet to point Claude Code / Cursor at the server.

---

## E6 — Quality, safety, observability

- **S6.1** As a maintainer, every MCP tool has integration tests against a real Postgres (testcontainers), not mocks.
- **S6.2** As a maintainer, the test suite covers: save, search (semantic + filter), update, delete, project isolation, auth rejection.
- **S6.3** As an operator, every MCP call is logged with `request_id`, `user_id`, `project_id`, `tool`, `latency_ms`, `result_status`.
- **S6.4** As an operator, I can dump a project's memories to JSON for backup / inspection.
- **S6.5** As the system, embeddings calls have a timeout and a single retry; failure surfaces as a structured error, never a silent empty result.
- **S6.6** As a maintainer, CI runs lint + tests on every PR.
- **S6.7** As an operator, a garbage-collection job (CLI command, run on demand or on a schedule) reviews `scope=global` memories and can: (a) delete entries the agent never re-reads, (b) flag near-duplicates for merge, (c) demote a global memory to a specific project if its content turned out to be project-specific. v2 ships the delete + duplicate-flag pieces; LLM-driven reclassification can land in v2.1.

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

## Open questions for you

1. **Auth (S3.5):** shared bearer tokens per user is the simplest thing that could work for a small team. OIDC is cleaner but heavier. Which way?
2. **Cross-project search:** strictly off, or opt-in via an explicit `project_ids: [...]` parameter?
3. **Instructions scope (E4):** project-scoped (my proposal) vs user-scoped (v1's ADR-0008) vs both with precedence? My read: project-scoped is what a team actually wants. Confirm?
4. **LLM-driven instruction compaction:** in v2 or defer to v2.1?
5. **`kind` vocabulary:** is `decision / episode / component / gotcha / pattern / instruction` the right starting set, or do you want different names?
6. **Tool count:** I proposed 6. Could plausibly drop to 5 by merging `memory_get` into `memory_search` (return full content when `limit=1` and an `id` filter is given). Cleaner or cuter?
7. **Streamable HTTP transport:** confirming this is the target — not stdio, not the old SSE-via-shim.
8. **Rewrite mechanics:** new repo, or `v2/` directory in this repo, or a `v2` branch that becomes `main`?

---

## Suggested next step

Once you've marked this up: I'll turn the agreed Epics into a sequenced delivery plan (which stories ship together, in what order), and only then start writing code.
