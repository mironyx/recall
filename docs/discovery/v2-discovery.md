# Discovery: Recall — Persistent Memory for AI Coding Agents

Date: 2026-04-12
Source: docs/discovery/recall-idea.md
Status: Final

---

## Vision

For engineering teams that use AI coding agents daily, whose agents lose all context between sessions — forcing humans to repeatedly re-explain project history, conventions, and decisions — Recall is a self-hosted MCP memory server that gives every agent on the team persistent, shared long-term memory across sessions, machines, and projects. Unlike Claude Code's built-in memory (single-user, single-project, local files) or managed platforms like Mem0 and Zep (cloud-hosted, general-purpose, not optimised for code), Recall is deliberately small, self-hosted, and purpose-built for the coding-agent workflow: it runs where your code runs, stores what coding agents actually need, and stays under the team's control.

## Boundaries

| | Is | Is Not |
|---|---|---|
| **The product** | A persistent memory layer for AI coding agents | A general-purpose AI memory platform for all agent types |
| | An MCP server that any MCP-compatible agent can connect to | A proprietary integration locked to one agent vendor |
| | Self-hosted by the team (single container, Postgres + pgvector) | A managed SaaS / cloud service |
| | A tool for storing project context, conventions, decisions, and team knowledge | A conversation history store or chat log archive |
| | Built on LangMem / LangGraph with AsyncPostgresStore | A bespoke storage engine or custom vector DB |
| | Opinionated about memory categories (few, broad tools) | A framework for building arbitrary memory systems |
| **The scope (V1)** | Core memory CRUD: store, retrieve, search, forget | Knowledge graph / entity resolution |
| | Two scopes: project-level and global | Per-user or per-agent scoping |
| | Semantic search over memories (pgvector embeddings) | Multi-strategy retrieval (graph traversal, BM25, reranking) |
| | Single MCP transport (Streamable HTTP) | Multiple transports (SSE, stdio, WebSocket) |
| | Single-container deployment (Docker) | Distributed / multi-node deployment |
| | Works with any MCP-compatible coding agent | Custom integrations for specific agent frameworks |

## Personas

### Persona: Sam (Tech Lead)

**Profile:** Senior engineer leading a team of 4–6, responsible for architecture decisions and code quality across 2–3 active repositories.

**Goals:**
- Ensure AI agents used by the team respect existing architectural decisions and conventions
- Avoid re-explaining the same project context to agents session after session
- Maintain consistency across the team's AI-assisted work (one agent shouldn't contradict another's output)

**Pain points:**
- Claude Code's CLAUDE.md files capture some context, but they're per-machine and manually maintained — no shared state across the team
- When a new team member (or a new agent session) starts, the "ramp-up tax" is high — the same decisions get re-explained
- No visibility into what an agent "knows" from previous sessions with other team members

**Context:** Uses AI coding agents throughout the day for code review, feature implementation, and debugging. Switches between multiple repos and machines. Wants agents to behave like a well-onboarded team member, not a stranger every session.

**Quote:** "I've explained our API versioning strategy to Claude four times this week — once per session. The agent should just know this by now."

### Persona: Priya (Full-Stack Developer)

**Profile:** Mid-level developer working primarily in one or two repositories, heavy daily user of AI coding agents for feature work and bug fixes.

**Goals:**
- Get AI agents up to speed on the codebase instantly, without lengthy preambles
- Have agents remember what was tried before (failed approaches, decisions made, trade-offs considered)
- Switch between her desktop and laptop without losing agent context

**Pain points:**
- Spends the first 5–10 minutes of each session re-establishing context with the agent
- When picking up a colleague's work-in-progress, the agent has no memory of what the colleague's agent already explored
- Built-in memory is tied to one machine — working from home vs. office means separate memory silos

**Context:** Works across desktop and laptop. Frequently picks up tasks started by teammates. Wants seamless continuity — the agent should remember not just what code exists, but why it was written that way.

**Quote:** "I switched to my laptop and Claude had no idea about the migration we spent all morning on. It's like talking to a different person."

### Persona: Jordan (Platform / DevOps Engineer)

**Profile:** Engineer responsible for developer tooling, CI/CD, and infrastructure. Evaluates and deploys tools for the engineering team.

**Goals:**
- Deploy and maintain a memory server that's reliable, observable, and low-maintenance
- Ensure the tool meets the team's data governance requirements (self-hosted, no data leaving the network)
- Keep the operational footprint small — one more container, not a new distributed system

**Pain points:**
- Managed AI memory services (Mem0, Zep Cloud) are non-starters for teams with data residency or security requirements
- Existing open-source memory solutions are either too complex (full knowledge graph stacks) or too simplistic (flat key-value stores)
- Wants something that fits into the existing Postgres infrastructure, not a new database to manage

**Context:** Maintains the team's Docker Compose / Kubernetes setup. Evaluates tools on operational cost, not just features. Will be the one paged at 2am if it breaks.

