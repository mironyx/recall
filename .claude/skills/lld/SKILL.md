---
name: lld
description: Generate Low-Level Design documents for implementation plan sections. Produces LLDs with implementation-level detail, file paths, internal types, and task breakdowns. Use for preparing a phase or section before implementation.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Low-Level Design — Generation Skill

Generates implementation-ready Low-Level Design documents from the implementation plan and high-level design.

## Arguments

`$ARGUMENTS` determines the scope:

- **Epic mode** (e.g., `epic 45`, `epic <number>`): Generate one LLD per task in the epic. This is the primary mode for new work. Reads the epic issue, identifies tasks, and produces `lld-<epic-slug>-<task-slug>.md` per task.
- **Phase mode** (e.g., `phase2`, `phase 2`): Generate LLDs for ALL sections in the phase. Legacy mode for existing phase-based work.
- **Section mode** (e.g., `2.3`, `2.1`): Regenerate or refine a single section's LLD. Use after reviewing phase output.
- **No arguments**: Ask the user which epic, phase, or section to target.

## Process

### Step 0: Read context

**Epic mode:**

1. Read the epic issue: `gh issue view <number>`. Extract the task list and scope.
2. For each task issue, read the issue body: `gh issue view <task-number>`.
3. Read the high-level design: `docs/design/v1-design.md`. Identify relevant sections.
4. Read existing LLDs in `docs/design/` to understand the established format and avoid duplication.
5. Read relevant ADRs from `docs/adr/`.
6. Read relevant requirements from `docs/requirements/v1-requirements.md`.
7. Read existing source code in `src/` to understand what already exists.

**Phase mode:**

1. Read the implementation plan: `docs/plans/2026-03-09-v1-implementation-plan.md`. Extract all sections for the target phase.
2. Read the high-level design: `docs/design/v1-design.md`. Identify which L4 contract sections are relevant.
3. Read existing LLDs in `docs/design/` to understand the established format and avoid duplication.
4. Read relevant ADRs from `docs/adr/` referenced by the phase sections.
5. Read relevant requirements from `docs/requirements/v1-requirements.md` for the stories referenced.
6. Read existing source code in `src/` to understand what already exists.

### Step 1: Overview (epic mode or phase mode)

Before generating individual LLDs, produce a brief analysis for the user:

- List all sections in the phase with their inferred layers (DB / BE / FE)
- Identify cross-cutting concerns (e.g., auth touches DB + BE + FE)
- Identify dependency ordering (e.g., 2.1 DB schema must exist before 2.2 auth)
- Identify shared foundations (e.g., types used across multiple sections)
- Propose which sections need a full LLD vs which are sufficiently covered by the HLD

Present this overview and **wait for user confirmation** before generating the LLD files.

### Step 2: Generate LLD

**Epic mode:** Generate **one file per task** in the epic. Each task gets its own standalone LLD. File naming: `docs/design/lld-<epic-slug>-<task-slug>.md`.

**Phase mode:** Generate a **single file per phase** containing all sections. Each implementation plan section becomes a top-level heading within the file. File naming: `docs/design/lld-phase-<N>-<short-name>.md`.

**Layer inference rules** — determine which layers a section needs by examining its content:
- **DB**: Mentions tables, migrations, RLS, schema, database functions, seed data
- **BE**: Mentions API routes, middleware, server-side logic, webhooks, services, ports/adapters
- **FE**: Mentions pages, components, UI, forms, navigation, client-side state

**DRY principle** — do NOT duplicate content from the HLD. Instead:
- Reference HLD sections by link: `See [v1-design.md §4.2](v1-design.md#42-database-schema---l4-contracts)`
- Only add implementation-level detail the HLD does not contain: file paths, internal function signatures, component trees, state machines, error handling strategies, internal types not in the public contract

**Section mode** (`/lld 2.3`): Update the relevant section within the existing phase LLD file rather than creating a new file.

**Cross-cutting LLDs** (e.g., `lld-artefact-pipeline.md`) remain as standalone files when they span multiple phases or cover a topic orthogonal to the phase structure.

### Step 3: Task breakdown

The LLD ends with a single `## Tasks` section covering all sections in the phase. Tasks should be:

- Concrete and implementable in a single PR (target < 200 lines)
- Ordered by dependency (earlier tasks unblock later ones)
- Sized appropriately — split large work, combine trivial items
- Written with enough context for the `/feature` skill to pick them up

Each task entry follows this format:

```markdown
### Task N: [Short title]

**Issue title:** [Title for the GitHub issue]
**Layer:** DB | BE
**Depends on:** Task M (if any)
**Stories:** [requirement story numbers]
**HLD reference:** [link to relevant HLD section]

**What:** [1-2 sentences on what to implement]

**Acceptance criteria:**
- [ ] [Concrete, testable criterion]
- [ ] [Another criterion]

**BDD specs:**
```
TestContext
  test_behaviour_given_when_then
