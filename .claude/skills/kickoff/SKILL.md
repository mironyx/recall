---
name: kickoff
description: Bootstrap a new project from a requirements document. Produces the HLD (Levels 1–3), load-bearing ADRs, and the implementation plan, with human gates after each. Use at the very start of a project, before /architect. See ADR-0005.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill, TodoWrite
---

# Kickoff — Project Bootstrap

Takes a requirements document and produces the design artefacts needed before
`/architect` can generate LLDs and `/feature` can implement. Owns the
**Levels 1–3** of the design-down process (Capabilities, Components,
Interactions) at project-wide scope.

See [ADR-0005](../../../docs/adr/0005-project-bootstrap-pipeline.md) for the
rationale and [docs/process/engineering-process.md](../../../docs/process/engineering-process.md)
for where this fits in the full lifecycle.

**Model:** Use Opus (the latest Claude model) for this skill and any sub-agents
it spawns. When launching agents, pass `model: "opus"`.

**Usage:**

- `/kickoff` — reads `REQUIREMENTS.md` at the repository root (recall's
  canonical requirements location)
- `/kickoff <path>` — reads a specific requirements file (use this if the
  project has migrated to a `docs/requirements/` directory)

## When to use

Run once per project (or once per major version) when:

- A requirements document exists (for recall, `REQUIREMENTS.md` at the root)
- No HLD exists yet, or the existing HLD is stale and being rewritten for a
  new version
- No implementation plan exists for this version

If an HLD and plan already exist and you only need per-epic LLDs, use
`/architect` instead.

## Inputs and outputs

**Inputs:**

- `REQUIREMENTS.md` (recall) or `docs/requirements/*.md` — user stories,
  acceptance criteria, constraints
- Existing `docs/adr/` — do not contradict accepted ADRs. For recall this
  means ADR-0001 (flat value schema), ADR-0002 (namespace shape), ADR-0003
  (no TTL in v1), ADR-0004 (filter limitations) are load-bearing and must be
  respected.
- Existing `CLAUDE.md` — project conventions to preserve

**Outputs (in order):**

1. `docs/design/v1-design.md` — HLD covering Capabilities, Components,
   Interactions (Levels 1–3)
2. `docs/adr/NNNN-*.md` — one ADR per load-bearing decision the HLD forces
3. `docs/plans/YYYY-MM-DD-v1-implementation-plan.md` — phased plan derived
   from the HLD
4. GitHub epic issues plus Phase 0 task issues on the project board
5. Updated `CLAUDE.md` — fills in or refreshes project-specific blocks
   (phase, stack, verification commands, project structure)

## Human gates

**Four** mandatory stop points. Do not proceed past any gate without explicit
user approval.

1. After the HLD is drafted — user reviews the drift-scan coverage matrix
2. After the ADR list is proposed — user approves the full set in one shot; individual ADRs are then drafted and committed back-to-back without per-ADR approval pauses
3. After the implementation plan is drafted — user reviews the second drift
   scan
4. After Phase 0 epics and task issues are proposed — user confirms before
   anything is created on the board

## Process

Execute these steps sequentially. Use `TodoWrite` to track progress.

### Step 1: Read inputs and orient

1. If `$ARGUMENTS` contains a file path, use that. Otherwise default to
   `REQUIREMENTS.md` at the repository root (recall convention). If neither
   exists, look for the most recent `docs/requirements/*.md`.
2. Read the requirements document fully. Extract: user stories, acceptance
   criteria, non-functional constraints, explicit technology choices, explicit
   non-goals.
3. List existing ADRs (`ls docs/adr/`) and read every one that looks
   load-bearing (storage, namespace, schema, transport, deployment). For
   recall, ADR-0001 to ADR-0004 are all load-bearing — do not re-decide what
   is already decided.
4. Read the current `CLAUDE.md` to understand project conventions.
5. Check for existing design artefacts:
   - `docs/design/v1-design.md` — if present, confirm with the user whether
     this run is a rewrite or an abort
   - `docs/plans/` — same check
6. Present a short orientation summary: what exists, what is missing, what
   will be produced. Wait for user confirmation before proceeding.

