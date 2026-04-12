# Recall — V2 Requirements

## Document Control

| Field | Value |
|-------|-------|
| Version | 0.3 |
| Status | Draft — Complete |
| Author | LS / Claude |
| Created | 2026-04-12 |
| Last updated | 2026-04-12 |

## Change Log

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-04-12 | LS / Claude | Initial draft — structure only |
| 0.2 | 2026-04-12 | LS / Claude | Acceptance criteria for all stories |
| 0.2.1 | 2026-04-12 | LS / Claude | Testability fixes: immutable scope AC (1.4), snippet length default (2.5), ranking wording (2.2), tool description specificity (3.2), agent instructions example AC (5.1) |
| 0.3 | 2026-04-12 | LS / Claude | Merged hand-written REQUIREMENTS.md with skill-generated v2. Added Epics 3 (Self-Improving Instructions) and 5 (Project & Identity Scoping) with full ACs. Added Context, Design Principles, tool signature reference table, user_id field, anti-scope section, open questions. Renumbered epics. |

---

## Context

Recall (formerly LangMem v2) is a greenfield rewrite, not a refactor. LangMem v1 was a proof of concept — it works but is over-built: ~10k LOC, 30+ MCP tools, three parallel server entrypoints, layers wrapping layers. We are rewriting it as a focused product.

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

## Design Principles

1. **Few tools, broad tools.** The agent should not have to choose between 30 lookalikes. Target: at most 6 MCP tools total.
2. **Two scopes: project and global.** A memory is either bound to a `project_id` or marked `scope=global` (no project). Global is for facts that would still be true and useful in a brand-new empty repo tomorrow: user preferences, library/tool gotchas, cross-project lessons. No team/org hierarchy beyond this. Cross-project search across multiple specific projects is opt-in.
3. **Categories are data, not classes.** A memory has a `kind` field (`decision`, `episode`, `component`, `gotcha`, `instruction`, ...). Adding a kind is a config change, not a new class + module + endpoint.
4. **One server, one transport, one entrypoint.** No parallel implementations.
5. **The agent is the user.** Optimise tool descriptions and return shapes for LLM comprehension, not human ergonomics.
6. **Boring storage.** LangGraph `AsyncPostgresStore` + pgvector + OpenAI embeddings. No bespoke abstractions on top until proven necessary.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Memory** | A discrete unit of persistent knowledge stored by an agent — a decision, convention, gotcha, or any other fact worth remembering across sessions. |
| **Scope** | Whether a memory is bound to a specific project (`project`) or applies universally (`global`). |
| **Project ID** | An identifier for a codebase or repository context. All project-scoped memories are namespaced under a project ID. |
| **Kind** | A free-form category label on a memory (e.g., `decision`, `convention`, `gotcha`, `component`, `episode`, `instruction`). Data, not code — adding a kind requires no server changes. |
| **Embedding** | A vector representation of a memory's content, generated via an OpenAI-compatible API, used for semantic similarity search. |
| **MCP** | Model Context Protocol — the standard interface through which AI coding agents connect to external tool servers. |
| **Streamable HTTP** | The current MCP transport standard. A single HTTP endpoint that supports streaming responses. Replaces the older SSE transport. |
| **AsyncPostgresStore** | The LangGraph storage backend that Recall builds on. Provides key-value storage with vector search over Postgres + pgvector. |
| **pgvector** | A Postgres extension that adds vector similarity search capabilities. |
| **Agent** | An AI coding assistant (Claude Code, Cursor, etc.) that connects to Recall via MCP to store and retrieve memories. |
| **Operator** | The person who deploys, configures, and maintains the Recall server infrastructure. |
| **User ID** | An identifier for the human engineer directing an agent. Resolved per request; stored on each memory for provenance. Not part of the storage namespace — all users in a project see each other's memories. |
| **Instructions** | A special category of memory (`kind=instruction`) that agents read at session start and evolve over time. Layered: global instructions composed with project-level instructions. |

---

## Roles

| Role | Type | Description |
|------|------|-------------|
| **Agent** | Persistent | The AI coding assistant that calls Recall's MCP tools to store, search, update, and delete memories. The primary user of the system — tool design optimises for agent comprehension. |
| **Team Member** | Persistent | A human engineer who directs the agent. Indirectly interacts with Recall through natural-language instructions to the agent (e.g., "remember that we use event sourcing"). Does not call MCP tools directly. |
| **Operator** | Persistent | The engineer who deploys the Recall container, configures database connections and environment variables, monitors health, and runs migrations. Typically a DevOps or platform engineer. |

**Role relationships:** Team Members direct Agents; Agents call Recall. Operators manage the Recall infrastructure that Agents depend on. Multiple Team Members may share the same Recall instance, and their Agents see each other's memories within a project.

