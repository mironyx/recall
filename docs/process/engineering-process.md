# Engineering Process

This document describes the end-to-end engineering process for this project,
from a blank repository with a requirements document to merged, verified
features running in production. It is the **map** — ADRs hold the *why*,
SKILL.md files hold the *how*, and CLAUDE.md holds the sticky-note summary
every session loads.

Come back here when you need to refresh your memory on the overall shape of
the process or where a specific artefact lives.

> **Provenance.** The process described here is ported from the sibling
> `feature-comprehension-score` project. The framework — not the domain — is
> what's being reused, matching the "Engineering practice (carried over from
> feature-comprehension-score)" section of recall's CLAUDE.md. Artefact paths
> have been adapted to recall's layout: a single `REQUIREMENTS.md` at the
> repository root replaces `docs/requirements/`, and the Python toolchain
> (`uv` / `pytest` / `ruff` / `mypy`) replaces the TypeScript one. A handful
> of process-shaping ADRs referenced below (FCS ADR-0009, 0014, 0018, 0019)
> live in the sibling repository and have **not** been ported to recall yet;
> they are listed in the ADR index so the lineage is visible and they can be
> ported when the corresponding stage of work begins.

## Philosophy

Three ideas underpin the process:

- **Peter Naur's Theory Building** — a system is not its code, it is the
  theory in the builders' minds about why the code is shaped the way it is.
  If the theory is lost, the code is effectively dead. AI agents produce code
  faster than humans can build theory; the process must close that gap.
- **Design-down** — five levels of progressive alignment (Capabilities →
  Components → Interactions → Contracts → Implementation), completed in
  order, with human gates between them. No code until Level 5.
- **Harness engineering** — **guides** (feedforward controls that steer
  before the agent acts: CLAUDE.md, skill definitions, design contracts) and
  **sensors** (feedback controls that enable self-correction: diagnostics,
  drift scans, PR reviews, the feature-evaluator agent).

## Pipeline overview

```
requirements → /kickoff → /architect → /feature → /feature-end → /retro
     (L0)        (L1–3)       (L4)        (L5)      (wrap-up)    (meta)
```

| Stage          | Owns levels       | Scope           | Primary artefacts                              |
| -------------- | ----------------- | --------------- | ---------------------------------------------- |
| Requirements   | —                 | project         | `REQUIREMENTS.md`                              |
| `/kickoff`     | L1–3              | project-wide    | HLD, load-bearing ADRs, implementation plan    |
| `/architect`   | L4                | per epic/task   | LLDs, enriched issue bodies                    |
| `/feature`     | L5                | per task        | code, tests, PR                                |
| `/feature-end` | —                 | per task        | session log, merged PR, updated LLD            |
| `/retro`, `/drift-scan` | —        | periodic        | reports in `docs/reports/`                     |

## The five design levels

Every feature passes through the same five levels, in order. The division of
responsibility across skills is deliberate: no single skill owns more than
two levels, and each level has a human gate before the next begins.

| Level | Name            | Owner skill   | Artefact                                             |
| ----- | --------------- | ------------- | ---------------------------------------------------- |
| 1     | Capabilities    | `/kickoff`    | HLD § Capabilities in `docs/design/v1-design.md`     |
| 2     | Components      | `/kickoff`    | HLD § Components                                     |
| 3     | Interactions    | `/kickoff`    | HLD § Interactions                                   |
| 4     | Contracts       | `/architect`  | LLD in `docs/design/lld-<epic>-<task>.md`            |
| 5     | Implementation  | `/feature`    | code under `src/recall/`, tests, PR                  |

→ See [ADR-0005](../adr/0005-project-bootstrap-pipeline.md) for the decision
to split Levels 1–3 from Level 4 across `/kickoff` and `/architect`.

## Stage 1 — Requirements

**Purpose.** Capture user stories, acceptance criteria, non-functional
constraints, and explicit non-goals. The requirements document is the single
source of human intent entering the system.

**Owner.** Human-authored or human-assisted. No skill currently owns
requirements capture.

**Artefacts.** `REQUIREMENTS.md` at the repository root.

**Exit criteria.** The requirements document is complete enough for
`/kickoff` to trace every component and capability back to at least one
requirement.

→ See [REQUIREMENTS.md](../../REQUIREMENTS.md) — the recall product spec.

## Stage 2 — Kickoff

**Purpose.** Turn requirements into project-wide Levels 1–3 design (the
HLD), the load-bearing ADRs the HLD forces, and an implementation plan
derived from the HLD. Bootstrap Phase 0 epics and tasks on the project
board.

**Owner skill.** [`.claude/skills/kickoff/SKILL.md`](../../.claude/skills/kickoff/SKILL.md)

