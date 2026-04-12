# Recall V2 — High-Level Design

**Version:** 1.0
**Date:** 2026-04-12
**Status:** Draft
**Requirements:** [docs/requirements/v2-requirements.md](../requirements/v2-requirements.md)

---

## Level 1 — Capabilities

Each capability maps to one or more requirement epics. Together they describe
what the system does at the boundary, without naming components or technology.

### C1. Persist structured memories

The system shall accept a memory record from an agent — comprising scope,
kind, title, content, optional tags, and optional metadata — and persist it
durably so that the same or a different agent session can retrieve it later.
Scope determines isolation: a memory is either bound to a specific project or
marked global. The scope invariant (project requires a project ID; global
forbids one) is enforced at both the application and database level.

Tags are stored as metadata on the record but are **not filterable** in v2
search. Tag-based filtering is deferred until a workable approach is
confirmed (see ADR-0004 amendment). This avoids the raw-SQL escape hatch and
keeps the "boring storage" principle intact.

**Covers:** Epic 1 (Stories 1.1, 1.2, 1.3), Epic 5 (Story 5.4)

### C2. Update and delete memories

The system shall allow an agent to modify the content, tags, or metadata of an
existing memory, or to permanently remove it. Scope and project ID are
immutable after creation. Content changes trigger re-embedding; metadata-only
changes do not.

**Covers:** Epic 1 (Stories 1.4, 1.5)

### C3. Discover memories by meaning

The system shall accept a natural-language query and return a ranked list of
semantically similar memories. When searching within a project, both
project-scoped and global memories are included by default, with project
results receiving a tie-breaking boost. Results are snippets (not full
content) to conserve the agent's context window; full records are available by
ID.

**Covers:** Epic 2 (Stories 2.1, 2.2, 2.4, 2.5)

### C4. Filter memories by structure

The system shall support narrowing search results by kind, scope, and
user ID. Filters compose conjunctively (AND). Combined with semantic ranking,
this lets the agent ask "show me decisions about authentication in this
project" without scanning everything. Tag filtering is deferred (see C1).

**Covers:** Epic 2 (Story 2.3)

### C5. Compose layered instructions

The system shall maintain instruction memories (a distinguished kind) at two
layers — global and per-project — and compose them on demand. The agent
calls `instructions_get` when it needs guidance (typically at session start,
but not exclusively — on-demand retrieval avoids polluting the context window
with instructions that may not be relevant to the current task). The global
layer provides user preferences; the project layer provides repo-specific
rules. Project instructions appear after global, giving them positional
precedence.

**Covers:** Epic 3 (Stories 3.1, 3.2, 3.3, 3.4)

### C6. Expose tools over MCP

The system shall present its capabilities as at most 6 MCP tools over the
Streamable HTTP transport. Tool descriptions are written for LLM
comprehension — they tell the agent when to call, what to pass, and include
the scope decision rule. Errors are structured objects with a message and a
recovery hint.

**Covers:** Epic 4 (Stories 4.1, 4.2, 4.3, 4.4)

### C7. Identify users and isolate projects

The system shall resolve a user identity on every request and record it on
each memory. All users within a project share the same memory namespace —
there is no per-user privacy within a project. Project IDs are validated
against the established character rules (ADR-0002). The reserved name
`global` (case-insensitive) is rejected as a project ID.

**Covers:** Epic 5 (Stories 5.1, 5.2, 5.3, 5.4, 5.5)

### C8. Deploy as shared infrastructure

The system shall run as a single Docker container, configured entirely via
environment variables, connecting to an external Postgres instance. Schema
migrations run via CLI or automatically on startup. Health endpoints
(`/healthz`, `/readyz`) support orchestrator probes. A Docker Compose file
enables local development with zero external dependencies.

**Covers:** Epic 6 (Stories 6.1, 6.2, 6.3, 6.4, 6.5)

### C9. Guide agent integration

