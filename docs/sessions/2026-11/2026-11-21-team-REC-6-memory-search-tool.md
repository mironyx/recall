# Team session log — REC-2 final wave (REC-6)

## Issues shipped

| Issue | Story | PR | Branch | Merged |
|---|---|---|---|---|
| REC-6 | 2.1–2.3, 2.5 (`memory_search` tool) | #128 | feat/memory-search-tool | 2026-11-21T09:08Z |

Earlier E2 tasks shipped solo: REC-3 (#122), REC-4 (#125), REC-5 (#126), REC-7 (#127). REC-7's feature-end was run by the lead directly, not a teammate.

## Cross-cutting decisions
- `scope='global'` with a `project_id` fails the adapter invariant, so the router maps global to the sentinel project ID (LLD §2.4).
- The internal-error hint advises a retry; no spec backs this (LLD §2.5 records it). Revisit for non-idempotent `memory_save`.

## Coordination events
- One teammate, one wave (blockers REC-7 and GH #91 were already done). A team added no parallelism.
- Human gate honoured: merge forwarded only after the user typed `edf:feature-end REC-6`.
- Several teammate idle messages were answers to questions asked in its own pane; none needed action.

## What worked / what didn't
- Worked: claims-ledger findings were resolved as LLD wording fixes instead of code changes.
- Didn't: no CI ran on PR #128's head (`ci: none`); test-author, evaluator and CodeScene/Sonar diag were skipped; repo lacks `scripts/run-*.sh` despite CLAUDE.md.
- Tool-count question: requirements mention `memory_list` (line 707), so the "5 tools" plan may really be 6.

## Process notes for edf:retro
- Add `scripts/run-*.sh` or correct CLAUDE.md's script contract.
- Investigate why CI did not run on the PR head; a green local run was the only verification.
- Final-cost query returned $0 for REC-7 (no Prometheus data); labels are unreliable there.
- Open: `_PerCallClient` in `tests/conftest.py` imports from `test_e2e_phase1` (deferred, TODO in code).
