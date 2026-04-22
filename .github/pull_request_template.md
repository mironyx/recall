<!--
Fill in each section below. Delete any that genuinely do not apply and say why.
See docs/process/engineering-process.md for the full pipeline.
-->

## Summary

<!-- 1–3 bullet points describing what changed and why. -->

## Issue

<!-- Link the tracking ticket. e.g. Closes #123 (GitHub), PROJ-456 (Jira), LIN-789 (Linear). -->

## Design reference

<!--
Link the section of the plan, HLD, or LLD this PR implements.
If an LLD exists, link it: docs/design/lld-<epic>-<task>.md
-->

## ADRs

<!--
List ADRs that inform or are affected by this change. Link each.
If none apply, write "None".
-->

## Design deviations

<!--
Anything implemented differently from the LLD or plan.
Format: "LLD said X; this PR does Y because Z."
If none, write "None".
-->

## Test plan

- [ ] `uv run pytest` — all tests pass (unit + integration)
- [ ] `uv run mypy` — clean
- [ ] `uv run ruff check .` — clean
- [ ] `uv run ruff format --check .` — clean
- [ ] Design contracts verified (field names, types, schemas match)

## Verification

<!--
- **Tests added:** <N> (brief: unit / integration / evaluation / BDD breakdown)
- **Total tests:** <N> (<M> test files)
- Notes on manual verification, fixtures used, edge cases exercised.
-->

## Process notes

<!--
Anything about how the work was done that reviewers should know:
evaluator adversarial test count, PR size warnings, dropped scope, follow-up tickets.
If none, write "None".
-->

## Usage

<!--
Cost and resource usage for this PR, captured from OpenTelemetry.
Example:
- **LLM tokens:** <input> in / <output> out
- **Cost:** $<amount>
- **Wall time:** <duration>
- **Trace:** <link to OTel trace / dashboard>
If not captured, write "Not captured" and say why.
-->
