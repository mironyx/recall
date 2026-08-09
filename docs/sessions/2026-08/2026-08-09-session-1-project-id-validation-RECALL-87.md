# Session log — RECALL-87

## Approach rationale
- **Issue:** #87
- **Approach chosen:** Follow the LLD §E1.2 verbatim — module-level `PROJECT_ID_PATTERN` (`^[a-zA-Z0-9_-]{1,128}$`), `RESERVED_PROJECT_IDS` frozenset (`{"global", "_"}`), and a pure `validate_project_id_format()` raising `ValidationError` from the shared `errors.py` module. The LLD is already the ADR-0014-reconciled replacement for the dropped `ProjectRegistry`; any deviation would add complexity, not remove it.
- **LLD deviations:**
  1. `.fullmatch()` instead of the LLD's `.match()` — Python's `$` anchor matches just before a trailing `\n`, so `.match()` silently accepts `'global\n'` and a 129-char ID ending in newline, bypassing the reserved-name guard and the `{1,128}` bound. `.fullmatch()` rejects both (PR #111 review finding; regression test added).
  2. `ValidationError` is a bare `Exception` subclass for now, not `ValidationError(RecallError)` with `error`/`hint` attributes per LLD §E1.1. Deferred to #91 — E1.1 (#86) lands `RecallError` in this module in parallel, and the E1.6 error formatter (#91) is the consumer of the structured shape. Marked with `TODO(#91)` in `errors.py`.
  (Issue body names the function `validate_project_id()`; LLD and E1.6 router call `validate_project_id_format()` — implemented per LLD.)
- **Pressure:** standard — ~50 src lines across 2 source files (`validation.py`, `errors.py`), 1 test file.

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T13:05:00Z | $0.0000 | 0 | pressure: standard |
| 4bF  | 2026-08-09T13:10:00Z | $0.0000 | 0 | test-author complete (11 tests) |
| 4dF  | 2026-08-09T13:15:00Z | $0.0000 | 0 | implementation complete — 11/11 pass |
| 5    | 2026-08-09T13:30:00Z | $0.0000 | 0 | green on attempt 4 (mypy/ruff/format/11 tests). Full suite: 80/81 — pre-existing smoke-test fixture failure also fails on clean main (order-dependent: pg_conn teardown drops tables before test_container_boots runs; unrelated to #87) |
| 6    | 2026-08-09T13:35:00Z | $0.0000 | 0 | diag pass — exporter N/A (no .diagnostics in worktree); CodeScene 10.0/10.0; SonarQube N/A (repo not analyzed) |
| 6b   | 2026-08-09T13:40:00Z | $0.0000 | 0 | evaluator: PASS (0 adversarial; smoke failure independently confirmed pre-existing; stale docstring fixed) |
| 8    | 2026-08-09T13:45:00Z | $0.0000 | 0 | [PR #111](https://github.com/mironyx/recall/pull/111) |
| 9    | 2026-08-09T14:05:00Z | $0.0000 | 0 | pr-review blocker: `.match()` accepts trailing newline → fixed to `.fullmatch()`; regression tests added; ValidationError shape deferred to #91 (TODO marker) |
| 9b   | 2026-08-09T14:20:00Z | $0.0000 | 0 | re-review after fix: conformance clean; quality — Co-Authored-By "block" adjudicated false positive (no such rule in project CLAUDE.md/kb; harness mandates the trailer; history not rewritten), warn: LLD wave table wrongly claims E1.1/E1.2 share no files (both write errors.py) — flagged for lead + lld-sync |

## Work completed

Implemented E1.2 (issue #87): `validate_project_id_format()` in `src/recall/validation.py` — pure function, no I/O/DB/cache. Rejects reserved names `global`/`_` case-insensitively and enforces `^[a-zA-Z0-9_-]{1,128}$` via `PROJECT_ID_PATTERN`. `ValidationError` added to shared `src/recall/errors.py` (bare `Exception` subclass, see Decisions). 12 unit tests in `tests/test_validation.py`, all green.

PR: https://github.com/mironyx/recall/pull/111 — 5 commits (feat + MD058 doc fix + trailing-newline fix + review-outcome doc + lld-sync/session-log finalisation).

## Decisions made

1. **`.fullmatch()` over the LLD's `.match()`.** Python's `$` matches just before a final `\n`, so `.match()` accepted `'global\n'` and 129-char+\n — bypassing the reserved-name guard and the `{1,128}` bound. Caught by pr-review; fixed in 6127af4 with regression test `test_trailing_newline_rejected`. LLD corrected in-place by lld-sync.
2. **`ValidationError` stays a bare `Exception` subclass.** LLD §E1.1 designs `ValidationError(RecallError)` with `error`/`hint`. The E1.6 error formatter (issue #91, REQ-story-43) is the consumer of the structured shape; a bare message is sufficient until then. Marked `TODO(#91)` in `errors.py`; the LLD marks it `_(deferred → issue #91)_`. After rebasing onto #86 (which landed `RecallError`/`UnauthenticatedError`), the promotion is trivial for #91 to complete.
3. **Rebase conflict resolution (errors.py).** #86 and #87 both write `errors.py` (the LLD wave table's "no shared files" claim was wrong). Kept both sides: `RecallError`/`UnauthenticatedError` from #86, `ValidationError` from #87. TODO text updated since its precondition (RecallError landing) is now met.
4. **Co-Authored-By trailers kept.** pr-review's block on the trailer is a template check; recall's CLAUDE.md/kb contain no such rule (grep-verified), and the harness mandates the trailer. History not rewritten.
5. **Function name:** issue body said `validate_project_id()`; LLD and E1.6 router call `validate_project_id_format()` — implemented per LLD.

## Review feedback addressed

- **pr-review #1 (blocker):** `PROJECT_ID_PATTERN.match()` accepts trailing newline → fixed to `.fullmatch()` (6127af4), regression test added, PR body documents the deviation.
- **pr-review #1 (warn):** ValidationError should be `ValidationError(RecallError)` per LLD §E1.1 → deferred to #91 with `TODO(#91)` marker and LLD deferral note; documented in PR body.
- **pr-review #2 (after fix):** Conformance agent clean. Quality agent: Co-Authored-By block adjudicated false positive (see Decisions #4); LLD wave-table "no shared files" warn accepted and corrected by lld-sync.
- **CI:** Lint job red on pre-existing markdownlint errors only (MD033/MD028 in main's design docs — untouched by this PR); all other jobs pass or skip.

## LLD Sync report

## LLD Sync — Issue #87: E1.2: Project ID validation — format check, reserved-name guard

### Corrections (spec was wrong)
- §E1.2 regex check: `.match()` → `.fullmatch()` — Python's `$` matches just before a trailing `\n`, so the spec'd `.match()` silently accepted `'global\n'` and a 129-char ID ending in newline, bypassing the reserved-name guard and the `{1,128}` bound. Implementation note added.
- Execution Waves table: "Parallelisable — no shared files" was wrong for E1.1/E1.2 — both write `src/recall/errors.py`. Note added; the second landing PR (this one) rebased and merged both error classes.

### Additions (not in spec)
- kb/architecture.md: `validation.py` catalogued as a reusable helper in the API composition section (future LLDs must reuse `validate_project_id_format()`, not inline the regex).

### Omissions (in spec but not built)
- §E1.1 `ValidationError(RecallError)` with error/hint shape: deferred → issue #91 (E1.6 error formatter, REQ-story-43 is the consumer). Implementation has a bare `ValidationError(Exception)` subclass; marked `_(deferred → issue #91)_` in the LLD and `TODO(#91)` in `errors.py`.

### Confirmations (notable)
- `PROJECT_ID_PATTERN`, `RESERVED_PROJECT_IDS`, `validate_project_id_format()` built exactly as specified (§E1.2). Issue body named the function `validate_project_id()`; LLD's `validate_project_id_format()` was followed (E1.6 router calls it).

### LLD updated
File: docs/design/v2/lld-e1-one-memory-e2e.md §E1.2, §E1.1, Execution Waves, Document Control
Version: Document Control Revised row added for issue #87 (2026-08-09)

## Cost retrospective

Cost tracking unavailable — no Prometheus session data for RECALL-87 (tagging never populated; all checkpoint rows show unavailable). Token/cost retrospective is therefore qualitative:

- **Step 4cF→5:** 4 verification attempts before first green — mostly environmental, not code: sub-agent cwd mismatch (agent spawned from main repo, `uv run pytest <abs path>` resolved the wrong project → empty collection) and EDF starter scripts invoking `pyright` (not installed for this project; CLAUDE.md contract is `uv run mypy --strict`). Fix for next time: prefix every verification command with `cd <worktree>`, and pass the project's own `./scripts/run-*.sh` (which honour the contract) instead of EDF starters where they diverge.
- **Step 8→9:** one blocker (trailing-newline regex gap) — a genuine design defect caught only by review. The `$`-before-`\n` Python gotcha is now in the LLD as an implementation note; future regex-spec work should prefer `fullmatch` by default.
- **Post-PR:** rebase onto #86's `errors.py` was mechanical (anticipated by the `TODO(#91)`); cost of parallel shared-file work was one conflict resolution.

## Next steps

- E1.6 (issue #91): promote `ValidationError` to `ValidationError(RecallError)` when the structured error formatter lands (REQ-story-43).
- Reconcile main's pre-existing markdownlint failures (MD033/MD028 in `lld-e1-one-memory-e2e.md`, `lld-e06-health-logging.md`) — CI is red on main; consider a docs-only fix PR.
- Pre-existing smoke-test fixture failure (pg_conn teardown ordering): fix `pg_conn_string` dependency on `_migrated_db_sess` in `tests/conftest.py`.
