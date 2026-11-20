# Session log — REC-5

## Approach rationale
- **Issue:** REC-5
- **Approach chosen:** `scope` optional; when None, `asyncio.gather` project + global queries at exactly `limit`, `_merge` boosts project scores, concatenates project-first, stable-sorts descending, truncates.
- **LLD deviations:** none
- **Pressure:** light — ~20 src lines, 1 source file (plus conftest fixture, ADR edit, tests)

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-20T09:56:58Z | $0.29 | 2,046 in / 1,761 out | pressure: light — ~20 src lines, 1 src file [models: claude-sonnet-5-5 $0.29, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-20T09:59:09Z | $0.55 | 2,076 in / 8,978 out | green: 287 tests, ruff, format, mypy, mdlint; e2e/audit n/a [models: claude-sonnet-5-5 $0.55, claude-haiku-5-5 $0.00] |
| 6 | 2026-11-20T09:59:10Z | $0.55 | 2,076 in / 8,978 out | diag: CodeScene 9.68/10/9.68, pre-existing arg-count smell [models: claude-sonnet-5-5 $0.55, claude-haiku-5-5 $0.00] |
| 8 | 2026-11-20T10:01:27Z | $0.85 | 2,097 in / 12,763 out | [PR #126](https://github.com/mironyx/recall/pull/126) [models: claude-sonnet-5-5 $0.85, claude-haiku-5-5 $0.00] |
| 9 | 2026-11-20T10:01:27Z | $0.85 | 2,097 in / 12,763 out | review clean [models: claude-sonnet-5-5 $0.85, claude-haiku-5-5 $0.00] |
| 10 | 2026-11-20T10:01:27Z | $0.85 | 2,097 in / 12,763 out | report done; CI pass [models: claude-sonnet-5-5 $0.85, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- Project has no `scripts/run-*.sh`; used plugin starters (`p`). Typecheck starter spawns pyright (absent) — ran `uv run mypy --strict src` instead.
- REC-4 test `test_search_signature_has_no_tags_or_project_ids` asserted `scope` required; updated to optional (intended REC-5 contract change).
- CodeScene: memory_service.py 9.68 — only smell is arg count of `search`/`save` (public contract, pre-existing); left. SonarQube step not run (no analysis tool verified).
