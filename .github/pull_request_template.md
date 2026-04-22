<!--
Fill in each section below. Delete any that genuinely do not apply and say why.
See docs/process/engineering-process.md for the full pipeline.
-->

## Summary

<!-- 1–3 bullet points describing what changed and why. -->

## Issue

<!-- e.g. Closes #123 -->

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
