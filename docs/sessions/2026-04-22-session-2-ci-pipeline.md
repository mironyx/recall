# Session log — E0.2 CI pipeline (#74)

**Date:** 2026-04-22
**Issue:** [#74 — E0.2 CI pipeline](https://github.com/mironyx/recall/issues/74)
**PR:** [#80 — feat: PR template and testcontainers-aligned CI](https://github.com/mironyx/recall/pull/80)
**Branch:** `feat/e02-ci-pipeline`
**Base:** `main`

## Work completed

- Added `.github/pull_request_template.md` covering Summary, Issue (tracker-agnostic hint), Design reference, ADRs, Design deviations, Test plan, Verification (tests added / total), Process notes, and Usage (OTel tokens / cost / wall time / trace link).
- Removed the `services.postgres` preprovision block and `DATABASE_URL` env from the `integration-tests` job so testcontainers owns the container lifecycle per ADR-0012. Docker is preinstalled on `ubuntu-latest`, so no extra runner setup is required.
- Verified the pipeline end-to-end: the PR itself is the "no-op PR" required by the issue's acceptance criterion. CI run 24778313820 all four jobs passed (quality, unit-tests, integration-tests, docker).

Two commits:
1. `2c62acf` — initial template + CI realignment.
2. `ff2131b` — expanded template with Verification / Process notes / Usage sections after user feedback.

## Decisions made

- **No code tests, by design.** Issue body explicitly states *"No code tests — CI is validated by a green pipeline on a no-op PR."* Step 4 (test-author sub-agent) and Step 6b (feature-evaluator) of `/feature-core` were skipped — documented as deviations in the PR body under *Design deviations*. The PR itself validates the pipeline.
- **Model directory cache deferred.** The E0.2 plan entry mentions *"Cache `uv` and the model directory for speed."* `uv` cache is already enabled via `astral-sh/setup-uv@v3`. A HuggingFace model cache would key into a never-populated directory until ADR-0008 embedding code lands, so deferring avoids a hollow cache step. Will add alongside the first embedding integration test.
- **Kept the consolidated `quality` job** (lint + format + typecheck + markdownlint in one job) rather than splitting into separate lint / typecheck jobs. The AC reads "lint → typecheck → unit → integration" as *stages*; steps inside `quality` preserve the stage order and each shows as a distinct step in the Actions UI. Splitting would triple the `uv sync` cost for no signal gain.
- **No LLD for this task** — skipping `/lld-sync` (documented per `feature-end` Step 1.5). E0.2 is an infrastructure task with acceptance criteria expressed directly as config artefacts (workflow jobs + PR template); an LLD would add no detail the YAML does not already express.

## Review feedback addressed

- `/pr-review-v2` on PR #80: no blockers, no warnings. Two observations noted (pre-existing unpinned action tags on `setup-uv@v3` and `markdownlint-cli2-action@v17`; minor wording inconsistency in the template between "delete if inapplicable" and `"write 'None'"`). Neither was actioned — the action tags were introduced in #79 and are out of scope; the template wording is minor enough to leave alone.
- User feedback after initial template landed: add Verification, Process notes, and Usage (OTel cost) sections. Addressed in the `ff2131b` follow-up commit.

## CI outcome

Run 24778313820 on PR #80 — **all green**:

- `quality` (lint, format, mypy, markdownlint): success
- `unit-tests`: success
- `integration-tests (Postgres + pgvector)`: success (0 integration tests collected yet; exit-code-5 fallback kept in place)
- `docker`: success

This satisfies the final acceptance bullet: *"A no-op PR triggers the workflow and all stages pass."*

## Cost retrospective

- **PR creation cost (PR body):** Not captured — `Usage` section marked *Not captured* because the prom metric stream was empty at PR time.
- **Final feature cost (`query-feature-cost.py --stage final`):** `$0.0000`, `0 tokens`, `5 min` wall time.
- **Delta:** n/a — Prometheus captured no token events for this session.

Prometheus metrics not flowing end-to-end for this session (same symptom as session-1 on 2026-04-22). The `scripts/tag-session.py` call succeeded and wrote `session_feature.prom`, but `query-feature-cost.py` returns zero tokens — so the token-counting side of the pipeline is the missing link, not the session tag. Not a blocker for this feature, but the observability task needs to reconcile.

**Qualitative cost drivers:**

| Driver | Observed? | Notes |
|--------|-----------|-------|
| Context compaction | No | Session stayed under compaction threshold. |
| Fix cycles (RED→fix) | No | No Python tests written; nothing to iterate on. |
| Agent spawns | 1 (ci-probe) | Minimal — skipped test-author and evaluator per issue spec. |
| LLD quality gaps | n/a | No LLD. |
| Mock complexity | n/a | No Python. |

**Improvement actions for future config-only tasks:**

1. `/feature-core` assumes Python behavior implementation; for pure config tasks, the test-author and evaluator steps are dead weight. Worth a short-circuit condition in the skill — e.g., if the issue body says "no code tests", skip directly from Step 3 to Step 5.
2. The CI previously had a `services.postgres` block from the initial import that contradicted ADR-0012. Would have been caught earlier by a drift-scan after the ADRs landed. Consider running `/drift-scan` as a gate after new ADRs are accepted.
3. The HuggingFace cache decision (defer vs add-now) was a judgement call made in-flight; a short note on "speculative cache steps" in the CI style guide would save the next contributor the 2-minute reasoning.

## Next steps

E0.2 closes. Wave 2 of epic #72 continues in parallel worktrees:

- **#76** — E0.4: Migration runner and initial schema (branch `feat/e04-migration-runner`, active worktree).
- **#78** — E0.6: Health endpoint + structured logging (branch `feat/e06-health-logging`, active worktree).

Once the migration runner lands, the integration job will stop being a no-op and start exercising real Postgres via testcontainers — at which point the CI work from this PR actually starts earning its keep.