---

## Epic 1: Core Memory Store [Priority: High]

The foundational data layer. An agent can persist memories with scope, kind, and content, then update or remove them. Without this, nothing else functions.

### Story 1.1: Store a memory

**As an** agent,
**I want to** store a memory with a scope (project or global), kind, title, content, and optional tags,
**so that** the knowledge persists across sessions and machines.

**Memory record fields:** `id`, `scope` (`project` | `global`), `project_id` (non-null when `scope=project`, null when `scope=global`), `user_id`, `kind`, `title`, `content`, `tags[]`, `metadata{}`, `created_at`, `updated_at`, `embedding`.

**Acceptance Criteria:**

- Given a valid scope of `project`, a non-null project ID, a user ID, a kind, a title, and content, when I call the store operation, then a memory is persisted and an ID is returned.
- Given a valid scope of `global` and no project ID, a user ID, a kind, a title, and content, when I call the store operation, then a memory is persisted and an ID is returned.
- Given a scope of `project` and optional tags provided as a list of strings, when I call the store operation, then the tags are stored alongside the memory.
- Given a missing required field (scope, kind, title, or content), when I call the store operation, then the request is rejected with a structured error identifying the missing field.
- Given a kind value not in the default vocabulary, when I call the store operation, then the memory is stored successfully — kind is free-form with no server-side validation against a fixed list.
- Given a valid request, when the memory is stored, then `user_id`, `created_at`, and `updated_at` are set automatically.

**Notes:** The scope decision rule — "if this fact would still be true and useful in a brand-new empty repo tomorrow, save it as global; otherwise project" — is conveyed through the tool description (see Story 4.2), not enforced by the server. The agent decides autonomously. When in doubt, prefer project (narrower scope).

---

### Story 1.2: Scope invariant enforcement

**As the** system,
**I want to** enforce that project-scoped memories always have a project ID and global-scoped memories never do,
**so that** the namespace model remains consistent and no memory exists in an ambiguous state.

**Acceptance Criteria:**

- Given a store request with `scope=project` and a non-null project ID, when the request is processed, then the memory is stored successfully.
- Given a store request with `scope=project` and a null or missing project ID, when the request is processed, then the request is rejected with an error indicating that project scope requires a project ID.
- Given a store request with `scope=global` and no project ID, when the request is processed, then the memory is stored successfully.
- Given a store request with `scope=global` and a non-null project ID, when the request is processed, then the request is rejected with an error indicating that global scope must not have a project ID.
- Given a store request with a scope value other than `project` or `global`, when the request is processed, then the request is rejected with an error indicating the invalid scope.
- Given the database schema, when inspected, then a CHECK constraint enforces `(scope='project' AND project_id IS NOT NULL) OR (scope='global' AND project_id IS NULL)`.

---

### Story 1.3: Embedding generation on save

**As the** system,
**I want to** generate a vector embedding when a memory is stored or its content is updated,
**so that** memories are immediately discoverable via semantic search.

**Acceptance Criteria:**

- Given a new memory is stored with content, when the store operation completes, then an embedding vector is generated from the content and persisted alongside the memory.
- Given an existing memory whose content is updated, when the update operation completes, then a new embedding is generated from the updated content, replacing the previous embedding.
- Given an existing memory whose tags or metadata are updated but content is unchanged, when the update operation completes, then the existing embedding is not regenerated.
- Given the embedding API is unreachable or times out (within a configured timeout), when a store or update is attempted, then the operation fails with a structured error — the memory is not stored with a missing embedding.
- Given the embedding API returns an error, when a store or update is attempted, then the system retries once; if the retry also fails, the operation fails with a structured error.

---

### Story 1.4: Update a memory

**As an** agent,
**I want to** update the content, tags, or metadata of an existing memory by ID,
**so that** I can refine knowledge as understanding evolves without creating duplicates.

**Acceptance Criteria:**

- Given an existing memory ID and new content, when I call the update operation, then the content is replaced and `updated_at` is set to the current timestamp.
- Given an existing memory ID and new tags, when I call the update operation, then the tags are replaced.
- Given an existing memory ID and new metadata, when I call the update operation, then the metadata is merged or replaced.
- Given an existing memory ID and only tags provided (no content change), when I call the update operation, then the content and embedding remain unchanged.
- Given a memory ID that does not exist, when I call the update operation, then the request is rejected with a structured error indicating the memory was not found.
- Given an update request with no fields to update (empty payload), when I call the update operation, then the request is rejected with a structured error indicating no changes were provided.
- Given an update request that attempts to change scope or project ID, when I call the update operation, then the request is rejected with a structured error indicating these fields are immutable.

**Notes:** Scope and project ID are immutable after creation. Kind and title may be updatable (design decision to be confirmed at implementation).

