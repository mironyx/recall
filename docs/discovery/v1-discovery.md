# Discovery: Recall — Persistent Memory for AI Coding Agent Teams

Date: 2026-04-12
Source: docs/discovery/recall-idea.md
Status: Draft — Problem Space

---

## Vision

For engineering teams who rely on AI coding agents (Claude Code, Cursor, Copilot agents) to ship software, whose agents lose all context the moment a session ends, Recall is a self-hosted MCP memory server that gives every agent on the team persistent, shared memory across sessions, machines, and projects. Unlike Mem0 and Zep, which are managed SaaS platforms optimised for conversational AI and customer-facing products, and unlike Claude Code's built-in memory, which is personal, per-project, and vanishes across machines, Recall takes a deliberately boring approach: a single container backed by Postgres + pgvector, exposed as a handful of MCP tools, designed to be owned and operated by the team that uses it.

## Boundaries

|  | Is | Is Not |
|---|---|---|
| **The product** | A self-hosted MCP server that stores and retrieves agent memories | A managed SaaS platform or cloud service |
|  | A shared memory layer for a team of humans + AI agents | A personal memory store scoped to one developer |
|  | A Postgres-backed store using pgvector for semantic search | A bespoke vector database or knowledge graph engine |
|  | An MCP tool provider with ≤ 6 tools | A general-purpose RAG pipeline or retrieval framework |
|  | A single container with one transport (Streamable HTTP) | A distributed system with multiple services or transports |
|  | Compatible with any MCP-capable client (Claude Code, Cursor, etc.) | Tied to a specific IDE or agent framework |
| **The scope (V1)** | Project-scoped and global-scoped memories | Per-user scopes, per-team scopes, or arbitrary namespace hierarchies |
|  | Semantic search over memory content | Knowledge graph traversal or temporal reasoning |
|  | Categories as data (configurable `kind` field) | Hard-coded memory types requiring code changes to extend |
|  | OpenAI-compatible embeddings endpoint | Bundled embedding model or multi-provider embedding router |
|  | Basic memory CRUD + search | Memory synthesis, reflection, or automatic consolidation |
|  | Docker-based deployment | Kubernetes operators, Helm charts, or managed cloud deployment |

## Personas

### Persona: Kai (Tech Lead)

**Profile:** Senior engineer who manages a team of 4–6 developers, all using AI coding agents daily.
**Goals:**
- Ensure agents across the team share knowledge about architecture decisions, conventions, and project context
- Reduce repeated "explain the codebase" prompts that waste tokens and time
- Keep agent memory under the team's control (no third-party SaaS holding proprietary context)
- Have a simple deployment that doesn't need a dedicated platform team to maintain

**Pain points:**
- Claude Code's CLAUDE.md files are per-repo and per-machine — knowledge doesn't transfer when a teammate picks up a task
- Every new agent session starts from zero; hard-won context about why something was built a certain way is lost
- Managed memory services (Mem0, Zep) are either too expensive, too complex, or raise data sovereignty concerns
- No standard way for agents to share learned context across projects (e.g., shared infrastructure patterns used in multiple repos)

**Context:** Uses AI agents in terminal (Claude Code) and IDE (Cursor). Manages 3–5 active repositories. Wants to `docker compose up` a memory server and point all agents at it.
**Quote:** "I want my agents to remember what we decided last sprint without me having to re-explain it every session."

### Persona: Rina (Individual Developer)

**Profile:** Mid-level developer on Kai's team, heavy daily user of Claude Code for feature work, debugging, and code review.
**Goals:**
- Pick up where she left off across sessions without losing context
- Have agents that understand project conventions without her manually maintaining CLAUDE.md
- Benefit from context her teammates' agents have already captured (e.g., "this API is flaky, retry with backoff")

**Pain points:**
- Switches between laptop and desktop; agent memory doesn't follow her
- Spends time re-explaining project setup, testing conventions, and deployment quirks to fresh agent sessions
- Claude Code's built-in memory is helpful but siloed — her teammate's agent doesn't know what hers learned yesterday
- Afraid of information overload if memory isn't well-scoped

**Context:** Works primarily in Claude Code. Touches 1–2 repos daily. Wants memory to "just work" without managing infrastructure.
**Quote:** "My agent should already know that we use pytest with testcontainers — I told it that three sessions ago."

### Persona: Alex (DevOps / Platform Engineer)

**Profile:** Runs the team's infrastructure. Responsible for deploying and maintaining internal tools.
**Goals:**
- Deploy the memory server with minimal operational overhead (single container, standard Postgres)
- Ensure data stays within the team's infrastructure (compliance, IP protection)
- Monitor and manage memory storage without needing to understand AI/ML internals
- Integrate with existing Postgres infrastructure if possible

**Pain points:**
- Managed AI memory services don't meet data residency or compliance requirements
- Complex memory systems (Zep's temporal graphs, Mem0's multi-tier architecture) are over-engineered for the team's needs
- Doesn't want to operate a separate vector database alongside Postgres — pgvector is already proven
- Needs clear resource consumption patterns (storage growth, embedding costs) to budget and plan

**Context:** Manages infrastructure via Docker Compose / Terraform. Already runs Postgres for other services. Wants a single container that talks to an existing (or bundled) Postgres instance.
**Quote:** "If it needs more than a Dockerfile and a connection string, it's too complex for what it does."
