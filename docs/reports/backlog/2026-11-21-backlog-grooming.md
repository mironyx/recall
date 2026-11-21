# Backlog Grooming

**Date:** 2026-11-21
**Period since last grooming:** first grooming
**Declared phase (CLAUDE.md):** none declared (CLAUDE.md names no "Current Phase"; phases come from the v2 implementation plan)

## Summary

| Column | Count |
|--------|-------|
| Todo | 1 (REC-1, a placeholder) |
| In Progress | 0 |
| Blocked | 0 |
| Done (since last grooming) | 6 (REC-2 epic, REC-3 to REC-7) |

The board is drained: the only open issue is REC-1 "Test item1", an empty placeholder. Phase 2 (Search) shipped in full between 2026-11-18 and 2026-11-21, and no issues exist yet for Phases 3 to 5. Health verdict: clean, but the next work needs `/architect` before `/feature` can run.

## Phase accuracy

CLAUDE.md declares no current phase, so there is nothing to contradict. By activity we are at the **Phase 2 → Phase 3 boundary**: E2.1–E2.5 are closed (PRs #122, #125, #126, #127, #128) and the Phase 2 exit criterion (ADR-0010 ranking E2E over real pgvector) is covered by REC-6.

Proposed edit to CLAUDE.md (not actioned): add `**Current phase:** 3 — Update, delete, full tool surface (Phase 2 complete 2026-11-21)` under the project overview.

Two naming mismatches to resolve in `/architect`:

- The plan's **Phase 3** (update/delete/errors) maps to requirements **Stories 1.4, 1.5 and 4.3**. Requirements **Epic 3** (Self-Improving Instructions) maps to plan **Phase 5**. Phase and epic numbers do not line up.
- The REC-2 labels `epic, phase-2` follow the plan numbering, so new issues should use `phase-3` and so on.

## Progress since last grooming

- Closed: REC-2 epic: E2 Search; REC-3 (E2.1 storage vector search); REC-4 (E2.2 service search); REC-5 (E2.3 merge ranking); REC-6 (E2.4 `memory_search` tool); REC-7 (E2.5 router hardening).
- Commits in the last 14 days: 15, nearly all E2 plus docs. Cadence is about 1 task per day.

## Actions from previous grooming

None: this is the first grooming report. There are no prior drift, retro or baseline reports in `docs/reports/`.

## In-flight health

Nothing In Progress or Blocked. Process concerns recorded in the session logs:

- **PR #128 had no CI run on its head** (`ci: none`). The only verification was a green local run.
- **`scripts/run-*.sh` do not exist.** CLAUDE.md's verification contract lists seven scripts, but `scripts/` holds only helper scripts. Skills fall back to ad-hoc commands, and the test-author, evaluator and CodeScene/Sonar diag steps were skipped on REC-6.
- **Cost labels unreliable** on REC-7 (`ai-cost-final:0.0000`, no Prometheus data).

## Backlog health findings

| # | Issue | Finding | Severity |
|---|-------|---------|----------|
| 1 | REC-1 | Placeholder "Test item1": empty body, no labels, no parent, no ACs | Info (delete or close) |
| 2 | (board) | No issues for Phases 3–5 (E3.1–E5.3, 8 plan items). Expected per ADR-0005 (issues created per phase by `/architect`), but the board is empty | Warning |
| 3 | REC-3 to REC-7 | Cost labels (`ai-cost-*`, `input-tokens-*`) cause label noise; REC-7 shows $0 final | Info |
| 4 | Docs | Tool-count ambiguity: requirements line ~707 lists `memory_list_kinds` as an open question; the tool table has 5 tools with a ≤ 6 budget | Info |

## Requirements coverage

Source: `docs/requirements/v2-requirements.md` (the only requirements file).

### Current version (v2) gaps

Delivered (per code and closed issues): 1.1 save, 1.3 embedding on save, 2.1–2.3, 2.5 search (REC-3 to REC-6), 2.4 get (E1), 4.1 transport, 4.2 tool descriptions (partial), 5.x auth/validation/namespace (E1), 6.2 migrations, 6.3 health (Phase 0).

Gaps with **no issue**:

- **Story 1.4** memory update, **Story 1.5** memory delete. Tools `memory_update` and `memory_delete` do not exist in `tool_router.py` (only save, get, search).
- **Story 4.3** structured error vocabulary. Only partial: `internal_error` added in REC-7.
- **Story 4.2/4.4** description and tool-budget verification across all five tools.
- **Story 1.2** scope invariants on update paths (arrives with update).
- **Stories 3.1–3.4** instruction kind round-trip, override convention docs, operator curation.
- **Stories 6.1, 6.4, 6.5** container, env config and docker-compose polish. Partly done in Phase 0; the real-embeddings and compose story is Phase 4.
- **Stories 7.1, 7.2** reference agent instructions and MCP config snippet.
- **Cross-cutting** JSON export (`recall export`) and OTEL export.

### Parked future ideas (not yet scheduled)

- **Story 3.5** instruction compaction (deferred, needs an LLM service).
- **GC job** for global memories (deferred to v2.1).
- **Per-user-private memories** (v3); tag filtering (ADR-0004); project registry (ADR-0014, dropped).
- **Open question** `memory_list_kinds` (requirements line ~707).

## Signals from reports

No drift, retro or baseline reports exist. Signals taken from session logs and ADRs instead.

### From recent session logs

- `tests/conftest.py` `_PerCallClient` imports from `test_e2e_phase1` and uses `client._session` (TODO, REC-6 review warn). No issue.
- `SearchConfig` does not reject `max_limit` < 1 or negative `snippet_max_chars` (REC-4). Deferred, no issue.
- HNSW iterative scan / `hnsw.ef_search` tuning is deferred to E4 operations (`lld-e2-search.md`:163). No issue.
- Internal-error hint advises retry. It could cause duplicate writes on non-idempotent `memory_save`; revisit (REC-7).
- Missing `scripts/run-*.sh`, and CI not running on PR heads (team log, process notes for retro).

### From recent ADRs

ADR-0014 (project registry deferred) and ADR-0015 (scope-explicit IDs) imply no new work. The ADR-0004 tag filtering deferral is parked.

## Creative / research proposals

No web research was done; this is a desk review.

- **Duplicate-write guard for `memory_save`** — source: session-log theme (REC-7 retry hint). Rationale: retry advice plus non-idempotent save can double-write. Options: client-supplied idempotency key or a content-hash check. Effort: low–med.
- **Search quality eval fixture** — source: creative. Rationale: ranking is verified with stub embeddings only. A small labelled query/memory set run against the real provider would catch embedding or boost regressions when E4.1 lands. Effort: med.
- **`memory_search` p50/p95 latency metric** — source: creative. Rationale: the first guard for pgvector filter and `ef_search` behaviour, ahead of E4 tuning. Effort: low.

## Recommended next (≥10 items, propose-only)

Nothing on the board is rankable except REC-1. Everything below is **proposed, not yet created**. Score = 0.4V + 0.3U + 0.2R + 0.1(1−E).

### Top priority (score ≥ 0.6)

| Rank | # / proposal | Title | Score | V | U | R | 1-E | Rationale |
|------|--------------|-------|-------|---|---|---|-----|-----------|
| 1 | (new) | E3.1 `memory_update`: content-vs-metadata path, re-embed only on content change (Story 1.4) | 0.67 | 0.9 | 0.5 | 0.5 | 0.6 | Largest requirement gap; completes the CRUD surface |
| 2 | (new) | Investigate why CI did not run on PR #128's head | 0.62 | 0.5 | 0.6 | 0.8 | 0.8 | Every merged PR is otherwise unverified remotely |

### Worth doing soon (0.45–0.59)

| Rank | # / proposal | Title | Score | V | U | R | 1-E | Rationale |
|------|--------------|-------|-------|---|---|---|-----|-----------|
| 3 | (new) | Add `scripts/run-*.sh` verification contract | 0.58 | 0.4 | 0.6 | 0.8 | 0.8 | Skills depend on them; skipped checks on REC-6 |
| 4 | (new) | E3.2 `memory_delete` (Story 1.5), idempotent | 0.57 | 0.8 | 0.3 | 0.4 | 0.8 | Small, mirrors update; closes Phase 3 tool surface |
| 5 | (new) | E4.1 real embeddings providers (sentence-transformers + OpenAI-compatible, ADR-0008) | 0.57 | 0.8 | 0.5 | 0.3 | 0.4 | Only stub embeddings exist today; ranking untested on real vectors |
| 6 | (new) | E3.3 full structured-error vocabulary (Story 4.3) | 0.49 | 0.6 | 0.3 | 0.5 | 0.6 | `internal_error` only so far; agents need stable codes |
| 7 | (new) | E4.3 deployment artefacts and operator docs (compose, env contract, MCP snippet) | 0.49 | 0.8 | 0.2 | 0.3 | 0.5 | Needed before anyone else can use it |
| 8 | (new) | E5.1 instruction kind end-to-end (Stories 3.1–3.3) | 0.46 | 0.7 | 0.2 | 0.3 | 0.6 | Core product promise (self-improving instructions) |

### Lower priority (<0.45)

| Rank | # / proposal | Title | Score | V | U | R | 1-E | Rationale |
|------|--------------|-------|-------|---|---|---|-----|-----------|
| 9 | (new) | E5.3 reference agent instructions + MCP config (Stories 7.1/7.2) | 0.41 | 0.6 | 0.1 | 0.3 | 0.8 | Cheap, but meaningful only after tools are complete |
| 10 | (new) | Extract shared e2e helpers from `test_e2e_phase1` (conftest TODO) | 0.35 | 0.2 | 0.3 | 0.5 | 0.8 | Fragile test coupling; every new tool test will add to it |
| 11 | (new) | E4.2 OTEL exporter activation | 0.31 | 0.4 | 0.1 | 0.3 | 0.6 | No-op mode works today |
| 12 | (new) | E5.2 `recall export <project_id>` JSON export | 0.29 | 0.4 | 0.1 | 0.2 | 0.6 | Nice to have; cross-cutting requirement |
| 13 | (new) | Resolve tool-count / `memory_list_kinds` open question | 0.28 | 0.2 | 0.1 | 0.4 | 0.9 | Decide before E3.x touches the tool table |
| 14 | (new) | Reject invalid `SearchConfig` (`max_limit` < 1, negative snippet length) | 0.23 | 0.2 | 0.0 | 0.3 | 0.9 | Trivial hardening |
| 15 | REC-1 | Delete or close placeholder | 0.16 | 0.1 | 0.0 | 0.1 | 1.0 | Board hygiene |

## Proposed new issues (NOT created — human-approve to action)

Phase 3 items are best created through `/architect` (LLD + enriched bodies), not by hand.

- [ ] **E3.1 `memory_update` tool** — source: requirements gap (Story 1.4).
  - Labels: `kind:task`, `phase-3`, `area:tools`. Epic: new "E3 — Update, delete, full surface".
  - AC: update content re-embeds; metadata-only update does not; namespace-explicit (ADR-0015); not-found gives a structured error; scope invariant holds.
- [ ] **E3.2 `memory_delete` tool** — source: requirements gap (Story 1.5). Same labels and epic. AC: deleted memory is gone from get and search; second delete is defined (idempotent `ok` or not-found); namespace-explicit.
- [ ] **E3.3 Structured error vocabulary** — source: requirements gap (Story 4.3). AC: documented codes for each failure class; every tool has ≥ 1 happy and 1 error path test (Phase 3 exit).
- [ ] **CI did not run on PR head** — source: session log (team REC-6). Labels: `kind:task`, `area:ci`. AC: a PR head triggers ci.yml; a branch-protection rule requires it.
- [ ] **`scripts/run-*.sh` contract** — source: session log / CLAUDE.md. Labels: `kind:task`, `area:tooling`. AC: all seven scripts exist, match CLAUDE.md's table, and exit non-zero on failure.
- [ ] **E4.1 real embeddings providers** — source: plan Phase 4. AC: provider selected by env var; cold start does not block readiness incorrectly; integration test with the real model gated by marker.
- [ ] **E4.3 deployment artefacts / operator docs**, **E5.1 instruction kind**, **E5.3 agent integration docs**, **E4.2 OTEL**, **E5.2 export** — source: plan Phases 4–5; create at phase start via `/architect`.
- [ ] **Test-helper extraction**, **SearchConfig validation**, **`memory_list_kinds` decision** — source: session logs / open question. Low priority; file when touching those areas.

## Proposed reprioritisation (NOT actioned)

- Run `/architect` for Phase 3 first. Order: E3.1 → E3.2 → E3.3, with the CI and `scripts/run-*.sh` fixes ahead of or alongside E3.1 so the new work is verified remotely.
- Delay E5.x until Phase 3 is done; Phase 5's instruction round-trip depends on update and delete semantics.

## Proposed issue edits (NOT actioned)

- REC-1: delete or close.
- REC-3 to REC-7: no edits needed. Consider dropping `ai-cost-*` and `*-tokens-*` labels from issue labels in favour of session logs, to keep label hygiene.
- CLAUDE.md: add a current-phase line (see Phase accuracy).