---

### Story 1.5: Delete a memory

**As an** agent,
**I want to** delete a memory by ID,
**so that** outdated or incorrect knowledge is removed and no longer surfaces in search results.

**Acceptance Criteria:**

- Given an existing memory ID, when I call the delete operation, then the memory (including its embedding) is permanently removed.
- Given a deleted memory's ID, when I subsequently search or retrieve, then the memory does not appear in any results.
- Given a memory ID that does not exist, when I call the delete operation, then the operation succeeds idempotently (no error).

---

## Epic 2: Memory Retrieval & Search [Priority: High]

The primary value delivery. Agents find relevant memories through semantic search, with project and global results merged in a single ranked list. This is what makes stored knowledge useful.

### Story 2.1: Semantic search

**As an** agent,
**I want to** search memories by a natural-language query using vector similarity,
**so that** I can find relevant knowledge without needing to know exact titles or IDs.

**Acceptance Criteria:**

- Given a project ID and a natural-language query, when I call the search operation, then results are returned ranked by semantic similarity to the query.
- Given a query that closely matches the content of a stored memory, when I search, then that memory appears in the top results.
- Given a query with no semantically similar memories, when I search, then an empty result list is returned (not an error).
- Given an optional `limit` parameter, when I search, then at most `limit` results are returned. When `limit` is omitted, a sensible default is used.

---

### Story 2.2: Merged project and global results

**As an** agent,
**I want to** receive both project-scoped and global memories in a single ranked result list when searching within a project,
**so that** I get complete context without making separate calls for each scope.

**Acceptance Criteria:**

- Given a search with a project ID, when results are returned, then both project-scoped memories (matching that project ID) and global-scoped memories are included in a single list.
- Given a search result list, when inspecting each result, then each result includes a `scope` field indicating whether it is `project` or `global`.
- Given a project-scoped memory and a global-scoped memory with equal semantic similarity to the query, when results are ranked, then the project-scoped memory ranks higher (project results get a tie-breaking boost).
- Given a global memory whose content closely matches the query and a project memory whose content is only loosely related, when results are ranked, then the global memory ranks higher — the project boost is a tie-breaker, not an override of relevance.

---

### Story 2.3: Search filtering

**As an** agent,
**I want to** filter search results by kind, tags, scope, and/or user ID,
**so that** I can narrow results to the type of knowledge I need right now.

**Acceptance Criteria:**

- Given a search with `kind=decision`, when results are returned, then only memories with `kind=decision` are included.
- Given a search with one or more tags, when results are returned, then only memories that have at least one of the specified tags are included.
- Given a search with `scope=project`, when results are returned, then only project-scoped memories are included (global memories are excluded).
- Given a search with `scope=global`, when results are returned, then only global-scoped memories are included.
- Given a search with a `user_id` filter, when results are returned, then only memories created by that user are included.
- Given a search with multiple filters (e.g., `kind=convention` and `scope=project`), when results are returned, then all filters are applied conjunctively (AND).
- Given a search with no filters (only a query and project ID), when results are returned, then all scopes and kinds are included (default: unfiltered).

---

### Story 2.4: Retrieve a memory by ID

**As an** agent,
**I want to** fetch the full record of a specific memory by its ID,
**so that** I can read the complete content after finding it via search (which returns snippets only).

**Acceptance Criteria:**

- Given a valid memory ID, when I call the get operation, then the full memory record is returned including: ID, scope, project ID (if project-scoped), user ID, kind, title, content, tags, metadata, created_at, and updated_at.
- Given a memory ID that does not exist, when I call the get operation, then a structured error is returned indicating the memory was not found.

---

### Story 2.5: Snippet-based search results

**As an** agent,
**I want to** receive short snippets (not full content) in search results,
**so that** my context window stays small and I can decide which memories to read in full.

**Acceptance Criteria:**

- Given a search result, when inspecting a result item, then it includes: ID, scope, kind, title, a content snippet, and a similarity score.
- Given a memory with content longer than the configured maximum snippet length (default: 200 characters), when it appears in search results, then the content is truncated to that limit (not the full content).
- Given a memory with content shorter than the maximum snippet length, when it appears in search results, then the full content is returned as the snippet (no padding or alteration).

---

## Epic 3: Self-Improving Instructions [Priority: High]

The procedural-memory idea from v1, simplified. Instructions are **layered**: a global "how this user likes to work" layer composed with a project-level "how to behave in this repo" layer. The agent reads the composed result at session start and proposes edits to either layer over time. This is the 6th MCP tool and a key differentiator.

### Story 3.1: Retrieve composed instructions

**As an** agent,
**I want to** call `instructions_get(project_id)` at the start of a session and receive layered instructions (global first, then project),
**so that** I have both cross-project user preferences and repo-specific rules in my working context from the outset.

