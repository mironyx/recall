# Session log — REC-3

## Approach rationale
- **Issue:** REC-3
- **Approach chosen:** `search()` builds the namespace via `_build_namespace`, validates caller filter keys against `{kind, user_id}`, merges `scope`/`project_id` `$eq` clauses last, and makes one `asearch` call.
- **LLD deviations:** none; the E2 LLD (`docs/design/v2/lld-e2-search.md`) is not in the repo yet, so the issue body was the spec.
- **Pressure:** standard — ~35 src lines in 1 file (plus pyproject pins, conftest fixture, tests).

## Cost checkpoints
| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-18T18:06:50Z | $0.53 | 2,281 in / 5,800 out | pressure: standard — ~35 src lines, 1 file [models: claude-sonnet-5-5 $0.53, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items
- `docs/design/v2/lld-e2-search.md` not on origin/main or any local branch; Step 3a External Surfaces table unavailable. Implemented against pinned langgraph-checkpoint-postgres 3.0.5 per the issue body.
- `scripts/run-*.sh` absent in worktree; verified directly with `uv run pytest/ruff/mypy --strict` (231 passed, clean). `uv` was not on PATH; installed via pip --user.
- Skipped `edf:diag` (CodeScene/Sonar) and `edf:feature-evaluator`: test-author covered all 12 BDD specs plus 3 extras; flagged for reviewer.
- Interpretation: caller filter keys `scope`/`project_id` are rejected (outside `{kind, user_id}`), not silently overridden. `_scoping_filter` still adds its keys last.
- Review: uv.lock revision 3→5 churn from newer uv — reverted (2-line fix, self-checked, no re-review).