**Quote:** "If it needs its own database cluster, it's dead on arrival. Give me a Postgres extension I can bolt onto what we already run."

---

## User Journeys

### J1: Sam (Tech Lead) — Seeding project knowledge

**Trigger:** Sam's team starts using Recall on an existing project. The agents have no shared memory yet.

**Steps:**
1. Jordan deploys Recall (single container) pointing at the team's existing Postgres instance
2. Sam configures the MCP connection in his coding agent, specifying the project ID
3. Sam tells his agent: "Remember that we use event sourcing for the order service, and all API changes must be backward-compatible"
4. The agent calls Recall's store tool → memory is persisted with `scope=project` and appropriate category
5. Next session (or another team member's session), the agent retrieves project memories at startup → knows the conventions without being told

**Outcome:** Project conventions, architecture decisions, and team agreements are stored once and available to every agent session on the team.

**Pain points addressed:** Re-explaining decisions every session; inconsistency across team members' agent sessions.

### J2: Sam (Tech Lead) — Ensuring agent consistency across the team

**Trigger:** Sam notices that Priya's agent suggested a REST endpoint design that contradicts an architecture decision he recorded last week.

**Steps:**
1. Sam asks his agent: "What do we have stored about API design conventions?"
2. The agent searches Recall → returns the stored decision about backward-compatible API changes
3. Sam realises the memory exists but Priya's agent didn't retrieve it at the right moment — this is an agent prompting issue, not a Recall issue
4. Sam refines the memory's content to be more specific and discoverable (updates the memory via the agent)

**Outcome:** Sam can audit and refine what the team's agents "know", building confidence that shared context is accurate and findable.

**Pain points addressed:** No visibility into what agents know; inconsistent agent behaviour across the team.

### J3: Priya (Developer) — Continuing work across machines

**Trigger:** Priya worked on a feature at the office all morning. She's now on her laptop at home and wants to continue.

**Steps:**
1. Priya opens her coding agent on the laptop, connected to the same Recall server
2. The agent retrieves project-scoped memories for this repository → picks up conventions, recent decisions, and context from the morning session
3. Priya says: "Continue the payment webhook integration I was working on earlier"
4. The agent searches memories for recent work context → finds notes about the webhook approach, what was tried, and what was decided
5. Priya resumes work without re-explaining anything

**Outcome:** Seamless continuity across machines. The agent picks up where the last session left off.

**Pain points addressed:** Per-machine memory silos; 5–10 minute context re-establishment at session start.

### J4: Priya (Developer) — Picking up a colleague's work

**Trigger:** A teammate was working on a bug fix but went on leave. Priya needs to pick it up.

**Steps:**
1. Priya opens the project in her coding agent
2. The agent retrieves project memories → finds the teammate's notes about the bug: what was investigated, which approaches failed, and the current hypothesis
3. Priya can ask the agent: "What did Alex try for the race condition in the payment service?"
4. The agent searches Recall → returns structured context from Alex's sessions
5. Priya continues from where Alex left off, avoiding repeated dead ends

**Outcome:** Knowledge transfer happens through the memory layer, not through Slack threads or handover meetings.

**Pain points addressed:** No memory of what a colleague's agent explored; repeated dead-end investigations.

### J5: Jordan (DevOps) — Deploying and operating Recall

**Trigger:** The team decides to adopt Recall. Jordan needs to get it running.

**Steps:**
1. Jordan pulls the Recall container image and adds it to the team's Docker Compose / Kubernetes config
2. Jordan points Recall at the team's existing Postgres instance (with pgvector extension enabled)
3. Recall runs database migrations on startup
4. Jordan configures the team's coding agents to connect to Recall's MCP endpoint
5. Jordan monitors Recall through standard container metrics and Postgres observability

**Outcome:** Recall is running in production with minimal operational overhead — one container, existing database, standard monitoring.

**Pain points addressed:** Complex deployment requirements; needing a new database to manage.

### J6: Jordan (DevOps) — Storing global conventions

**Trigger:** The team has cross-project standards (coding style, security practices, deployment conventions) that should apply to all projects.

**Steps:**
1. Jordan (or Sam) tells the agent: "Remember globally that all services must use structured logging with correlation IDs"
2. The agent stores this with `scope=global`
3. When any team member works on any project, the agent retrieves both project-scoped and global memories
4. Global conventions are available everywhere without per-project duplication

**Outcome:** Organisation-wide standards are stored once and surfaced in every project context.

**Pain points addressed:** Repeating cross-cutting conventions in every project; inconsistency between projects.

### Design tension: Agent-side integration

Three related concerns surfaced during review:

1. **Agents need instructions for when/how to save and retrieve memories.** Recall provides the storage layer, but the agent needs prompting guidance (skills, system prompts, or CLAUDE.md-style instructions) to know when to call the memory tools. Without this, memory usage is ad-hoc and inconsistent.

2. **Autonomous agents must retrieve proactively.** When agents run in autonomous mode (e.g., `/feature` workflows), they can't rely on the human to say "check your memory." The agent's system prompt or skill definition must include retrieval triggers — e.g., "before starting implementation, search Recall for relevant project conventions."

3. **On-demand retrieval, not eager loading.** Loading all memories into context at session start would pollute the context window and waste tokens. The preferred pattern is **lazy retrieval**: search for relevant memories when a specific task or decision point arises, not upfront. This means Recall's search tool must be good enough that agents can find what they need in the moment, rather than needing to pre-load everything.

**Where this lives:** This is an agent-configuration concern, not a server feature — but it directly shapes Recall's tool design. The MCP tool descriptions (which are prompts to the agent) should encode retrieval guidance. Recall should also ship with reference agent instructions (e.g., a sample CLAUDE.md snippet or skill) that teams can adapt. This is captured as Feature #18 below.

---

## Features

| # | Feature | Journey | Personas | Effort | Value | Notes |
|---|---------|---------|----------|--------|-------|-------|
| 1 | Store a memory (with scope, category, and content) | J1, J2, J6 | Sam, Priya, Jordan | S | H | Core CRUD — the fundamental write operation |
| 2 | Retrieve memories by project scope | J1, J3, J4, J5 | Sam, Priya | S | H | Filtered retrieval by project ID |
| 3 | Semantic search over memories | J2, J4 | Sam, Priya | M | H | pgvector embedding search — the primary discovery mechanism |
| 4 | Global-scope memories (cross-project) | J6 | Sam, Jordan | S | H | `scope=global` memories returned alongside project memories |
| 5 | Update / refine an existing memory | J2 | Sam, Priya | S | M | Edit content without losing the memory's identity |
| 6 | Delete / forget a memory | J2 | Sam, Priya | S | M | Explicit removal of outdated or incorrect memories |
| 7 | MCP server with Streamable HTTP transport | All | All | M | H | The integration surface — how agents connect |
| 8 | Single-container deployment (Docker) | J5 | Jordan | M | H | Dockerfile, health checks, env-var config |
| 9 | Database migrations on startup | J5 | Jordan | S | M | Auto-migrate schema; no manual SQL |
| 10 | Memory categories (kind field) | J1, J6 | Sam, Jordan | S | M | Categorise memories (decision, convention, context, etc.) — config, not code |
| 11 | List memories with filtering | J2, J4 | Sam, Priya | S | M | Filter by scope, category, date range |
| 12 | Bulk memory seeding (import) | J1 | Sam, Jordan | M | L | Import memories from a file for initial setup |
| 13 | Memory expiry / TTL | — | Jordan | S | L | Auto-expire stale memories after a configurable period |
| 14 | Access control / API keys | J5 | Jordan | M | M | Basic auth to prevent unauthorised access |
| 15 | Memory provenance (who stored it, when) | J2, J4 | Sam | S | L | Metadata about memory origin for auditability |
| 16 | Admin UI for browsing memories | J2 | Sam, Jordan | L | M | Web interface to inspect and manage stored memories |
| 17 | Multi-project dashboard | J5 | Jordan | L | L | Overview of all projects, memory counts, health |
| 18 | Reference agent instructions (sample skills / system prompts) | J1, J2, J3 | Sam, Priya | S | H | Ship guidance that teaches agents when to store/retrieve — e.g., sample CLAUDE.md snippet, MCP tool descriptions with retrieval hints |

---

## MVP Sequencer

### Wave 1 — Core (minimum viable)
**Features:** #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #18

**Rationale:** This is the smallest set that delivers end-to-end value. An agent can connect via MCP, store memories with project or global scope, search them semantically, and update or remove them. Jordan can deploy it as a single container against existing Postgres. Without any of these, the product doesn't function as a useful memory layer. Feature #10 (categories) is included because uncategorised memories become unsearchable noise quickly — it's a small addition with outsized impact on retrieval quality. Feature #18 (reference agent instructions) is included in Wave 1 because the server is useless without agents knowing how to use it — the tool descriptions and sample instructions are the "last mile" that makes everything else work.

### Wave 2 — Operational confidence
**Features:** #11, #14, #15

**Rationale:** Once teams are actively using Recall, they need to manage what's stored. Filtering (#11) lets agents and humans browse memories efficiently. API keys (#14) are essential before any team deployment beyond a single developer. Provenance (#15) builds trust — Sam needs to know who stored a memory and when to judge its reliability.

### Wave 3+ — Future
**Features:** #12, #13, #16, #17

**Rationale:** Bulk import (#12) is a convenience for onboarding, not essential — teams can seed memories organically through normal agent usage. TTL (#13) is a nice-to-have that can be managed manually in V1 (just delete stale memories). Admin UI (#16) and dashboard (#17) add significant development effort for features that are valuable but not blocking — teams can inspect memories through the agent itself initially.

---

## Next steps

1. Run `/requirements` to produce `docs/requirements/v2-requirements.md` from this discovery
2. Run `/kickoff docs/requirements/v2-requirements.md` to produce HLD, ADRs, and implementation plan