**Inputs.** `REQUIREMENTS.md`, existing ADRs (for recall, ADR-0001 to
ADR-0004 are already accepted and load-bearing), current `CLAUDE.md`.

**Outputs.**

- `docs/design/v1-design.md` — HLD (Capabilities, Components, Interactions)
- `docs/adr/NNNN-*.md` — one ADR per load-bearing decision
- `docs/plans/YYYY-MM-DD-v1-implementation-plan.md`
- GitHub epics (all phases) + Phase 0 task issues on the board
- Refreshed `CLAUDE.md` with project-specific blocks updated

**Human gates.** Four:

1. After the HLD is drafted — drift-scan coverage matrix reviewed
2. After each ADR is drafted — approved individually
3. After the implementation plan is drafted — second drift-scan reviewed
4. After Phase 0 epics and tasks are proposed — confirmed before creation

**Sensors used.** `requirements-design-drift` agent.

→ See [ADR-0005](../adr/0005-project-bootstrap-pipeline.md) — why HLD before
plan, why the internal gates.

## Stage 3 — Architect

**Purpose.** Turn an epic's tasks into Level 4 contracts: LLDs with file
paths, internal types, function signatures, internal decomposition,
BDD specs, and acceptance criteria.

**Owner skill.** [`.claude/skills/architect/SKILL.md`](../../.claude/skills/architect/SKILL.md)

**Inputs.** An epic issue, the HLD section it references, any ADRs it
depends on.

**Outputs.**

- `docs/design/lld-<epic-slug>-<task-slug>.md` — one LLD per task
- Enriched task issue bodies with acceptance criteria and BDD specs

**Human gate.** LLD review before `/feature` is invoked.

> Cross-references to FCS ADR-0018 (epic/task organisation and LLD naming)
> and FCS ADR-0014 (API route contract types) apply conceptually here. They
> have not been ported into recall's ADR set yet because recall's work is
> not yet at the stage where those conventions are exercised. Port them
> when the first epic starts moving through `/architect`.

## Stage 4 — Feature

**Purpose.** Level 5 implementation via TDD, with diagnostics and
evaluation gates before the PR is created.

**Owner skill.** [`.claude/skills/feature/SKILL.md`](../../.claude/skills/feature/SKILL.md)
→ delegates to [`.claude/skills/feature-core/SKILL.md`](../../.claude/skills/feature-core/SKILL.md)

**Pipeline.**

1. Pick the top Todo item from the board, create a feature branch
2. Read the LLD and ADRs it references
3. Tests-first, batched per acceptance criterion (test + implementation in
   one turn, one criterion at a time) — the literal Red-Green cadence is
   relaxed to cut LLM round-trip cost; a dedicated ADR on TDD execution
   strategy is planned
4. Full test suite green (`uv run pytest` — unit and integration;
   integration tests hit real Postgres via testcontainers, per CLAUDE.md)
5. `/diag` — batch diagnostics check across changed files
6. **`feature-evaluator` agent** — maps acceptance criteria to test
   coverage, writes adversarial tests for gaps, returns pass/fail per
   criterion in a fresh context
7. Commit with cost retrospective in the PR body
8. Create PR
9. `/pr-review-v2` — 1 agent for small diffs, 2 for large
10. Fix any findings
11. **Stop for human review and merge**

**Human gate.** PR review and merge approval.

**Sensors used.**

- `diagnostics-exporter` (VS Code extension) + `/diag`
- `feature-evaluator` agent
- `/pr-review-v2`

> Conceptual references: the `feature-evaluator` agent pattern and the
> "evaluator in a fresh context" design are justified in the sibling
> project's FCS ADR-0019. Port that ADR into recall's numbering when the
> evaluator is first wired into this repo.

→ See CLAUDE.md § "Things to never do" for the hard limits every `/feature`
invocation must respect in recall (never mock the database, never bypass
`ruff`/`mypy`, never add MCP tools without updating REQUIREMENTS.md E2,
never widen the storage namespace without an ADR).

## Stage 5 — Feature-end

**Purpose.** Post-merge wrap-up: keep the LLD in sync with what was actually
built, log the session, close the issue, update the board.

**Owner skill.** [`.claude/skills/feature-end/SKILL.md`](../../.claude/skills/feature-end/SKILL.md)

**Actions.**

1. `/lld-sync` — compare the LLD against the merged code, update the LLD
   in-place
2. Write session log to `docs/sessions/YYYY-MM-DD-session-N-<issue>.md`
3. Merge the PR (if not already merged by the human)
4. Switch to parent branch, clean up local branch
5. Close the issue, move the board item to Done

→ See [`.claude/skills/lld-sync/SKILL.md`](../../.claude/skills/lld-sync/SKILL.md)
— the contract sync loop that prevents LLD drift.

## Stage 6 — Maintenance (periodic + gated)