**Acceptance Criteria:**

- Given global-scoped instruction memories exist and project-scoped instruction memories exist for the given project ID, when I call `instructions_get(project_id)`, then the response contains both layers concatenated: global instructions first, project instructions second.
- Given the returned instructions, when inspected, then clear section markers separate the global layer from the project layer, so both the agent and a human reviewer can tell them apart.
- Given multiple instruction memories in a single layer, when the layer is composed, then instructions are ordered by recency (most recent last) or by a `priority` metadata field if present.
- Given no instruction memories exist (neither global nor for the project), when I call `instructions_get(project_id)`, then an empty response is returned (not an error).
- Given only global instruction memories exist (none for the project), when I call `instructions_get(project_id)`, then only the global layer is returned.
- Given only project instruction memories exist (no global), when I call `instructions_get(project_id)`, then only the project layer is returned.

---

### Story 3.2: Store an instruction memory

**As an** agent,
**I want to** save a durable lesson as `kind=instruction` via `memory_save`, choosing global scope for user/workflow preferences and project scope for repo-specific rules,
**so that** the instruction is included in future `instructions_get` responses.

**Acceptance Criteria:**

- Given I save a memory with `kind=instruction` and `scope=global`, when I subsequently call `instructions_get(project_id)` for any project, then that instruction appears in the global layer of the response.
- Given I save a memory with `kind=instruction` and `scope=project` for project X, when I call `instructions_get` for project X, then that instruction appears in the project layer.
- Given I save a memory with `kind=instruction` and `scope=project` for project X, when I call `instructions_get` for a different project Y, then that instruction does not appear.
- Given a saved instruction, when I update its content via `memory_update`, then the next call to `instructions_get` reflects the updated content.
- Given a saved instruction, when I delete it via `memory_delete`, then the next call to `instructions_get` no longer includes it.

**Notes:** Instructions use the same `memory_save` / `memory_update` / `memory_delete` tools as any other memory. The `kind=instruction` value is what identifies them; `instructions_get` filters on this kind. Same scope decision rule as Story 1.1: "user wants terse PR descriptions" is global; "always run `make fmt` before commit in this repo" is project.

---

### Story 3.3: Project instructions override global

**As an** agent,
**I want to** project-level instructions to take precedence over global instructions when they conflict,
**so that** repo-specific rules can override general preferences without requiring the global instruction to be deleted.

**Acceptance Criteria:**

- Given a global instruction stating "use tabs for indentation" and a project instruction stating "use spaces for indentation", when I call `instructions_get` for that project, then both instructions are returned with the project instruction appearing after the global instruction (project layer follows global layer).
- Given the layered ordering (global first, project second), when the agent processes the instructions, then later instructions naturally override earlier ones — the project layer has the last word.

**Notes:** Conflict resolution is positional, not semantic. The system does not detect contradictions — it relies on the agent processing instructions in order, where later entries override earlier ones. This is the simplest mechanism that works.

---

### Story 3.4: Operator curation of instructions

**As an** operator,
**I want to** review and curate instructions in either layer (remove stale entries, merge duplicates),
**so that** the instruction set stays clean and relevant over time.

**Acceptance Criteria:**

- Given instruction memories stored in the database, when an operator queries the database directly (SQL), then instruction memories are identifiable by `kind=instruction` and their scope/project ID.
- Given an operator identifies a stale instruction, when they delete or update it via direct database access or the MCP tools, then subsequent `instructions_get` calls reflect the change.
- Given the need for a management CLI, then this is deferred to a later story — initial curation is via direct DB access or the existing MCP tools.

---

### Story 3.5: Instruction compaction (deferred)

**As the** system,
**I want to** periodically merge and deduplicate instruction memories using an LLM,
**so that** the instruction set does not grow unboundedly.

**Acceptance Criteria:**

- This story is deferred to v2.1. No implementation in v2.
- Given this deferral, when the instruction set grows large, then the operator can curate manually (Story 3.4).

---

## Epic 4: MCP Server Interface [Priority: High]

The integration surface. Agents connect to Recall via MCP over Streamable HTTP. Tool descriptions are agent-oriented — they tell the LLM when and how to call each tool.

### Tool reference table

The following tools constitute the full MCP surface. This is the product interface — additions require updating this table and respecting the 6-tool budget.