### Step 2: Draft the HLD (Levels 1–3)

Produce `docs/design/v1-design.md` with three sections matching the
design-down levels.

#### Level 1 — Capabilities

For each user story or requirement group, name the capability it delivers at
system level. One short paragraph per capability. No components yet, no
technology. Example (recall-shaped): "Store a memory: the system shall accept
a `(scope, project_id, kind, value)` tuple and persist it durably under the
correct namespace."

Cross-check every requirement has at least one capability covering it. Flag
any requirement with no capability — this is where AI bias toward novel
problems shows up.

#### Level 2 — Components

Decompose the capabilities into components. For each component:

- **Name** and one-line purpose
- **Responsibilities** (bullet list, 3–6 items)
- **Non-responsibilities** (what it explicitly does not do) — this is the
  single most valuable section for catching boundary errors later
- **Depends on** (other components, external services)

Include a Mermaid component diagram showing the dependency graph.

Keep components abstract. "Storage adapter" is a component; "LangGraph
AsyncPostgresStore v0.3" is an implementation detail that belongs in an ADR.

#### Level 3 — Interactions

For the top 3–5 user flows, produce a sequence diagram (Mermaid) showing how
components collaborate. Include at least: the happy path for the primary
capability, the primary error path, and any flow that crosses a trust
boundary (auth, external API, cross-scope access).

Each diagram is accompanied by a short prose walkthrough naming the
contracts that will need to be pinned down at Level 4 (but do not specify
them here).

#### HLD commit

```bash
git add docs/design/v1-design.md
git commit -m "docs: HLD v1 — capabilities, components, interactions"
```

### Step 3: Gate 1 — drift scan and human review

Run the `requirements-design-drift` agent against the requirements and the
freshly written HLD. The agent produces a coverage matrix: which requirement
maps to which capability and component.

Present the coverage matrix to the user. Flag:

- Uncovered requirements (critical — AI bias signal)
- Over-covered requirements (spec bloat)
- Components with no requirement (scope creep)

**Stop. Wait for explicit user approval before proceeding to Step 4.** The
user may direct patches to the HLD — apply them and re-run the drift scan
until the user is satisfied.

### Step 4: Propose and draft load-bearing ADRs

From the HLD, identify the decisions that are load-bearing — the ones that
shape multiple components or constrain future choices. Typical categories:

- Runtime / hosting
- Primary datastore and schema shape
- Authentication and authorisation
- External service integration pattern (embeddings, MCP clients)
- Test strategy (unit/integration mix; for recall, testcontainers is already
  mandated)
- Observability and logging
- Any framework choice that appears in multiple components

Present the proposed ADR list to the user with a one-line rationale per
entry. Wait for confirmation of the list before drafting any ADR.

For each confirmed ADR:

1. Use `/create-adr` to produce the ADR. Follow the project's ADR format and
   numbering (check `docs/adr/` for the next number — for recall today,
   start from 0006).
2. Commit the ADR:
   ```bash
   git add docs/adr/NNNN-*.md
   git commit -m "docs: ADR-NNNN <title>"
   ```
3. After committing each ADR, immediately proceed to drafting the next one
   on the approved list. Do **not** pause for per-ADR approval — the user
   approved the set in the previous step. Briefly summarise each ADR as it
   lands so the user can interject if they want to course-correct, but the
   default is to keep drafting until the approved list is exhausted.

Do not draft ADRs for decisions that are not load-bearing. Those belong in
LLDs (Level 4) and are produced later by `/architect`.

### Step 5: Draft the implementation plan

Produce `docs/plans/YYYY-MM-DD-v1-implementation-plan.md` derived **from the
HLD**, not from the requirements directly. The plan's job is to sequence the
delivery of components and contracts, not activities.

Structure:

- **Phases** — typically Phase 0 (scaffolding / infra), Phase 1 (first
  end-to-end slice), Phase 2+ (additional capabilities). Each phase has a
  stated goal and exit criteria.
- **Per phase: epics** — each epic maps to a component or a capability slice
  from the HLD. Reference the HLD section explicitly.