The system shall ship reference instructions (e.g., sample CLAUDE.md
snippets, skill definitions) and MCP connection configuration snippets that
teach agents when and how to use Recall's tools. These ship as files in the
repository — they are not enforced by the server at runtime.

**Covers:** Epic 7 (Stories 7.1, 7.2)

### C10. Log every tool call

The system shall emit a structured log entry for every MCP tool invocation,
including request ID, user ID, project ID, tool name, latency (ms), and
result status. Memory content is never logged at INFO level or above.

**Covers:** Cross-cutting concern (Observability)

### ~~C11. Garbage-collect stale global memories~~ (deferred to v2.1)

Garbage collection of global memories (deleting unread entries, flagging
near-duplicates, LLM-driven reclassification) is deferred to v2.1. In v2,
operators curate memories manually via the MCP tools or direct DB access.

**Covers:** Cross-cutting concern (Garbage collection) — **deferred**

### C12. Export memories to JSON

The system shall allow an operator to dump a project's memories to JSON for
backup or inspection via a CLI command.

**Covers:** Cross-cutting concern (JSON export)

---

## Level 2 — Components

### Component diagram

```mermaid
graph TB
    Agent["Agent (MCP Client)"]

    subgraph Recall["Recall Server (single container)"]
        Transport["MCP Transport"]
        ToolRouter["Tool Router"]
        MemoryService["Memory Service"]
        InstructionService["Instruction Service"]
        EmbeddingClient["Embedding Client"]
        UserResolver["User Resolver"]
        Config["Configuration"]
        HealthEndpoints["Health Endpoints"]
        Migrations["Migration Runner"]
    end

    Postgres["Postgres + pgvector"]
    EmbeddingAPI["OpenAI-compatible Embedding API"]
    CLI["CLI (recall)"]

    Agent -->|Streamable HTTP| Transport
    Transport --> ToolRouter
    ToolRouter --> UserResolver
    ToolRouter --> MemoryService
    ToolRouter --> InstructionService
    MemoryService --> EmbeddingClient
    MemoryService --> Postgres
    InstructionService --> Postgres
    EmbeddingClient --> EmbeddingAPI
    HealthEndpoints --> Postgres
    Migrations --> Postgres
    Config -.->|env vars| Transport
    Config -.->|env vars| EmbeddingClient
    Config -.->|env vars| Postgres
    CLI --> Migrations
    CLI --> MemoryService
```

### MCP Transport

**Purpose:** Accept MCP connections from agents over Streamable HTTP.

**Responsibilities:**
- Listen on the configured host and port for Streamable HTTP connections
- Parse incoming MCP tool-call requests and dispatch to the Tool Router
- Serialise MCP responses (results and errors) back to the client
- Expose the server's tool listing with agent-oriented descriptions

**Non-responsibilities:**
- Does not authenticate requests (deferred to Wave 2)
- Does not implement SSE, stdio, or WebSocket transports
- Does not contain business logic — it is a protocol adapter

**Depends on:** Tool Router, Configuration

### Tool Router

**Purpose:** Map MCP tool names to service methods, threading cross-cutting
concerns (user resolution, validation, error formatting).

**Responsibilities:**
- Receive a parsed tool call and resolve the user identity via User Resolver
- Validate common parameters (scope, project_id format per ADR-0002)
- Dispatch to Memory Service or Instruction Service based on tool name
- Catch service exceptions and format them as structured MCP errors with
  `error` and `hint` fields
- Enforce the tool budget by being the single place where tools are registered
- Emit a structured log entry for every tool call (request ID, user ID,
  project ID, tool name, latency, result status) — see Architectural
  Invariants

**Non-responsibilities:**
- Does not own persistence logic
- Does not generate embeddings
- Does not know about the storage schema

**Depends on:** Memory Service, Instruction Service, User Resolver

### Memory Service

**Purpose:** Implement the core memory lifecycle — save, search, get, update,
delete.

**Responsibilities:**
- Persist memory records via `AsyncPostgresStore.aput` with the flat value
  schema (ADR-0001) and `(scope, project_id)` namespace (ADR-0002)