| # | Tool | Parameters | Returns | Purpose |
|---|------|-----------|---------|---------|
| 1 | `memory_save` | `scope`, `project_id?`, `kind`, `title`, `content`, `tags?`, `metadata?` | `{id}` | Persist a new memory. `scope` is `"project"` or `"global"`. `project_id` required when `scope="project"`, forbidden when `scope="global"`. |
| 2 | `memory_search` | `project_id`, `query`, `kind?`, `tags?`, `scope?`, `user_id?`, `limit?` | `[{id, scope, kind, title, snippet, score}]` | Semantic search. Searches the given project **and** global by default; pass `scope` to restrict. |
| 3 | `memory_get` | `id` | Full memory record | Fetch the complete record for a memory found via search. |
| 4 | `memory_update` | `id`, `content?`, `tags?`, `metadata?` | `{id}` | Update an existing memory's content, tags, or metadata. |
| 5 | `memory_delete` | `id` | `{ok}` | Permanently remove a memory. |
| 6 | `instructions_get` | `project_id` | Layered instruction text | Retrieve composed global + project instructions for session start. |

---

### Story 4.1: Streamable HTTP transport

**As an** agent,
**I want to** connect to Recall via the Streamable HTTP MCP transport,
**so that** I can use standard MCP client libraries without custom integration code.

**Acceptance Criteria:**

- Given a running Recall server, when an MCP client connects via Streamable HTTP, then the connection is established and tools are discoverable.
- Given a connected MCP client, when it calls any Recall tool, then the request is processed and a response is returned over the same transport.
- Given the server, when inspecting its transport configuration, then only Streamable HTTP is supported — no SSE, stdio, or WebSocket transports are exposed.

---

### Story 4.2: Agent-oriented tool descriptions

**As an** agent,
**I want to** each MCP tool's description to tell me when to call it, what parameters to provide, and include a usage example,
**so that** I can use the tools correctly without external documentation.

**Acceptance Criteria:**

- Given the tool listing returned by the MCP server, when inspecting any tool, then its description includes: a one-sentence purpose, guidance on when to call it, and a parameter summary.
- Given the `memory_save` tool description, when inspecting it, then it includes the scope decision rule: "if this fact would still be true and useful in a brand-new empty repo tomorrow, save it as global; otherwise project."
- Given the `memory_search` tool description, when inspecting it, then it describes the default behaviour (project + global merged) and how to restrict with filters.
- Given any tool description, when inspected, then it lists all required and optional parameter names with their types and constraints.

**Notes:** Tool descriptions are prompts to the LLM — their quality directly impacts whether agents use the tools correctly. Treat description authoring as prompt engineering.

---

### Story 4.3: Structured error responses

**As an** agent,
**I want to** receive errors as structured objects with an error message and a recovery hint,
**so that** I can diagnose problems and retry or adjust my approach without human intervention.

**Acceptance Criteria:**

- Given any error condition (validation failure, not found, server error), when the error response is returned, then it contains at minimum an `error` field (human/agent-readable message) and a `hint` field (suggested recovery action).
- Given a validation error (e.g., missing required field), when the error is returned, then the `error` field identifies which field failed validation and `hint` suggests the correction.
- Given a not-found error (e.g., invalid memory ID), when the error is returned, then the `error` field states the ID was not found and `hint` suggests verifying the ID or searching first.
- Given an internal server error, when the error is returned, then the `error` field gives a general message (not a stack trace) and `hint` suggests retrying.

---

### Story 4.4: Tool budget

**As a** team member,
**I want to** the server to expose at most 6 MCP tools,
**so that** the agent's tool selection remains simple and accurate — fewer tools means fewer wrong choices.

**Acceptance Criteria:**

- Given the tool listing returned by the MCP server, when counting the tools, then there are at most 6 tools.
- Given any proposed addition of a new tool, when the total would exceed 6, then the addition is blocked until an existing tool is removed or merged.

**Notes:** This is a design constraint, not a runtime enforcement. It is validated by inspection and code review, not by the server rejecting tool registrations.

---

## Epic 5: Project & Identity Scoping [Priority: High]

Safe multi-tenant use across machines. Users are identified per request; projects are configured out-of-band. Authentication is deferred to Wave 2, but the identity and project model is established here.

### Story 5.1: User ID resolution

**As the** system,
**I want to** resolve a `user_id` for every incoming request,
**so that** each memory records who created it and search results can be filtered by author.

**Acceptance Criteria:**

- Given an incoming MCP request with a resolvable user identity (e.g., via a header or token), when the request is processed, then a `user_id` is associated with the request context.
- Given a memory is saved, when the record is persisted, then the `user_id` from the request context is stored on the memory record.
- Given an incoming request without a resolvable user identity, when the request is processed, then the request is rejected with a structured error indicating that a user identity is required.
- Given the `user_id` is stored on a memory, when the memory is retrieved via `memory_get`, then the `user_id` is included in the returned record.

**Notes:** In Wave 1 (trusted network), user ID resolution may be as simple as a required header (e.g., `X-User-ID`). Full authentication (bearer tokens, OIDC, mTLS) is deferred to Wave 2 (see Story 5.6).

---