- **Per epic: rough task list** — not enriched issues yet, just the shape of
  the work. `/architect` will turn these into LLDs later.
- **Dependencies** — explicit ordering between phases and between epics
  within a phase.
- **Cross-references** — every epic links to the HLD section and any ADRs it
  depends on.

Commit:

```bash
git add docs/plans/YYYY-MM-DD-v1-implementation-plan.md
git commit -m "docs: v1 implementation plan"
```

### Step 6: Gate 2 — second drift scan and human review

Run `requirements-design-drift` again, this time checking that the plan
covers the HLD (and therefore, transitively, the requirements). Present the
second coverage matrix.

**Stop. Wait for explicit user approval before proceeding to Step 7.** Apply
any requested patches and re-run until satisfied.

### Step 7: Bootstrap Phase 0 on the board

Create the GitHub artefacts — but only for Phase 0. Later phases stay
epic-level until their turn, to avoid generating stale issues upfront.

1. Propose the list of epics and Phase 0 tasks to the user with a summary
   table. **Wait for confirmation** before creating anything.
2. For each epic (all phases), create an epic issue:
   ```bash
   gh issue create --title "Epic: <name>" --label epic --body "$(cat <<'EOF'
   ## Scope
   ...

   ## Success criteria
   ...

   ## HLD reference
   docs/design/v1-design.md#<anchor>

   ## Related ADRs
   - ADR-NNNN ...

   ## Tasks
   - [ ] (to be added)
   EOF
   )"
   ```
3. Add each epic to the board (the board setup is not yet in place for
   recall — when the first epic lands, wire up the board script before
   running this step).
4. For Phase 0 epics only, create task issues and link them back to their
   parent epic. Follow the task-body format from `/architect` (Parent epic,
   Design reference, Acceptance criteria, BDD specs placeholder).
5. Add each task to the board.
6. Update epic bodies with their task checklists.

### Step 8: Update CLAUDE.md

Refresh the project-specific blocks in `CLAUDE.md`:

- Current phase (set to Phase 0)
- Tech stack (already populated for recall — cross-check against any new
  ADRs and update only if they changed a choice)
- Verification commands (`uv run pytest`, `uv run ruff check .`,
  `uv run mypy` — already present)
- Project structure (already populated)

Commit:

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — project-specific configuration"
```

### Step 9: Report and stop

Summarise to the user:

- HLD file produced
- ADRs produced (numbers and titles)
- Implementation plan file
- Epics created (all phases) and task issues created (Phase 0 only)
- Board state
- Drift scan verdicts (both runs)
- Suggested next step: run `/architect epic <N>` on the first Phase 0 epic

**Stop here.** Do not proceed to `/architect` or `/feature` automatically.
Project bootstrap is a deliberate, gated process — the user drives the
transition to implementation.

## Guidelines

- **Do not implement.** This skill produces design and planning artefacts
  only. Zero production code.
- **HLD before plan, always.** A plan drafted before the HLD plans activities
  rather than component deliveries. See ADR-0005.
- **One ADR at a time.** Batching ADR drafts makes review expensive and
  encourages rubber-stamping. Draft, commit, wait for approval, repeat.
- **Phase 0 only on the board.** Do not generate issues for later phases.
  They go stale before `/architect` ever touches them.
- **Respect existing ADRs.** If requirements contradict an accepted ADR, stop
  and ask — do not silently re-decide. For recall, ADR-0001 to ADR-0004 are
  not up for renegotiation inside `/kickoff`.
- **Drift scans are gates, not decoration.** Do not proceed past Step 3 or
  Step 6 without running the agent and showing the user the matrix.
- **British English** in all documentation.
- **Reference, do not duplicate.** The HLD references requirements; ADRs
  reference the HLD; the plan references both. Every artefact has exactly
  one source of truth.
- **Do not invent requirements.** If the requirements document is ambiguous,
  stop and ask rather than inferring.
- **Keep the HLD proportional.** Three levels covering the main shape of the
  system — not an exhaustive design. Level 4 detail belongs in LLDs produced
  by `/architect`, not here.