Two skills maintain the harness itself rather than producing features:

- **`/drift-scan`** — garbage collection scan for drift between
  requirements, design artefacts, and implemented code. Output:
  `docs/reports/YYYY-MM-DD-drift-*.md`. Plays **two** roles: a mandatory
  gate inside `/kickoff` (after the HLD and after the implementation plan),
  and a periodic maintenance sweep.
- **`/retro`** — process retrospective across recent sessions, git history,
  board state, and drift reports. Identifies what is working, what is not,
  and what to change. Output: `docs/reports/YYYY-MM-DD-retro-*.md`.
  Consumes the latest drift report as input, so run `/drift-scan` first
  whenever both are due.

**When to run:**

| Trigger                                  | Skill(s)                            |
| ---------------------------------------- | ----------------------------------- |
| After HLD drafted (Gate 1)               | `/drift-scan` via `/kickoff`        |
| After implementation plan drafted (Gate 3) | `/drift-scan` via `/kickoff`      |
| Session end with significant code churn  | `/drift-scan`                       |
| Completing a batch of changes            | `/drift-scan`                       |
| End of a project phase                   | `/drift-scan` → `/retro`            |
| After 3–5 active sessions                | `/drift-scan` → `/retro`            |
| Before starting parallel work            | `/drift-scan` → `/retro`            |

→ See skill definitions in [`.claude/skills/drift-scan/`](../../.claude/skills/drift-scan/)
and [`.claude/skills/retro/`](../../.claude/skills/retro/).

## Human gates (summary)

Points where the human must explicitly approve before the pipeline advances.

| # | Gate                      | Stage        | What the human reviews                         |
| - | ------------------------- | ------------ | ----------------------------------------------- |
| 1 | HLD drafted               | `/kickoff`   | Drift-scan coverage matrix, component boundaries |
| 2 | Each ADR drafted          | `/kickoff`   | One ADR at a time                               |
| 3 | Implementation plan       | `/kickoff`   | Second drift-scan, phase sequencing             |
| 4 | Phase 0 board items       | `/kickoff`   | Epic and task list before creation              |
| 5 | LLD drafted               | `/architect` | Level 4 contracts before implementation         |
| 6 | PR ready                  | `/feature`   | Code, tests, evaluator verdict, review findings |

## Sensors (feedback controls)

Automated checks that catch problems after the fact and feed corrections
back into the process.

| Sensor                        | Stage        | What it catches                                 |
| ----------------------------- | ------------ | ----------------------------------------------- |
| `requirements-design-drift`   | `/kickoff`, `/drift-scan` | Requirements not covered by design; design with no requirement |
| `diagnostics-exporter` + `/diag` | `/feature` | Code health issues from CodeScene / SonarQube   |
| `feature-evaluator` agent     | `/feature`   | Acceptance criteria not verified by tests       |
| `/pr-review-v2`               | `/feature`   | Bugs, CLAUDE.md violations, framework misuse    |
| `/drift-scan`                 | periodic     | Drift between requirements, design, and code    |
| `/retro`                      | periodic     | Process health across sessions                  |

## Guides (feedforward controls)

Artefacts that steer agents before they produce output.

| Guide                    | Scope          | Where                                            |
| ------------------------ | -------------- | ------------------------------------------------ |
| `CLAUDE.md`              | every session  | [`/CLAUDE.md`](../../CLAUDE.md)                  |
| `REQUIREMENTS.md`        | every session  | [`/REQUIREMENTS.md`](../../REQUIREMENTS.md)      |
| Five design levels       | every feature  | This document, ADR-0005                          |
| TDD discipline           | every feature  | CLAUDE.md § Engineering practice                 |
| SKILL.md files           | per skill      | `.claude/skills/*/SKILL.md`                      |
| ADRs                     | project-wide   | `docs/adr/`                                      |
| HLD                      | project-wide   | `docs/design/v1-design.md` (produced by `/kickoff`) |
| LLDs                     | per epic/task  | `docs/design/lld-*.md`                           |

## Artefact map

Where every kind of artefact lives and which skill owns it.