- Trigger embedding generation via Embedding Client when content is created
  or updated
- Execute semantic search via `AsyncPostgresStore.asearch`, merging project
  and global results with a project-scope tie-breaking boost
- Apply filters (kind, scope, user_id) via store filter operators (ADR-0004)
- Validate scope invariant (project ↔ project_id) at the application layer
- Truncate content to snippet length in search results
- Reject immutable-field changes (scope, project_id) on update

**Non-responsibilities:**
- Does not handle MCP protocol concerns
- Does not resolve user identity
- Does not own the instruction composition logic (that is Instruction Service)
- Does not manage database migrations

**Depends on:** Postgres (via AsyncPostgresStore), Embedding Client

### Instruction Service

**Purpose:** Compose layered instructions from global and project instruction
memories.

**Responsibilities:**
- Query the store for memories with `kind=instruction` in both the global and
  project namespaces
- Order instructions within each layer by recency (or priority metadata if
  present)
- Concatenate global layer then project layer with clear section markers
- Return the composed text (or empty string if no instructions exist)

**Non-responsibilities:**
- Does not store or delete instructions — that flows through Memory Service
  via `memory_save` / `memory_update` / `memory_delete` with `kind=instruction`
- Does not perform instruction compaction (deferred to v2.1)
- Does not detect semantic conflicts between layers

**Depends on:** Postgres (via AsyncPostgresStore)

### Embedding Client

**Purpose:** Generate vector embeddings for memory content via an
OpenAI-compatible API.

**Responsibilities:**
- Accept text content and return an embedding vector
- Authenticate with the configured API key
- Route requests to the configured base URL (supporting OpenAI-compatible
  endpoints)
- Implement a single retry on transient failure
- Raise a structured error if both attempts fail — never return silently
  without an embedding

**Non-responsibilities:**
- Does not decide when to embed — that is Memory Service's responsibility
- Does not store embeddings directly — `AsyncPostgresStore` handles that via
  its index configuration
- Does not cache embeddings

**Depends on:** OpenAI-compatible Embedding API (external), Configuration

### User Resolver

**Purpose:** Extract a user identity from each incoming request.

**Responsibilities:**
- Read the user identifier from the request (e.g., `X-User-ID` header in
  Wave 1)
- Reject requests with no resolvable user identity with a structured error
- Provide the resolved `user_id` to the Tool Router for propagation into
  service calls

**Non-responsibilities:**
- Does not authenticate the user (Wave 2)
- Does not manage user accounts or profiles
- Does not authorise — all authenticated users have equal access within a
  project

**Depends on:** Configuration

### Configuration

**Purpose:** Load and validate all runtime settings from environment variables.

**Responsibilities:**
- Read required variables (`DATABASE_URL`, `OPENAI_API_KEY`) and optional
  variables (`OPENAI_BASE_URL`, `RECALL_HOST`, `RECALL_PORT`)
- Fail fast on startup if required variables are missing, listing all missing
  variables in a single error message
- Provide typed, validated settings to all components that need them

**Non-responsibilities:**
- Does not read config files — environment variables only
- Does not watch for runtime config changes — settings are immutable after
  startup

**Depends on:** Nothing (leaf component)

### Health Endpoints

**Purpose:** Expose `/healthz` and `/readyz` for orchestrator probes.

**Responsibilities:**
- `/healthz` returns 200 if the process is alive
- `/readyz` returns 200 if the database connection is healthy; 503 otherwise
- Respond within 1 second — no expensive operations

**Non-responsibilities:**
- Does not expose metrics or detailed diagnostics
- Does not serve the MCP protocol — these are plain HTTP endpoints alongside
  the MCP transport

**Depends on:** Postgres (connection check only)

### Migration Runner

**Purpose:** Bring the database schema up to date.

**Responsibilities:**
- Invoke `AsyncPostgresStore.setup()` to run pending store and vector
  migrations
