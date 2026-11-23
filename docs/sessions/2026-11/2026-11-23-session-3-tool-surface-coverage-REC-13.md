# Session log — REC-13

## Approach rationale

- **Issue:** REC-13
- **Approach chosen:** One table-driven test file, `TOOL_CASES` keyed by tool name, each row
  a happy coroutine (seeds data, asserts success shape) plus an error `(params, code)` pair
  asserted as a string literal; a guard compares `list_tools()` names to the table keys.
- **LLD deviations:** `_save` is defined locally instead of imported from
  `tests/test_e2e_search.py` — importing a test module's private helper couples two test
  files; both sibling e2e files already define their own `_save`.
- **Pressure:** light — 0 src lines, 0 src files, 1 test file (tests-only task).

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-23T20:33:26Z | $0.60 | 2,624 in / 2,133 out | pressure: light — tests only, 0 src lines [models: claude-opus-5-5 $0.60, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-23T20:34:50Z | $1.06 | 3,363 in / 8,531 out | green on attempt 1 — 440/440, mypy strict + ruff clean; e2e skip (no e2e-dir); audit PRE-EXISTING [models: claude-opus-5-5 $1.05, claude-haiku-5-5 $0.00] |
| 6 | 2026-11-23T20:34:50Z | $1.06 | 3,363 in / 8,531 out | diag pass — light track, no src files changed; justification ok; mock grep clean [models: claude-opus-5-5 $1.05, claude-haiku-5-5 $0.00] |
| 8 | 2026-11-23T20:35:19Z | $1.16 | 3,371 in / 9,985 out | [PR #134](https://github.com/mironyx/recall/pull/134) [models: claude-opus-5-5 $1.16, claude-haiku-5-5 $0.00] |
| 9 | 2026-11-23T20:35:52Z | $1.69 | 3,391 in / 13,949 out | review clean — 0 findings (Agent Q, test-only diff) [models: claude-opus-5-5 $1.69, claude-haiku-5-5 $0.00] |
| 10 | 2026-11-23T20:37:00Z | $1.73 | 4,098 in / 14,618 out | report done — CI pass, review clean, PR ready [models: claude-opus-5-5 $1.73, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items

- `tag-session.py` resolved the session via its file-lookup path, not `CLAUDE_CODE_SESSION_ID`, so
  it wrote the "REC-13" custom title into REC-12's transcript (wrong pane titles). The Prometheus
  tag (`b7581497`) is correct. EDF plugin issue, reported by the lead; not fixed here.

## Work completed

- [PR #134](https://github.com/mironyx/recall/pull/134) — `tests/test_e2e_tool_surface.py` (new).
- `TOOL_CASES` table: happy + error row for each of the five tools; guard compares
  `list_tools()` names to the table keys. 11 tests; suite 440/440.

## Decisions made

- Error cases chosen per tool: missing required field → `validation_error` for save, search and
  delete (delete is idempotent, so unknown id is not an error); unknown id → `not_found` for get
  and update.
- `test_error_path` also asserts a non-empty `hint`, pinning the `{error, hint}` wire shape (D5).

## Review feedback addressed

- None — [review](https://github.com/mironyx/recall/pull/134#issuecomment-7113288436) returned 0 findings.

## LLD Sync report

## LLD Sync — Issue REC-13: E3.3b: Tool-surface happy/error coverage (Phase 3 exit)

### Corrections (spec was wrong)

- `_save` source: spec said import from `tests/test_e2e_search.py` → defined locally — sibling
  e2e files each keep their own; importing another test module's private helper couples them.

### Additions (not in spec)

- `test_error_path` asserts a non-empty `hint` alongside the code literal (§3.5 note).

### Omissions (in spec but not built)

- None.

### Confirmations (notable)

- `ToolCases(happy, error)` NamedTuple and `TOOL_CASES` keyed by tool name, built as specified.

### LLD updated

File: docs/design/v2/lld-e3-update-delete-errors.md §3.5 (no Version row; Revised row extended)

## Cost retrospective

| Bucket | Cost |
|--------|------|
| PR creation (step 8) | $1.16 |
| Review + CI + report (8 → 10) | $0.57 |
| Final total | $2.09 |

- Light track, green on attempt 1 — no fix cycles. The largest post-PR item was the review
  agent re-reading CLAUDE.md and kb for a 134-line test-only diff (~$0.5); acceptable.
- The checkpoint script dropped the blank line before the table (MD058) — fixed by hand before commit.

## Next steps

- REC-12 (error vocabulary, PR #135) merges next; this file asserts literals, so needs no change.
- Phase 3 exit: once REC-12 lands, epic REC-8 can be closed.
