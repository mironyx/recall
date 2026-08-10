# Session log — RECALL-91

## Approach rationale
- **Issue:** #91
- **Approach chosen:** Thin `ToolRouter` per LLD §E1.1 code block (validate → dispatch → catch RecallError → one `mcp_call` event) wired at the composition root: lowlevel MCP `Server` + `StreamableHTTPSessionManager` mounted at `/mcp` on the existing Starlette app. Auth header captured at the ASGI boundary into a plain contextvar (never structlog contextvars — bearer token is a credential, ADR-0007); the MCP tool callback resolves `user_id` via `authenticate()` and formats `UnauthenticatedError` as `{error, hint}`. E2E tests drive the real MCP protocol (`streamable_http_client` + `ClientSession`) over `httpx.ASGITransport` with manually-entered lifespan, against real Postgres (testcontainers).
- **LLD deviations:** (1) auth header captured via ASGI middleware contextvar — SDK tool handlers cannot see HTTP headers, so "Transport→Auth" is realized at the middleware boundary; (2) `validate_input=False` on the SDK `call_tool` registration — SDK jsonschema pre-validation would short-circuit missing-required-field calls before the router, breaking AC1 (router validates) and AC3 (exactly one `mcp_call` event per call); (3) `ValidationError` promoted to `RecallError` subclass (LLD §E1.1 shape) — resolves the deferred `TODO(#91)` in errors.py, required for AC4 formatting.
- **Pressure:** heavy — ~310 src lines across 3 source files (`tool_router.py` new, `server.py`, `errors.py`); 2 new test files.


## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-10T09:40:00Z | $3.79 | 161,684 in / 24,730 out | pressure: heavy |
| 4bF  | 2026-08-10T10:05:00Z | $7.50 | ~280k in / ~45k out | test-author complete — 13 properties, 34 tests |
| 4dF  | 2026-08-10T10:18:00Z | $23.64 | 479,825 in / 311,105 out | implementation complete — e2e green (8/8); see 4cF debugging note below |
| 5    | 2026-08-10T10:41:00Z | $26.53 | 517,243 in / 338,836 out | green on attempt 2 — tests 206/206, mypy --strict, ruff check, ruff format --check; attempt 1 failed on 2 mypy errors (test doubles typed) + 1 unformatted file |
| 6    | 2026-08-10T11:05:00Z | $28.76 | 533,522 in / 364,522 out | diag pass — CodeScene: 6/7 files 10.0, tool_router.py 9.68 (_log_call 5 args, justified in code); test_tool_router.py 9.38->10.0 (validator extraction, logging-test dedup); e2e file 10.0; SonarQube N/A (no project analysis); full suite re-run 206/206 |
| 6b   | 2026-08-10T11:30:00Z | $31.18 | 599,604 in / 395,550 out | evaluator: PASS WITH WARNINGS — 6 adversarial tests (tests/evaluation/test_e16_tool_router_eval.py), 6/6 pass; all 7 ACs covered; warnings noted in PR body; TODO(#91) added for vacuous validate_dim; full suite 212/212 |
| 9    | 2026-08-10T11:55:00Z | Cost: unavailable | Tokens: unavailable | pr-review fixes: SSE 409 regression test (root cause: SSE-stream race with the MCP client — one stream per session), route methods fix, triage comment on PR #117 |
| 9b   | 2026-08-10T12:20:00Z | $45.52 | 869,456 in / 564,009 out | design decision (user): **stateless mode** — StreamableHTTPSessionManager(stateless=True, json_response=True); /mcp POST-only; stateful SSE/409 test removed (e2e 213→212); 2026-07-28 spec changelog reviewed (sessions removed, SEP-2567; SDK 1.27.0 = 2025-11-25, follow-up tracked); PR body + addendum comment updated |
| 9c   | 2026-08-10T13:10:00Z | $54.51 | 969,579 in / 653,009 out | **mcp 2.0.0 rewrite** (user directive: use latest) — pyproject `mcp>=2.0.0`, re-lock; server.py rebuilt on v2 lowlevel Server (on_list_tools/on_call_tool) + streamable_http_app(json_response, stateless_http, host=0.0.0.0) mounted at /; dispatcher runs in lifespan; no initialize; wire models snake_case; e2e client on httpx2; full gate 212/212, mypy --strict clean, ruff clean; ADR-0006 amendment; PR body deviation #8 rewritten |