### Story 5.2: Cross-machine visibility

**As a** team member on machine A,
**I want to** memories I save to be visible to my agent on machine B for the same project,
**so that** I can switch machines without losing context.

**Acceptance Criteria:**

- Given a memory saved with `project_id=X` from machine A, when a search is performed with `project_id=X` from machine B, then the memory appears in the results.
- Given a memory saved with `scope=global` from machine A, when `instructions_get` or a global search is performed from machine B, then the memory is accessible.
- Given two different users in the same project, when either user searches, then memories from both users are visible by default.

---

### Story 5.3: Project configuration

**As an** operator,
**I want to** configure projects out-of-band (config file or database table),
**so that** agents can reference a known project ID and the system can validate it.

**Acceptance Criteria:**

- Given a project is configured in the system, when an agent passes that project ID on an MCP call, then the call succeeds.
- Given a project ID that is not configured, when an agent passes it on an MCP call that requires a project, then the call is rejected with a structured error indicating the unknown project.
- Given the project configuration, when an operator inspects it, then each project has at minimum an ID and a display name.

**Notes:** Initial implementation may accept any project ID string without pre-registration (implicit project creation). Strict project validation can be a follow-up if needed. The design should support either approach.

---

### Story 5.4: Storage namespace

**As the** system,
**I want to** the storage namespace to be `(scope, project_id)`,
**so that** project isolation is enforced at the storage layer and global memories are cleanly separated.

**Acceptance Criteria:**

- Given a project-scoped memory, when it is stored, then it is namespaced under `("project", "<project_id>")`.
- Given a global-scoped memory, when it is stored, then it is namespaced under `("global", null)`.
- Given two different projects, when memories are stored in each, then a search in one project never returns memories from the other project (only from that project and global).
- Given the namespace design, when reviewed, then `user_id` is a column on the memory record, not part of the namespace — all users in a project share the same namespace.

---

### Story 5.5: Global-name rejection

**As the** system,
**I want to** reject any project configuration that tries to register a project named `global` (case-insensitive),
**so that** the scope vocabulary remains unambiguous.

**Acceptance Criteria:**

- Given a project configuration attempt with ID `global`, when the configuration is processed, then it is rejected with an error indicating that `global` is a reserved name.
- Given a project configuration attempt with ID `Global`, `GLOBAL`, or any case variation, when the configuration is processed, then it is rejected (case-insensitive check).

---

### Story 5.6: Authentication (deferred to Wave 2)

**As an** operator,
**I want to** configure authentication for the Recall server,
**so that** only authorised users can access the memory store.

**Acceptance Criteria:**

- This story is deferred to Wave 2. V2 assumes a trusted network.
- Given this deferral, when the system is deployed in V2, then user ID resolution (Story 5.1) operates without cryptographic authentication.

**Notes:** Authentication options under consideration: shared bearer tokens per user (simplest), OIDC (cleaner but heavier), or mTLS. Decision to be made before Wave 2 implementation.

---

## Epic 6: Deployment & Operations [Priority: High]

Makes Recall runnable as shared team infrastructure. A single container, environment-based configuration, automatic migrations, and health endpoints.

### Story 6.1: Single-container deployment

**As an** operator,
**I want to** deploy Recall as a single Docker container configured via environment variables,
**so that** I can add it to our existing Docker Compose or Kubernetes setup without new infrastructure.

**Acceptance Criteria:**

- Given a Dockerfile in the repository, when built, then it produces a single container image that runs the Recall server.
- Given the container is started with `DATABASE_URL` and `OPENAI_API_KEY` environment variables set, when it starts, then the server begins accepting MCP connections.
- Given the container is started without `DATABASE_URL`, when it starts, then it exits with a clear error message indicating the missing configuration.
- Given the container image, when inspected, then it contains no bundled database — Recall connects to an external Postgres instance.

---

### Story 6.2: Database migrations

**As an** operator,
**I want to** run schema migrations via a CLI command or automatically on server startup,
**so that** the database schema stays in sync with the server version without manual SQL.

**Acceptance Criteria:**

- Given a fresh Postgres database with pgvector enabled, when `recall db migrate` is run, then the full schema is created (tables, indexes, constraints).
- Given an existing database from a prior version, when `recall db migrate` is run, then only missing migrations are applied; existing data is preserved.
- Given the server is started with an auto-migrate flag or environment variable, when it starts, then migrations run automatically before accepting connections.
- Given migrations have already been applied, when `recall db migrate` is run again, then it completes successfully with no changes (idempotent).

---

### Story 6.3: Health check endpoints

**As an** operator,
**I want to** the server to expose `/healthz` and `/readyz` endpoints,
**so that** container orchestrators and monitoring tools can verify the server is running and ready to serve.

**Acceptance Criteria:**

