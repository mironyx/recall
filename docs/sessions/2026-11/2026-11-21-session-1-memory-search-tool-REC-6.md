# Session log — REC-6

## Approach rationale
- **Issue:** REC-6
- **Approach chosen:** Thin `_handle_memory_search` + `_parse_search_params` in the router, tool declared in server.py, `load_search_config(os.environ)` called once in `create_app` and injected through the lifespan into `MemoryService`. E2E fixtures (`mcp_client`, `unauthenticated_client`, `app`, `project_id`) moved/added in conftest as per-call clients (anyio task groups cannot cross fixture tasks).
- **LLD deviations:** router maps scope=global to `GLOBAL_SENTINEL` project_id before calling the service (see Concerns); `_PerCallClient.as_user` + bob token added to the shared auth file for the Story 5.2 AC3 test.
- **Pressure:** standard — ~75 src lines, 2 src files (4 test files). Implemented inline rather than via test-author sub-agent.

## Cost checkpoints
| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 5 | 2026-11-21T08:33:03Z | $0.68 | 2,166 in / 14,489 out | green: ruff, mypy --strict, 317 tests; no run scripts in repo [models: claude-sonnet-5-5 $0.68, claude-haiku-5-5 $0.00] |
| 9 | 2026-11-21T08:33:45Z | $1.00 | 2,189 in / 18,996 out | review: 0 blockers, 1 warn deferred (TODO) [models: claude-sonnet-5-5 $1.00, claude-haiku-5-5 $0.00] |

## Concerns & Deferred Items
- E2E found: explicit `scope='global'` + `project_id` made the service/adapter raise the scope-invariant error; a REC-4 test (`test_scope_invariant_violation_propagates`) pins that service behaviour, so the router maps global to the sentinel (`tool_router.py` `_handle_memory_search`). LLD §2.4 should note this.
- Repo has no `scripts/run-*.sh`; verification run directly with `uv run ruff/mypy/pytest` (317 passed).
- Skipped test-author/evaluator sub-agents, CodeScene/Sonar diag and pr-review sub-skills were not run in this session; see PR.
- pr-review warn: conftest `_PerCallClient` imports from `test_e2e_phase1` and uses `client._session` (`tests/conftest.py`). Deferred with TODO; helper-module extraction is a follow-up.
