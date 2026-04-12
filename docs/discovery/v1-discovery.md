# Discovery: Recall — Persistent Memory for AI Coding Agents

Date: 2026-04-12
Source: docs/discovery/recall-idea.md
Status: Draft — Problem Space

---

## Vision

**For** engineering teams who use AI coding agents (Claude Code, Cursor, OpenCode, and others), **whose** agents lose all learned context at the end of every session — architectural decisions, hard-won gotchas, how a component actually works — **Recall is** a shared, persistent memory server **that** lets every agent on the team pick up where any agent left off, across sessions, machines, and projects. **Unlike** Claude Code's built-in memory (single-user, single-machine, flat markdown) or heavyweight platforms like Mem0 Cloud ($249/month for graph features, opinionated extraction pipeline), **our approach** is deliberately small: a focused MCP server with a handful of broad tools, backed by Postgres, that a team can self-host and that treats the agent — not the human — as the primary user.

---

## Boundaries

|   | Is | Is Not |
|---|---|---|
| **The product** | A shared memory backend for AI coding agents | A general-purpose AI memory platform for chatbots, customer support, or non-coding use cases |
|  | An MCP server that any MCP-compatible agent can connect to | A plugin or extension specific to one IDE or agent |
|  | A tool designed for agent comprehension (tool descriptions are prompt design) | A human-facing UI for browsing or managing memories |
|  | A multi-user, multi-machine system where teammates' agents share project knowledge | A single-user, local-only memory file |
|  | A semantic search layer over structured memories (Postgres + pgvector) | A knowledge graph with entity extraction and relationship modelling |
|  | Self-hostable infrastructure a team controls | A managed SaaS with vendor lock-in |
| **The scope (V1)** | Core CRUD + semantic search for memories | LLM-driven memory extraction, compaction, or summarisation |
|  | Two scopes: project-level and global (cross-project) | Multi-tenant org/team hierarchy or per-user privacy within a project |
|  | A `kind` field for categorisation (data, not class hierarchy) | Typed memory classes with separate modules and endpoints |
|  | Streamable HTTP transport (current MCP standard) | SSE shim, stdio transport, or multiple transport options |
|  | Self-improving agent instructions (read + save, layered by scope) | Automatic instruction merging, deduplication, or forgetting |
|  | Single container deployment with Postgres | Kubernetes operator, managed database, or complex orchestration |

---

## Personas

### Persona: Sam (Senior Engineer / Tech Lead)

**Profile:** Leads a team of 4–6 engineers. Uses Claude Code daily for architecture, refactoring, and code review. Runs agents on a laptop and a remote dev machine.

**Goals:**
- Stop re-explaining project conventions to a fresh agent every session
- Ensure architectural decisions made with one agent are visible to all agents on the team
- Maintain a living knowledge base of "how things actually work here" that agents consult automatically
- Reduce onboarding time for new team members (their agents inherit the team's project memory)

**Pain points:**
- Claude Code's CLAUDE.md is local and single-machine — manually syncing it across machines is tedious
- When a teammate's agent discovers a gotcha (e.g. "never mock the database in tests — we got burned"), that knowledge dies with the session
- Agent sessions start cold: the first 10 minutes of every session are spent re-establishing context
- Existing memory solutions (Mem0, Zep) are either too heavyweight, too expensive, or designed for chatbot personalization rather than coding agents

**Context:** Works across 2–3 active repositories. Wants agents to remember cross-project lessons (e.g. "this user prefers British English in docs") alongside project-specific rules.

**Quote:** "I want my agent to know what my team's agents already learned — without me copy-pasting from Slack."

### Persona: Priya (Individual Contributor / Mid-Level Engineer)

**Profile:** Works primarily in one repository, uses Cursor and occasionally Claude Code. Not interested in infrastructure — wants memory to "just work."

**Goals:**
- Have her agent remember what she taught it last session (coding patterns, test approaches, library quirks)
- Search for relevant past decisions when working on unfamiliar parts of the codebase
- Avoid repeating the same corrections to the agent ("no, we use snake_case here", "don't add docstrings to private methods")

**Pain points:**
- Every new session feels like starting over — the agent forgets her preferences and the project's idioms
- Built-in memory files grow stale and nobody curates them
- She doesn't want to manage a database or run Docker — but will if setup is a single `docker compose up`

**Context:** Joins stand-ups where teammates mention things "the agent should know." Wants to benefit from shared memory without actively managing it.

**Quote:** "I corrected my agent three times this week about the same thing. It should remember."

### Persona: Jordan (DevOps / Platform Engineer)

**Profile:** Responsible for the team's shared infrastructure. Evaluates, deploys, and maintains internal tools. Security-conscious.

**Goals:**
- Deploy a memory server that the whole team can use with minimal operational overhead
- Ensure project isolation — one project's memories don't leak into another
- Have visibility into what's stored (audit, backup, inspection)
- Keep the stack simple: no new databases, no new runtimes — Postgres is already in the stack

**Pain points:**
- Existing memory solutions require multiple services, exotic storage backends, or cloud accounts with opaque pricing
- No clear auth story — who can read/write what?
- Observability is an afterthought in most agent tooling — hard to debug when things go wrong

**Context:** Manages 3–5 internal services. Will champion or block adoption based on operational simplicity and security posture.

**Quote:** "If it needs more than a Dockerfile and a Postgres connection string, it's too complicated."

---