| Artefact                | Location                                    | Owner skill                | Level |
| ----------------------- | ------------------------------------------- | -------------------------- | ----- |
| Requirements            | `REQUIREMENTS.md`                           | human                      | —     |
| HLD                     | `docs/design/v1-design.md`                  | `/kickoff`                 | 1–3   |
| ADRs                    | `docs/adr/NNNN-*.md`                        | `/create-adr`, `/kickoff`  | any   |
| Implementation plan     | `docs/plans/YYYY-MM-DD-*.md`                | `/kickoff`                 | —     |
| Epic issues             | GitHub Issues (`epic` label)                | `/kickoff`                 | —     |
| Task issues             | GitHub Issues (`L5-implementation`)         | `/architect`, `/kickoff`   | —     |
| LLDs                    | `docs/design/lld-<epic>-<task>.md`          | `/architect`, `/lld`       | 4     |
| Code                    | `src/recall/`                               | `/feature`                 | 5     |
| Tests                   | `tests/` (integration marked `@pytest.mark.integration`) | `/feature`     | 5     |
| Adversarial tests       | `tests/evaluation/`                         | `feature-evaluator` agent  | 5     |
| Session logs            | `docs/sessions/YYYY-MM-DD-session-N-*.md`   | `/feature-end`             | —     |
| Drift reports           | `docs/reports/*-drift-*.md`                 | `/drift-scan`              | —     |
| Retro reports           | `docs/reports/*-retro-*.md`                 | `/retro`                   | —     |
| Diagnostics             | `.diagnostics/` (mirror of `src/`)          | `diagnostics-exporter`     | —     |

## Skill index (by stage)

Skills listed in the order they typically run during a project lifecycle.

| Skill            | Purpose                                                              | SKILL.md                                                                 |
| ---------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `/kickoff`       | Bootstrap: HLD + ADRs + plan + Phase 0 board items                   | [link](../../.claude/skills/kickoff/SKILL.md)                            |
| `/create-adr`    | Produce an ADR for a load-bearing decision                           | [link](../../.claude/skills/create-adr/SKILL.md)                         |
| `/create-plan`   | Implementation plan from an existing HLD                             | [link](../../.claude/skills/create-plan/SKILL.md)                        |
| `/architect`     | Per-epic LLDs + enriched task issue bodies                           | [link](../../.claude/skills/architect/SKILL.md)                          |
| `/lld`           | Generate LLDs for a phase or section                                 | [link](../../.claude/skills/lld/SKILL.md)                                |
| `/feature`       | Autonomous implementation cycle for the top Todo task                | [link](../../.claude/skills/feature/SKILL.md)                            |
| `/feature-core`  | Shared implementation pipeline called by `/feature` and `/feature-team` | [link](../../.claude/skills/feature-core/SKILL.md)                    |
| `/feature-team`  | Parallel implementation via agent teams (CLI only)                   | [link](../../.claude/skills/feature-team/SKILL.md)                       |
| `/diag`          | Batch diagnostics check across changed files                         | [link](../../.claude/skills/diag/SKILL.md)                               |
| `/pr-review-v2`  | PR review (bugs, CLAUDE.md compliance, design adherence)             | [link](../../.claude/skills/pr-review-v2/SKILL.md)                       |
| `/lld-sync`      | Sync LLD to the implementation after the feature is merged           | [link](../../.claude/skills/lld-sync/SKILL.md)                           |
| `/feature-end`   | Post-merge wrap-up                                                   | [link](../../.claude/skills/feature-end/SKILL.md)                        |
| `/drift-scan`    | Garbage collection scan                                              | [link](../../.claude/skills/drift-scan/SKILL.md)                         |
| `/retro`         | Process retrospective                                                | [link](../../.claude/skills/retro/SKILL.md)                              |

## ADR index (process-shaping)

The ADRs that shape **the process itself**, not individual product decisions.
For product ADRs (ADR-0001 to ADR-0004), see [`docs/adr/`](../adr/).

| ADR      | Title                                            | Status in recall                                  |
| -------- | ------------------------------------------------ | ------------------------------------------------- |
| [0005](../adr/0005-project-bootstrap-pipeline.md) | Project bootstrap pipeline       | Accepted (ported from FCS ADR-0021)               |
| FCS-0009 | Test diamond strategy                            | Not ported — lives in sibling FCS repo, applies conceptually to test layer ratios |
| FCS-0014 | API route contract types                         | Not ported — recall does not have HTTP API routes in the same sense; revisit if/when MCP tool contracts grow complex |
| FCS-0018 | Epic/task organisation                           | Not ported — port when the first epic lands       |
| FCS-0019 | Feature evaluator agent                          | Not ported — port when the evaluator is first wired into this repo |

## When things go wrong

- **Scope creep during kickoff.** The first drift scan should catch it.
  Look for components with no requirement.
- **AI gravitating to novel problems.** The first drift scan should also
  catch this — look for requirements with no component coverage.
- **LLDs drifting from code.** `/lld-sync` runs at `/feature-end` to pull
  the LLD back in line with what was actually built.
- **Process degradation over time.** `/retro` reviews recent sessions and
  surfaces changes worth making to the harness itself.
- **Requirements / design / code out of sync.** `/drift-scan` is the
  garbage collector.

## Related reading

- [CLAUDE.md](../../CLAUDE.md) — the contract loaded every session.
- [REQUIREMENTS.md](../../REQUIREMENTS.md) — the recall product spec.
- [`docs/adr/`](../adr/) — full ADR history.