- Given a running Recall server, when `GET /healthz` is called, then it returns HTTP 200 indicating the process is alive.
- Given a running Recall server with a healthy database connection, when `GET /readyz` is called, then it returns HTTP 200 indicating readiness to serve requests.
- Given a running Recall server with a broken database connection, when `GET /readyz` is called, then it returns HTTP 503 indicating the server is not ready.
- Given the health endpoints, when called, then they respond within 1 second (they must not perform expensive operations).

---

### Story 6.4: Environment-based configuration

**As an** operator,
**I want to** configure Recall entirely through environment variables (`DATABASE_URL`, `OPENAI_API_KEY`, etc.),
**so that** I can use standard secrets management and deployment tooling without config files.

**Acceptance Criteria:**

- Given `DATABASE_URL` set to a valid Postgres connection string, when the server starts, then it connects to that database.
- Given `OPENAI_API_KEY` set to a valid API key, when the server generates embeddings, then it authenticates with that key.
- Given an optional `OPENAI_BASE_URL` variable, when set, then embedding requests are sent to that base URL (supporting OpenAI-compatible endpoints).
- Given an optional `RECALL_HOST` and `RECALL_PORT` variable, when set, then the server binds to that host and port. When unset, sensible defaults are used.
- Given a required environment variable is missing, when the server starts, then it exits immediately with an error listing all missing required variables.

---

### Story 6.5: Local development with Docker Compose

**As an** operator,
**I want to** run `docker compose up` to bring up Postgres + pgvector + Recall locally,
**so that** developers can run the full stack for testing without external dependencies.

**Acceptance Criteria:**

- Given the `docker-compose.yml` in the repository, when `docker compose up` is run, then Postgres (with pgvector), and the Recall server start and connect to each other.
- Given the Compose stack is running, when an MCP client connects to the Recall server's exposed port, then it can call tools successfully.
- Given a fresh clone of the repository, when `docker compose up` is run with no prior setup, then the stack starts successfully (migrations run automatically).

---

## Epic 7: Agent Integration Guidance [Priority: Medium]

The last mile. Recall is useless if agents don't know when to store and retrieve memories. This epic ships reference instructions and configuration snippets that teams adapt for their agents.

### Story 7.1: Reference agent instructions

**As a** team member,
**I want to** a set of reference instructions (e.g., sample CLAUDE.md snippet, skill definitions) that teach my agent when and how to use Recall's memory tools,
**so that** memory usage is consistent and proactive rather than ad-hoc.

**Acceptance Criteria:**

- Given the shipped reference instructions, when inspected, then they include guidance on when to store memories (after learning a durable fact, convention, or decision).
- Given the shipped reference instructions, when inspected, then they include guidance on when to retrieve memories (before starting implementation, when encountering a decision point, when context seems relevant).
- Given the shipped reference instructions, when inspected, then they include the scope decision rule for choosing between project and global.
- Given the reference instructions, when inspected, then they include at least one concrete example of a store call and one concrete example of a search call with realistic parameters.

**Notes:** The reference instructions are documentation shipped with the project, not server-side behaviour. Their effectiveness depends on agent prompt handling, which varies by agent.

---

### Story 7.2: MCP connection configuration snippet

**As a** team member,
**I want to** a one-line MCP configuration snippet per supported agent (Claude Code, Cursor, etc.),
**so that** connecting my agent to Recall is copy-paste simple.

**Acceptance Criteria:**

- Given the project documentation, when a team member looks up connection setup, then a ready-to-use MCP configuration snippet is provided for Claude Code.
- Given the configuration snippet, when pasted into the agent's MCP settings with only the server URL customised, then the agent can connect to Recall and discover its tools.
- Given additional agents are supported (e.g., Cursor), when a team member looks up connection setup, then a snippet is provided for each supported agent.

---

## Cross-Cutting Concerns

### Scope isolation

- Project-scoped memories are never visible outside their project. There is no cross-project leakage.
- The storage namespace is `(scope, project_id)`. This is the only dimension of isolation in V2.

### Testing

- All MCP tools have integration tests against a real Postgres instance via testcontainers.
- No mocking of the database layer. The test suite covers: store, search (semantic + filter), update, delete, scope isolation, auth rejection.

### Observability

- Every MCP tool call is logged with: request ID, user ID, project ID, tool name, latency (ms), result status.
- Embedding API calls have a timeout and a single retry; failure surfaces as a structured error, never a silent empty result.

### Security

- Authentication and access control are deferred to Wave 2 (see Story 5.6). V2 assumes a trusted network.
- No memory content is logged at INFO level or above.

### Data integrity

- The scope invariant (`project` + project_id, or `global` + no project_id) is enforced at the database level (CHECK constraint), not just application code.

### JSON export