- Apply any Recall-specific migrations (e.g., CHECK constraints for the scope
  invariant) via a lightweight migration framework
- Expose as both a CLI command (`recall db migrate`) and an optional
  auto-migrate-on-startup mode
- Be idempotent — running twice changes nothing

**Non-responsibilities:**
- Does not manage data migrations (backfills)
- Does not handle down-migrations — schema changes are additive
- Does not bypass `AsyncPostgresStore.setup()` for store-owned tables

**Depends on:** Postgres, Configuration

### CLI

**Purpose:** Provide operator-facing commands for migration and export.

**Responsibilities:**
- `recall serve` — start the MCP server
- `recall db migrate` — run the Migration Runner
- `recall export <project_id>` — dump a project's memories to JSON via
  Memory Service

**Non-responsibilities:**
- Does not serve the MCP protocol (that is MCP Transport via `recall serve`)
- Does not implement GC (deferred to v2.1)

**Depends on:** Migration Runner, Memory Service, Configuration

### Architectural invariants

1. **Statelessness.** The server holds no per-client or per-machine state.
   All persistence is in Postgres. Any client connecting to the same database
   sees the same data, ensuring cross-machine visibility (Story 5.2).

2. **Structured logging.** Every MCP tool invocation is logged with:
   request ID, user ID, project ID, tool name, latency (ms), result status.
   Memory content is never logged at INFO level or above. Logging is the
   responsibility of the Tool Router (which sees all tool calls).

3. **Operator curation.** Operators may curate instruction memories and any
   other memories via the existing MCP tools or direct database access.
   No separate admin interface is provided in v2 (Story 3.4).

---

## Level 3 — Interactions

### Interaction 1: Save a memory (happy path)

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as MCP Transport
    participant R as Tool Router
    participant U as User Resolver
    participant M as Memory Service
    participant E as Embedding Client
    participant DB as Postgres

    A->>T: memory_save(scope, project_id, kind, title, content, tags?)
    T->>R: dispatch(memory_save, params)
    R->>U: resolve(request)
    U-->>R: user_id
    R->>R: validate scope + project_id format
    R->>M: save(scope, project_id, user_id, kind, title, content, tags)
    M->>M: enforce scope invariant
    M->>M: build flat value dict (ADR-0001)
    M->>E: embed(content)
    E-->>M: vector
    M->>DB: aput(namespace=(scope, pid), key=id, value=record, index=["content"])
    DB-->>M: ok
    M-->>R: {id}
    R-->>T: MCP result {id}
    T-->>A: {id}
```

**Contracts to pin at Level 4:**
- Flat value dict schema (field names, types, required vs optional)
- Namespace construction: `(scope, project_id)` with sentinel `"_"` for
  global (ADR-0002)
- Embedding field configuration: which value key is embedded
- Error response shape: `{error, hint}` structure

### Interaction 2: Search memories (project + global merge)

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as MCP Transport
    participant R as Tool Router
    participant U as User Resolver
    participant M as Memory Service
    participant DB as Postgres

    A->>T: memory_search(project_id, query, kind?, scope?, user_id?, limit?)
    T->>R: dispatch(memory_search, params)
    R->>U: resolve(request)
    U-->>R: user_id
    R->>M: search(project_id, query, filters, limit)
    M->>DB: asearch(namespace=("project", pid), query=query, filter=filters)
    DB-->>M: project_results
    M->>DB: asearch(namespace=("global", "_"), query=query, filter=filters)
    DB-->>M: global_results
    M->>M: merge + rank (project boost as tie-breaker)
    M->>M: truncate content to snippets
    M-->>R: [{id, scope, kind, title, snippet, score}]
    R-->>T: MCP result [...]
    T-->>A: [{id, scope, kind, title, snippet, score}]
```

**Contracts to pin at Level 4:**
- Merge algorithm: how the project tie-breaking boost is applied (additive
  score offset vs. positional preference at equal scores)
