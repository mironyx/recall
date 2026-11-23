# Team session — Epic REC-8 (E3: update, delete, full surface)

Lead session `a75f3a1e`. Waves 2–4 of REC-8; REC-9 (wave 1) shipped in an earlier session.

## Issues shipped

| Issue | Story | PR | Branch | Merged at |
| --- | --- | --- | --- | --- |
| REC-10 | 1.4, 4.2 — `memory_update` tool | [#132](https://github.com/mironyx/recall/pull/132) | `feat/memory-update-tool` | 2026-11-23T20:03Z |
| REC-11 | 1.5, 4.2 — `memory_delete` | [#133](https://github.com/mironyx/recall/pull/133) | `feat/memory-delete-tool` | 2026-11-23T20:31Z |
| REC-13 | 4.3, 4.4 — tool-surface coverage | [#134](https://github.com/mironyx/recall/pull/134) | `feat/tool-surface-coverage` | 2026-11-23T21:37Z |
| REC-12 | 4.3 — `ErrorCode` registry, `embedding_failed` | [#135](https://github.com/mironyx/recall/pull/135) | `feat/error-vocabulary` | 2026-11-23T21:40Z |

Epic REC-8 closed. All five MCP tools are live; the Phase 3 exit test (`test_every_listed_tool_has_both_cases`) is on main.

## Cross-cutting decisions

- Teammate prompts carried lessons forward between waves: REC-10's review finding (non-string locators surfaced as `internal_error`) became the instruction to reuse `_check_text` in REC-11.
- After REC-11's CI failure, the wave 4 prompts said to run bare `uv run mypy`, which also checks `tests/`. Neither wave 4 PR failed CI on types.
- Wave 4 merge order: REC-13 first, then REC-12 rebased onto it and re-ran CI before merging, so the combined code was verified rather than each PR alone.
- `memory_search` provider failures now return `embedding_failed` instead of `internal_error`. This behaviour change was planned in the LLD (§3.4).

## Coordination events

- **REC-10 crash recovery:** the original teammate session was gone and its worktree orphaned. The lead ran `feature-end` itself in recovery mode, with the user's message as approval ("/feature-end to the current task").
- **Spawns:** REC-11 alone (wave 3), then REC-12 and REC-13 in parallel (wave 4). There were no blockers and no stuck teammates.
- **CI:** REC-11 failed once on mypy over `tests/`; the teammate fixed it. REC-10's rebase push briefly showed "no workflow runs" before CI registered.
- **Docs conflicts:** the REC-12 and REC-13 LLD syncs both edited the Document Control `Revised` row. REC-12 merged them when landing. REC-11's `park-docs.sh land` also conflicted, because the session log had been edited before landing.
- **Session-title cross-write:** REC-13's `tag-session.py` wrote `customTitle: "REC-13"` into REC-12's transcript, so both tmux panes showed REC-13. Prometheus tags were correct.

## What worked / what didn't

- Worked: wave gating from the epic's dependency table; per-PR human gate with verbatim relay; carrying lessons into prompts; serialising the second rebase after the first merge.
- Didn't: teammates sent duplicate reports (one as a message, one as the idle summary); EDF tooling gaps listed below cost a manual workaround in every task.
- REC-10 final cost ($0.97) was lower than its own checkpoint table ($1.44); the crashed session's tail was missing from the query.

## Process notes for `edf:retro`

- `tag-session.py`: when `CLAUDE_CODE_SESSION_ID` is set, write the title to `<claude_dir>/<env id>.jsonl`. Today the script uses the file-lookup result even when it disagrees with the env ID, so parallel teammates started in the same folder overwrite each other's titles.
- `update-coverage-manifest.py --verify-anchors` reports every valid anchor as "file not found" (path resolution).
- The EDF typecheck wrapper calls `pyright`, which isn't installed here; CLAUDE.md's `mypy --strict src` should become `uv run mypy` to match CI.
- The checkpoint script drops the blank line before the session-log table (MD058). Every task fixed it by hand.
- 84 Dependabot alerts on main; about a dozen dependency PRs (#94–#110) are still open.