- An operator can dump a project's memories to JSON for backup or inspection.

### CI

- CI runs lint (`ruff`), type checking (`mypy --strict`), and tests (`pytest`) on every PR.

### Garbage collection

- A garbage-collection job (CLI command, run on demand or on a schedule) reviews `scope=global` memories and can: (a) delete entries the agent never re-reads, (b) flag near-duplicates for merge. LLM-driven reclassification (demoting a global memory to project-specific) is deferred to v2.1.

---

## What We Are NOT Building in V2

- **Visibility hierarchy** (personal/team/org) — two scopes only: project and global.
- **Typed memory classes** (Collection / Profile / Episodic / Procedural as Python class hierarchy) — replaced by the `kind` field.
- **The `mcp/modules/` adapter layer** — no wrapping layers.
- **Multiple MCP server entrypoints** — one server, one transport, one entrypoint.
- **LiteLLM proxy** — deferred; if we need LLM-driven instruction compaction, it goes in its own service.
- **Per-user-private memories within a project** — deferred to v3.
- **Memory graph / relationships** between memories.
- **Temporal decay / forgetting** — no time-decay scoring.
- **Summarisation of episodes** — no automatic episode summarisation.
- **A web UI** — no admin interface in v2.
- **Multi-strategy retrieval** (graph traversal, BM25, reranking) — semantic search via pgvector only.
- **Multiple transports** (SSE, stdio, WebSocket) — Streamable HTTP only.
- **Distributed / multi-node deployment** — single container.
- **Bulk memory seeding / import** — deferred.
- **Memory expiry / TTL** — deferred.

---

## Open Questions

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 1 | **Auth mechanism (Story 5.6):** shared bearer tokens per user, OIDC, or mTLS? | Open | Shared bearer tokens are simplest for a small team. Decision needed before Wave 2. |
| 2 | **Cross-project search:** strictly off, or opt-in via `project_ids: [...]`? | Open | Currently off. Opt-in could be added as a filter parameter on `memory_search`. |
| 3 | **LLM-driven instruction compaction:** in v2 or v2.1? | Resolved | Deferred to v2.1 (Story 3.5). |
| 4 | **`kind` vocabulary:** is `decision / episode / component / gotcha / pattern / instruction` the right starting set? | Open | Free-form with documented vocabulary. Team can adjust without server changes. |
| 5 | **Tool count — merge `memory_get` into `memory_search`?** | Resolved | Keeping separate. `memory_search` returns snippets; `memory_get` returns full records. Clearer contract. |
| 6 | **`memory_list_kinds(project_id)` — should agents discover what kinds exist?** | Open | Could be noise. May be better as a metadata query on `memory_search`. Defer unless demand arises. |
| 7 | **Instructions scope:** project-scoped vs user-scoped vs both? | Resolved | Both — global layer for user preferences, project layer for repo rules. Per-user-private instructions deferred to v3. |
| 8 | **Streamable HTTP as sole transport?** | Resolved | Confirmed. No stdio, no SSE shim. |

---

## Wave 2 — Operational Confidence (Future)

Features deferred from V2 core but planned for the next iteration. Included here for context; these are not in scope for V2 delivery.

| # | Feature | Summary |
|---|---------|---------|
| W2.1 | List memories with filtering | Filter and browse memories by scope, category, date range |
| W2.2 | Authentication & access control | Bearer tokens, OIDC, or mTLS — mechanism TBD (see Open Question 1 / Story 5.6) |
| W2.3 | Memory provenance | Metadata about who stored a memory and when, for auditability |
| W2.4 | Instruction compaction | LLM-driven merge/dedup of instruction memories (Story 3.5) |
| W2.5 | GC reclassification | LLM-driven demotion of global memories to project-specific |

---

## Wave 3+ — Future

Features identified during discovery but explicitly deferred. Not planned for near-term delivery.

| # | Feature | Summary |
|---|---------|---------|
| W3.1 | Bulk memory seeding (import) | Import memories from a file for initial project setup |
| W3.2 | Memory expiry / TTL | Auto-expire stale memories after a configurable period |
| W3.3 | Admin UI | Web interface to inspect and manage stored memories |
| W3.4 | Multi-project dashboard | Overview of all projects, memory counts, health |
| W3.5 | Per-user-private memories | Privacy scoping within a shared project |
| W3.6 | Memory graph / relationships | Linking related memories together |

---

## Next Steps

1. Review and approve this merged requirements document (v0.3).
2. Run `/kickoff docs/requirements/v2-requirements.md` to produce HLD, ADRs, and implementation plan.
3. Sequence epics into delivery milestones — Epics 1 and 2 first (core value), then 3-6 in parallel tracks, Epic 7 last.
4. Create GitHub issues from stories, grouped by epic.