- Snippet truncation: max length, truncation strategy (character cut vs.
  sentence boundary)
- Filter translation: how `kind`, `scope`, `user_id` map to store filter
  dicts (ADR-0004)
- Default limit value

### Interaction 3: Retrieve composed instructions

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as MCP Transport
    participant R as Tool Router
    participant U as User Resolver
    participant I as Instruction Service
    participant DB as Postgres

    A->>T: instructions_get(project_id)
    T->>R: dispatch(instructions_get, params)
    R->>U: resolve(request)
    U-->>R: user_id
    R->>I: get_instructions(project_id)
    I->>DB: asearch(namespace=("global", "_"), filter={kind: "instruction"})
    DB-->>I: global_instructions
    I->>DB: asearch(namespace=("project", pid), filter={kind: "instruction"})
    DB-->>I: project_instructions
    I->>I: order each layer by recency
    I->>I: compose: global section + project section with markers
    I-->>R: composed_text
    R-->>T: MCP result {instructions: text}
    T-->>A: {instructions: text}
```

**Contracts to pin at Level 4:**
- Section marker format (e.g., `## Global Instructions` /
  `## Project Instructions`)
- Ordering strategy: `updated_at` ascending (most recent last) vs.
  `priority` metadata field
- Empty-layer behaviour: omit the section entirely vs. include an empty
  section marker
- Return shape: single text string vs. structured layers

### Interaction 4: Embedding failure on save (error path)

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as MCP Transport
    participant R as Tool Router
    participant M as Memory Service
    participant E as Embedding Client
    participant API as Embedding API

    A->>T: memory_save(...)
    T->>R: dispatch(memory_save, params)
    R->>M: save(...)
    M->>E: embed(content)
    E->>API: POST /embeddings
    API-->>E: 500 error
    E->>API: POST /embeddings (retry 1)
    API-->>E: 500 error
    E-->>M: EmbeddingError
    M-->>R: raise EmbeddingError
    R-->>T: MCP error {error: "Embedding generation failed", hint: "Retry or check embedding API"}
    T-->>A: structured error
```

**Contracts to pin at Level 4:**
- Retry policy: exactly one retry, no backoff (or configurable?)
- Error propagation: Memory Service does not store the memory if embedding
  fails — no partial writes
- Error shape: same `{error, hint}` as all other errors

### Interaction 5: User identity missing (trust boundary)

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as MCP Transport
    participant R as Tool Router
    participant U as User Resolver

    A->>T: memory_save(...) [no X-User-ID header]
    T->>R: dispatch(memory_save, params)
    R->>U: resolve(request)
    U-->>R: raise UserIdentityError
    R-->>T: MCP error {error: "User identity required", hint: "Set X-User-ID header"}
    T-->>A: structured error
```

**Contracts to pin at Level 4:** User Resolver specifics (header name,
validation rules, error shape) — deferred to LLD.

---

## Cross-Reference Matrix

| Capability | Components Involved | ADRs |
|------------|-------------------|------|
| C1. Persist memories | Tool Router, Memory Service, Embedding Client, Postgres | 0001, 0002 |
| C2. Update/delete | Tool Router, Memory Service, Embedding Client, Postgres | 0001 |
| C3. Discover by meaning | Tool Router, Memory Service, Postgres | 0001, 0002 |
| C4. Filter by structure | Tool Router, Memory Service, Postgres | 0001, 0004 |
| C5. Layered instructions | Tool Router, Instruction Service, Postgres | 0001, 0002 |
| C6. MCP tools | MCP Transport, Tool Router | — |
| C7. User/project identity | User Resolver, Tool Router | 0002 |
| C8. Deploy as infra | Config, Health Endpoints, Migration Runner, MCP Transport, CLI | 0003 |
| C9. Agent guidance | (documentation only) | — |
| C10. Log every tool call | Tool Router | — |
| ~~C11. GC stale globals~~ | ~~deferred to v2.1~~ | — |
| C12. Export to JSON | CLI, Memory Service | — |
