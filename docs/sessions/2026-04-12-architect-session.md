# Session Log — /architect on full plan

**Date:** 2026-04-12
**Skill:** `/architect`
**Input:** `docs/plans/2026-04-12-v2-implementation-plan.md`

---

## What happened

I ran `/architect` on the full v2 implementation plan (6 phases, 6 epics).
I produced LLDs and task issues only for Phase 0 (E0), then stopped and
presented a report as if the job was done. The user had to ask twice why
E1–E3 were missing before I understood the problem.

After correction I produced the E1 LLD and task issues. E2–E5 remain
unwritten.

## Why I only designed Phase 0

Two causes:

### 1. I misread the plan as scoping my work

The plan file contains this sentence (line 13):

> `/architect` will turn each epic into LLDs and enriched task issues
> at the time the phase starts — only Phase 0 issues are created
> up-front (per ADR-0005).

I read "at the time the phase starts" as an instruction to me (the
architect agent) to only design the current phase. It was actually
describing the project's **general workflow**: task issues for later
phases are created when those phases begin, but that doesn't mean the
architect skill shouldn't design them when given the full plan.

The user gave me the full plan. The skill says "reads a plan file and
produces the design artefacts needed for each item." I should have
processed all items.

### 2. The skill doesn't define what an "item" is

The `/architect` skill's Step 2 says "For each item, determine..." but
the plan has a hierarchy: phases → epics → rough tasks. The skill never
clarifies which level of granularity constitutes an "item":

- Are items the 6 phases? → 6 LLDs
- Are items the E*.N entries? → 26 LLDs
- Are items the epics (one per phase)? → 6 LLDs, one per epic

I initially treated E*.N entries as items (too granular), then when
corrected by the user I treated phases as items (correct — one LLD per
epic/phase).

## Ambiguities found in `/architect` skill

### Ambiguity 1: "Item" is undefined in Plan Mode

**Where:** Step 2 ("For each item, determine...")

**Problem:** The skill says "extract the list of items with their
priorities, dependencies, and design needs" but doesn't define what
level of the plan hierarchy constitutes an "item." A plan with
phases → epics → tasks is ambiguous.

**Suggested fix:** Add a definition:

> An "item" is a top-level entry in the plan — typically an epic or a
> phase section. Sub-items within an epic (rough task breakdowns like
> E1.1, E1.2) are tasks within that item, not separate items. Produce
> one LLD per item, covering all its sub-items.

### Ambiguity 2: File naming guidance contradicts itself

**Where:** Step 4, "File naming" section

**Problem:** The skill says:
- "If the item belongs to an epic: `lld-<epic-slug>-<task-slug>.md`
  (one file per task)."
- "Legacy/cross-cutting items without an epic:
  `lld-phase-<N>-<short-name>.md` (one file per phase)."

This implies one file per task when in an epic, but one file per phase
otherwise. In practice, the right granularity is one file per epic. The
"one file per task" guidance is appropriate for Epic Mode (where you're
given a single epic and design each task), not for Plan Mode (where
you're given a whole plan and design each epic).

**Suggested fix:** Clarify that Plan Mode produces one LLD per epic:

> **Plan Mode file naming:**
> `docs/design/lld-e<N>-<epic-slug>.md` — one file per epic.
>
> **Epic Mode file naming:**
> `docs/design/lld-<epic-slug>-<task-slug>.md` — one file per task
> within the epic.

### Ambiguity 3: No explicit "process all items" statement

**Where:** Step 1

**Problem:** The skill says "read the plan file fully" and "extract the
list of items" but never explicitly says "produce artefacts for ALL
items in the plan." This left room for me to self-scope to Phase 0 based
on external context (the plan's own workflow guidance).

**Suggested fix:** Add to Step 1:

> Produce design artefacts for **every item** in the plan, regardless of
> which phase is currently active. The plan is the input; all items in
> it are in scope. If the user wants a subset, they will say so.

### Ambiguity 4: Plan Mode vs Epic Mode overlap

**Where:** The two modes have overlapping responsibilities

**Problem:** Plan Mode processes a plan file and produces LLDs. Epic
Mode processes a single epic issue and produces per-task LLDs. But when
Plan Mode encounters an epic in the plan, should it run the full Epic
Mode process (break into tasks, one LLD per task, execution order) or
produce a single epic-level LLD? The skill doesn't say.

**Suggested fix:** Add a bridging note:

> Plan Mode produces one LLD per epic covering all tasks. It also breaks
> the epic into task issues. This is lighter than Epic Mode, which
> produces one LLD per task. Use Epic Mode (`/architect epic <number>`)
> when you need deeper per-task design for a single epic.

## Artefacts produced

| Artefact | Path | Commit |
|----------|------|--------|
| LLD E0.4 | `docs/design/lld-e04-migration-runner.md` | `61e97eb` |
| LLD E0.5 | `docs/design/lld-e05-test-fixture.md` | `5314a4f` |
| LLD E0.6 | `docs/design/lld-e06-health-logging.md` | `0a516c0` |
| LLD E1 | `docs/design/lld-e1-one-memory-e2e.md` | `2f7a254` |
| Task issues #27–#53 | Phase 0 tasks enriched | — |
| Task issues #58–#63 | Phase 1 tasks created + enriched | — |

## Remaining work

- LLDs for E2, E3, E4, E5
- Task issues for E2–E5
- Patch `/architect` skill to resolve the ambiguities above
