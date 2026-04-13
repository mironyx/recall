# Session Log — Board cleanup and skill consistency

**Date:** 2026-04-13
**Duration:** ~1 hour
**Scope:** Project board cleanup, `/architect` skill rewrite, issue-creation consistency across skills

---

## What happened

### 1. Board audit and cleanup

The GitHub project board (Project #3) had two problems:

- **4 closed issues still on the board** — #23 (E5.2: Compactor), #24 (E6.1: Project export), #25 (E6.2: Audit), #26 (E6.3: Documentation pass). These were from the old E5/E6 structure before the plan consolidated everything into E5. Removed all four.
- **Items #1–53 had "No Status"** — they were added to the board but never had their status field set. Set all 59 remaining items to "Todo".

### 2. `/architect` skill — removed epic mode

The skill had two divergent code paths:
- **Plan mode** — full process (decision logic, Part A+B LLDs, ADR support, enrichment, execution waves)
- **Epic mode** — simplified process (no decision logic, abbreviated LLD template, no ADRs, no enrichment)

The user decided to keep only plan mode with an `--epics` filter. Changes:

- Removed epic mode entirely (lines 20–138)
- Added `--epics` flag: `E2` expands to all Phase 2 epics, `E2.1` targets one epic, combinable
- Step 1 now parses the filter and reports which epics are in/out of scope
- Updated `/kickoff` Step 9 reference from `/architect epic <N>` to `/architect --epics E0`

### 3. Issue-creation consistency

Audited all skills that create GitHub issues (`/kickoff`, `/architect`, `/frontend-architect`) and found:

| Problem | Fix |
|---------|-----|
| No shared dedup — each skill had its own check or none | Created `scripts/gh-create-issue.sh` with automatic exact-title dedup |
| Inconsistent body templates and labels | Standardised: epics get `epic,phase-N,area:X`, tasks get `phase-N,area:X,kind:scaffold` |
| `/feature` looked for `L5-implementation` label that didn't exist on actual issues | Changed to `kind:scaffold` in `/feature` and `/feature-end` |
| `gh-project-status.sh` hardcoded repo-specific project IDs | Refactored to read from `.github/project.env` |
| No board `remove` command | Added `remove <issue-number>` to the script |

### Files changed

| File | Change |
|------|--------|
| `scripts/gh-create-issue.sh` | **New** — shared issue creation with dedup, board integration, dry-run |
| `scripts/gh-project-status.sh` | Refactored — config from `.github/project.env`, added `remove` command |
| `.github/project.env` | **New** — board config (project ID, field ID, status option IDs) |
| `.claude/skills/architect/SKILL.md` | Epic mode removed, `--epics` filter added, uses shared script |
| `.claude/skills/kickoff/SKILL.md` | Uses shared script, standard templates, fixed `/architect` reference |
| `.claude/skills/frontend-architect/SKILL.md` | Uses shared script, standard labels |
| `.claude/skills/feature/SKILL.md` | `L5-implementation` → `kind:scaffold` |
| `.claude/skills/feature-end/SKILL.md` | `L5-implementation` → `kind:scaffold` |

## Decisions

- **One mode for `/architect`** — plan mode with optional `--epics` filter replaces the old plan+epic dual modes. Rationale: epic mode was a subset of plan mode's capabilities, causing inconsistent LLD quality.
- **`kind:scaffold` is the task label** — not `L5-implementation`. All issue-creating and issue-consuming skills now agree on this.
- **Board config is externalised** — `.github/project.env` makes the scripts portable across repos.

## Portability notes (for new repos)

To reuse the board and issue scripts in a different repo:

1. Copy `scripts/gh-project-status.sh` and `scripts/gh-create-issue.sh`
2. Create `.github/project.env` with repo-specific values
3. Get IDs via: `gh project field-list <number> --owner <owner>`

## Open items

- LLDs for E2–E5 still need to be produced: `/architect --epics E2,E3,E4,E5`
- Skill consistency for issue body templates could be further tightened (e.g. a shared body-builder script), but current state is good enough
- The `kind:scaffold` label name may want revisiting once we're past Phase 0 — "scaffold" implies bootstrapping work, not feature implementation