```

**Files to create/modify:**
- `src/recall/path/to/module.py` — [what this file does]
```

### Step 4: Cross-references (epic mode and phase mode)

Add a `## Cross-References` section at the end of the phase LLD (before Tasks) noting:
- **Internal dependencies** between sections within this phase (as anchor links)
- **External dependencies** on other phase LLDs or cross-cutting LLDs (as file links)
- **Shared types or interfaces** that span multiple sections

## LLD Template

The LLD is structured in two parts. **Part A** is for human review — a reviewer can read
Part A alone and build sufficient theory about the feature. **Part B** is for the implementing
agent — detailed enough for `/feature` to produce correct code autonomously.

One file per phase. Each implementation plan section becomes a top-level heading.

```markdown
# Low-Level Design: Phase N — [Phase Name]

## Document Control

| Field | Value |
|-------|-------|
| Version | 0.1 |
| Status | Draft |
| Author | LS / Claude |
| Created | [today's date] |
| Parent | [v1-design.md](v1-design.md) |
| Implementation plan | [Phase N](../plans/2026-03-09-v1-implementation-plan.md) |

---

# Part A — Human-Reviewable Design

> Both the human reviewer and the implementing agent read this part.
> For the reviewer, it builds theory about the feature. For the agent, it provides
> the conceptual foundation that Part B's details depend on.
> It answers: what does the feature do, how do the parts interact,
> what must always be true, and how do we know it works.

## N.1 [Section Name]

**Stories:** [story numbers]
**Layers:** DB | BE

### Purpose
[1-3 sentences: what this section delivers and why]

### Behavioural Flows

Sequence diagrams for every non-trivial interaction (>2 components communicating).
Use mermaid `sequenceDiagram` syntax. One diagram per key flow (happy path, error path,
async flows as needed).

` ` `mermaid
sequenceDiagram
    participant Agent as Coding Agent
    participant MCP as MCP Server
    participant Tool as Tool Handler
    participant Svc as Service
    participant Store as AsyncPostgresStore

    Agent->>MCP: tools/call memory.write(...)
    MCP->>Tool: dispatch(args)
    Tool->>Svc: write_memory(ctx, args)
    Svc->>Store: aput(namespace, key, value)
    Store-->>Svc: ok
    Svc-->>Tool: MemoryWritten
    Tool-->>MCP: result
    MCP-->>Agent: tools/call result
` ` `

**When required:** Any flow involving >2 components or services. MCP tool calls that
chain tool handler → service → store (+ embeddings). Background/retry flows.

**When optional:** Pure utility functions. Schema-only migrations. Single-module refactors.

### Structural Overview

Module/class dependency diagram showing how the pieces fit together. Use mermaid
`classDiagram` syntax. Works for both class-based and module-based codebases:

- **Classes** — show with methods and relationships (inheritance, composition)
- **Modules** — use `<<module>>` stereotype, show exported functions
- **Interfaces/Ports** — use `<<interface>>`, show who implements them
- **Direction** — arrows show dependency direction (who depends on whom)

` ` `mermaid
classDiagram
    class recall/services/memory {
        <<module>>
        +write_memory(ctx, args) MemoryWritten
        +search_memories(ctx, query) SearchResult
    }
    class recall/embeddings {
        <<interface>>
        +embed(text) Vector
    }
    class recall/embeddings/openai {
        <<module>>
        +OpenAIEmbedder
    }
    class recall/store {
        <<module>>
        +namespace(scope, project_id) Tuple
    }
    recall/services/memory --> recall/embeddings : depends on
    recall/services/memory --> recall/store : depends on
    recall/embeddings/openai ..|> recall/embeddings : implements
