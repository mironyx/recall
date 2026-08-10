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
| 9d   | 2026-08-10T14:05:00Z | — | — | design note: user questioned `_resolve_save_namespace` living on ToolRouter (possible overlap with StorageAdapter._build_namespace); answered (param-validation vs key-construction + defence-in-depth, deviation #4); user: "not sure I fully agree but leave it for now" — revisit at lld-sync/feature-end |

## Work completed

- **PR #117** — E1.6 Tool Router + MCP wiring: memory_save + memory_get over real MCP transport. Merged via squash.
- `src/recall/tool_router.py` — ToolRouter: dispatch, per-field validation (required fields, scope enum, scope invariant, project_id format), structured {error, hint} formatting, one mcp_call event per call (ADR-0011).
- `src/recall/server.py` — composition root rebuilt on the **2026-07-28 MCP protocol revision / mcp SDK 2.0.0**: lowlevel `Server(on_list_tools, on_call_tool)`, `streamable_http_app(json_response=True, stateless_http=True, host="0.0.0.0")` mounted at `/` via `Mount`, dispatcher task group in the app lifespan, auth gate reading `ServerRequestContext.request.headers`.
- `tests/test_tool_router.py`, `tests/test_e2e_phase1.py` (8 e2e BDD tests over real MCP transport against real Postgres), `tests/evaluation/test_e16_tool_router_eval.py` (6 adversarial tests). Total suite: 212 tests, all green; mypy --strict, ruff lint + format clean.
- ADR-0006 amendment 1 (2026-07-28 protocol revision); coverage manifest `REQ-story-41` → Revised; LLD synced (see LLD Sync report).
- Commit: 2490867 (single-squash PR commit on feat/tool-router-mcp).

## Decisions made

- **Stateless server** (user decision, post-review): every tool call is one self-contained POST, inline JSON, no MCP-Session-Id, no SSE, no DELETE termination.
- **Latest protocol revision** (user directive: "in our doc we says that we should use latest"): the deliverable was rewritten onto the 2026-07-28 spec / mcp 2.0.0 inside PR #117 rather than landing the v1 (2025-11-25) implementation first. v1.x SDK is in maintenance mode.
- **Auth at the transport, resolved from the request** — v2 `ServerRequestContext.request.headers`; ToolRouter takes only the service (LLD deviation, now synced).
- **Router is the single validator** — the v2 dispatcher does no input pre-validation, so SDK jsonschema pre-validation never short-circuits the router (AC1/AC3 preserved).
- **`host="0.0.0.0"`** on `streamable_http_app` mirrors `cli.DEFAULT_HOST`; keeps the SDK's DNS-rebinding auto-protection off — serve epic must pass the configured public hostname.
- **User-deferred design question:** namespace resolution placement (`_resolve_save_namespace` on ToolRouter vs StorageAdapter._build_namespace) — "not sure I fully agree but leave it for now" (row 9d); revisit at next feature.

## Review feedback addressed

- **PR review triage** (see PR comment): trailer false-positive dismissed; GET/DELETE routes + SSE 409 regression test (later **superseded** by the stateless decision — transport test removed, 213 → 212); vacuous `validate_dim` documented as `TODO(#91)` (Story 6.4); `_missing_fields` Justification comment added; server.py composition layer deferred to lld-sync — **now synced** (new LLD-e1-mcp-wiring section).
- **Evaluator (Step 6b): PASS WITH WARNINGS** — 6 adversarial tests added (TestStoreWiring, dim-mismatch, ADR-0015 isolation); all pass.

## LLD Sync report

## LLD Sync — Issue #91: E1.6 Tool Router + MCP wiring for memory_save + memory_get

### Corrections (spec was wrong)
- **ToolRouter constructor** — spec showed `__init__(memory_service, auth_config)`; shipped takes only `memory_service`. Auth is resolved at the transport boundary: the call-tool handler reads the Authorization header from `ServerRequestContext.request.headers` (the v2 SDK attaches the Starlette Request to message metadata — the LLD's "Transport→Auth" arrow is now satisfied by the SDK itself, no middleware contextvar).
- **Scope resolution in `_handle_memory_save`** — spec's inline `project_id = params.get("project_id", "_" if scope == "global" else "")` silently dropped a project_id on global calls; shipped `_resolve_save_namespace` rejects `scope=global` with a project_id (Story 1.2 AC4), validates the enum (AC5), and fills the `GLOBAL_SENTINEL`.
- **`mcp_call` event emission** — spec duplicated the log inline per outcome; shipped extracts a single `_log_call` helper (ADR-0011 one-event invariant), `latency_ms` rounded to 2 decimals.
- **Tool declarations shape** — spec showed one dict per tool carrying `name`+`description` with JSON Schema omitted; shipped separates DESCRIPTION/SCHEMA constants (name is a `Tool` field, not part of the schema) with full JSON Schema per the requirements tool table.
- **Transport wiring (major)** — the LLD assumed the v1 SDK (decorator-based `@mcp_server.list_tools()`/`@call_tool(validate_input=False)`, session-manager modes). User-directed rewrite onto the 2026-07-28 protocol revision / mcp SDK 2.0.0: dispatcher `Server("recall", on_list_tools=..., on_call_tool=...)`, `streamable_http_app(json_response=True, stateless_http=True, host="0.0.0.0")` mounted at `/`, no initialize handshake, stateless is protocol-native (SEP-2567/2575). The dispatcher does no input pre-validation — router stays the single validator (AC1/AC3).

### Additions (not in spec)
- `_missing_fields` and `_resolve_save_namespace` static helpers on ToolRouter (extracted per CodeScene findings + issue ACs).
- `_McpRuntime` holder + lifespan composition (`_build_lifespan`): store pool → router wiring → `mcp_server.session_manager.run()`; documented as new `LLD-e1-mcp-wiring` section.
- `server.py` composition layer (build functions, auth gate, mount) — previously absent from the LLD's internal decomposition (review finding 5, deferred to lld-sync); decomposition table now includes a `server.py` row.

### Omissions (in spec but not built)
- Real fail-fast `validate_dim` against the existing `vector(N)` column — built, but vacuous (stub dim comes from the same env var); deferred → Story 6.4 (schema introspection), `TODO(#91)` in server.py.

### Confirmations (notable)
- `_handle_memory_get` (scope-explicit, ADR-0015) shipped as specified.
- BDD specs from the issue (8 e2e tests) match the shipped test suite 1:1.

### LLD updated
File: docs/design/v2/lld-e1-one-memory-e2e.md — `LLD-e1-tool-router` (code block synced to shipped), `LLD-e1-mcp-tool-declarations` (shipped shape + registration), new `LLD-e1-mcp-wiring` (composition), Internal Decomposition table (`server.py` row, tool_router dependency), Document Control row. Coverage manifest: `REQ-story-41` → `Revised` (anchors verified OK).

## Cost retrospective

- **PR-creation cost:** $31.77 (PR body) → **final total:** $57.63 (ai-cost-final labels). Post-PR rework ≈ **$25.9** — dominated by two user-directed design events, not review churn.
- **Drivers:**
  - Row 9b ($45.52, +$13.7): stateless design decision — reviewing the 2026-07-28 spec changelog mid-PR triggered a transport rework (SSE/409 test removed, stateless wiring) *and* surfaced that the SDK pinned was one spec revision behind.
  - Row 9c ($54.51, +$9.0): the 2.0.0 rewrite itself — pyproject bump, transport + client-layer rewrite, re-verification. This is the direct cost of "use latest" landing after implementation had started.
  - Row 9 ($31.18 → $45.52): review fix cycles (SSE 409 regression test, route methods) — later **superseded** by the stateless decision (sunk cost: ~$1-2k of the rework was written then removed).
- **Improvement actions:**
  1. **Check the SDK/protocol revision at kickoff, not mid-PR** — the docs' "current MCP standard"/"official SDK" language was only interpreted after implementation. Add a requirements-review check: "pin the latest published MCP spec revision and SDK major in the issue".
  2. **When a mid-PR design decision triggers a rewrite, estimate it before committing** — the stateless decision cascaded into the 2.0.0 rewrite; an explicit cost/scope call at 9b would have merged #117 on 1.27 stateless and queued the rewrite as its own issue (the alternative the user declined).
  3. **The PR body Design-deviations section paid off** — review findings 4/5 flowed through it into lld-sync; keep the discipline.

## Next steps

- **E2 (Search) epic** — `memory_search` is unblocked: store now constructed with a working embed at the composition root; E2.3 extends `tool_router.py`. Suggested next board item.
- **Markdownlint cleanup PR** — 23 pre-existing errors in 4 docs files (lld-e06-health-logging, lld-e1-one-memory-e2e, 2 session logs) red on CI; not part of any feature PR.
- **Serve epic** — pass the configured public hostname to `streamable_http_app` (DNS-rebinding); real embedding provider (E4.1); update/delete (E3.1/E3.2); real `validate_dim` via schema introspection (Story 6.4); SDK `tasks` extension + DPoP when upstream lands (ADR-0006 amendment 1).