` ` `

**When required:** Any task that introduces new modules, modifies module boundaries,
or adds new dependencies between existing modules. Changes touching the embeddings or store layer.

**When optional:** Changes within a single existing module that do not alter its public
surface or dependencies.

### Invariants

Hard constraints that the implementation must satisfy. Collected in one place so the
reviewer can sign off on them and automated tools (`/pr-review-v2`, `/feature-evaluator`)
can verify them.

Each invariant should be testable — either by a unit test, a type check, or a lint rule.

| # | Invariant | Verification |
|---|-----------|-------------|
| 1 | [e.g. Store namespace is always (scope, project_id) — never widened] | [e.g. grep `aput(` / `asearch(` in src/recall; integration test asserts namespace tuple] |
| 2 | [e.g. Memory writes are idempotent per (scope, project_id, key)] | [e.g. integration test writes same key twice, asserts row count unchanged] |
| 3 | [e.g. Integration tests never mock AsyncPostgresStore] | [e.g. grep `tests/integration` for `Mock`, `patch.*Store`; CI rule] |

### Acceptance Criteria

- [ ] [Concrete, testable criterion]
- [ ] [Another criterion]

### BDD Specs

` ` `python
# tests/.../test_<area>.py

class TestContext:
    def test_behaviour_given_when_then(self) -> None:
        ...

    def test_another_behaviour(self) -> None:
        ...
` ` `

### HLD coverage assessment
- [Section X.Y] — sufficient, referenced only
- [Section X.Z] — needs extension, detailed below

---

# Part B — Agent Implementation Detail

> The implementing agent (`/feature`) reads both parts — Part A for the conceptual
> model, Part B for precise file paths, types, function signatures, and decomposition
> rules. A human reviewer may scan Part B for completeness but does not need to
> review it line-by-line.

## N.1 [Section Name] — Implementation

### [Layer: Database] (if applicable)

See [v1-design.md §N.N](v1-design.md#section-anchor) for [schema/RLS/functions].

[Only what the HLD doesn't cover: migration file strategy, seed data, test isolation, etc.]

### [Layer: Backend] (if applicable)

See [v1-design.md §N.N](v1-design.md#section-anchor) for [contracts].

#### File structure
` ` `
src/recall/<area>/
  __init__.py
  module.py        — [purpose]
tests/unit/<area>/
  test_module.py   — [what it tests]
tests/integration/<area>/
  test_module_store.py — [what it tests against a real Postgres]
` ` `

#### Internal types
[Types (TypedDicts, dataclasses, Pydantic models) not in the public contract but needed for implementation]

#### Function signatures
[Key internal functions with their signatures and behaviour]

#### Internal decomposition — [tool or component]

For every non-trivial MCP tool or component, add an explicit internal decomposition
section **before implementation begins**. Name every function, class, or protocol that
will exist internally and state what is forbidden.

```
Tool handler (src/recall/tools/<tool>.py, ≤ 10 lines):
- Parses/validates args via the tool's input model
- Delegates to the service function — no store calls, no embedding calls inline

Service (src/recall/services/<area>.py):
- Exported: `async def <service_fn>(ctx: ServiceContext, args: Args) -> Result` — [one-line purpose]
- Receives ServiceContext (carries store, embedder, project registry) — never constructs them itself

  Private helpers (≤ 20 lines each):
  - `_helper(args) -> ReturnType` — [purpose and error behaviour]

Extracted to a pure module (if applicable):
- `pure_function(...)` — [why extracted: testability, reuse]
```

Use `> **Constraint:**` for notes written **before** implementation (hard limits for the implementing
agent). Use `> **Implementation note (issue #N):**` only to document decisions made **after**
implementation — these are historical records, not pre-implementation guidance.

#### Error handling
[Error cases, MCP error codes, and recovery strategies]

---

## N.2 [Next Section Name]

[Same Part A + Part B structure as above]

---

## Cross-References

### Internal (within this phase)
- §N.1 depends on: —
- §N.2 depends on: [§N.1](#n1-section-name)
- ...

### External
- Depends on: [lld-artefact-pipeline.md](lld-artefact-pipeline.md) (if applicable)
- Depended on by: Phase M LLD (if applicable)

### Shared types
[Types used across multiple sections in this phase]

---

## Tasks

[Task entries per the format in Step 3, covering ALL sections in the phase]
```

## Guidelines

- The LLD is an **implementation guide**, not a design discussion. Decisions should already be made in the HLD and ADRs. If you find an undecided question, flag it to the user rather than deciding in the LLD.
- **Part A is the shared foundation.** Both the human reviewer and the implementing agent read Part A. For the reviewer, it is sufficient on its own to build theory. For the agent, it provides the conceptual model that Part B's details depend on. Part A must be self-contained: a reviewer who reads only Part A should understand what the feature does, how the parts interact, what must always be true, and how success is verified.
- **Part B extends Part A with implementation precision.** The `/feature` agent reads both parts. Part B adds file paths, types, function signatures, and decomposition rules. A human reviewer may scan Part B for completeness but does not need to review it line-by-line.
- **Diagrams are not optional decoration.** Sequence diagrams and structural overviews are primary review artefacts. Generate them whenever the "when required" conditions are met. Use mermaid syntax so they render in GitHub and editors.
- **Invariants must be verifiable.** Every invariant needs a verification method (test, type check, grep, lint rule). If you cannot state how to verify it, it is not an invariant — it is a wish.
- Keep LLDs focused and concise. If a section is just "see HLD", that's fine — it confirms the HLD is sufficient.
- Task granularity: each task should be completable in one `/feature` cycle. If a task would produce > 200 lines of changes, split it.
- BDD specs in tasks should be concrete enough for the `/feature` skill to write tests directly from them.
- Use British English in all documentation.
