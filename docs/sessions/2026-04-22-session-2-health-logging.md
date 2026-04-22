# Session 2 — E0.6: Health endpoints and structured logging skeleton

**Date:** 2026-04-22
**Issue:** [#78](https://github.com/mironyx/recall/issues/78) — E0.6: Health endpoints and structured logging skeleton (part of Epic #72)
**PR:** [#81](https://github.com/mironyx/recall/pull/81) (merged)
**Branch:** `feat/e06-health-logging`
**Driver:** teammate-78 (feature-team lane for #78)

## Summary

Second Phase 0 feature after #73/#79 (repo scaffolding and CLI stubs). Shipped the
observability skeleton every later phase builds on: Starlette ASGI app with
`/healthz` + `/readyz`, structlog JSON-on-stdout with contextvar request-scoped
fields and a stdlib bridge, OTEL initialised in no-op mode, and `recall serve`
wired end-to-end (logging → telemetry → app → uvicorn).

## Work completed

- **New modules** under `src/recall/`:
  - `server.py` — `create_app(conn_string)` builds a Starlette app with
    `/healthz` and `/readyz`, installs `RequestContextMiddleware` that binds
    `request_id` + OTEL `trace_id`/`span_id` into the structlog contextvar on
    every HTTP request and emits one `http_request` JSON event per call.
  - `health.py` — `healthz()` is always 200; `readyz()` opens a short-lived
    asyncpg connection (0.5 s connect + 0.3 s query timeouts) and returns
    503 with a `reason` field on failure.
  - `logging.py` — `configure_logging()` installs the processor chain
    (`merge_contextvars → add_log_level → TimeStamper → wrap_for_formatter`)
    plus a single stdlib `ProcessorFormatter` handler; `bind_request_context`
    / `unbind_request_context` manage the three request-scoped keys.
  - `telemetry.py` — `configure_telemetry()` is a no-op with a warn-and-
    continue branch when `OTEL_EXPORTER_OTLP_ENDPOINT` is set but export
    wiring is still Phase-4 work; `get_trace_context()` extracts hex IDs from
    the default OTEL tracer and returns `("", "")` for the invalid span.
- **CLI change** in `src/recall/cli.py` — `serve` subcommand now wires
  everything up and runs uvicorn (with `log_config=None` so uvicorn's default
  handlers do not override the structlog bridge); a `--dry-run` flag returns
  after `create_app()` so CI/tests can assert the wiring without binding a
  port.
- **Dependencies** — added `starlette>=0.37`, `uvicorn>=0.30`,
  `opentelemetry-api>=1.27`, `opentelemetry-sdk>=1.27` to `pyproject.toml`.
- **Tests** —
  - 11 contract tests in `tests/test_health.py` authored independently by a
    `test-author` sub-agent against the spec only.
  - 4 adversarial tests in `tests/evaluation/test_e06_health_logging_eval.py`
    written by `feature-evaluator`, including the one that failed first and
    drove the middleware addition.
  - Session-scoped Postgres container fixture + `bad_dsn` + `reset_logging`
    helper in `tests/conftest.py`.
  - Updated `tests/test_cli.py` and `tests/evaluation/test_e01_scaffolding_eval.py`
    to call `recall serve --dry-run` so they keep asserting clean-exit now
    that serve actually boots a server.
- **Infrastructure** — bumped `.pre-commit-config.yaml` ruff pin from `v0.6.0`
  to `v0.15.11` to stop drift between the local hook and CI (`uv run ruff
  format --check`).
- **LLD synced** — `docs/design/lld-e06-health-logging.md` updated to `0.2`
  with implementation notes for the three design deviations and the additions.

## Decisions made

1. **Per-request asyncpg connect for `/readyz` instead of a pool on
   `app.state.pool`** — the LLD prescribed a pool; skipping it avoids the
   Starlette lifespan dance in in-process httpx `ASGITransport` tests without
   adding `asgi-lifespan` as a dev dep. Timeouts split 0.5 s + 0.3 s to fit
   the 1 s SLA on the failure path. Will switch to the store's pool in Phase 1.
2. **`RequestContextMiddleware` is a pure-ASGI class installed via
   `starlette.middleware.Middleware`** — Starlette's current recommended
   approach over `BaseHTTPMiddleware`. It also emits one `http_request`
   event per call (method / path / status / latency_ms), the HTTP counterpart
   of Phase 1's `mcp_call` event.
3. **`/mcp` stub route dropped** — the LLD listed it as a Phase 0 stub, but
   a no-op route with no consumer is future-refactor churn. Ships in Phase 1
   with real MCP routing.
4. **`sys.stderr.write` for missing `DATABASE_URL` replaced by a structlog
   warning** — raw stderr bypasses the JSON-on-stdout contract (I3).

## Review feedback addressed

`feature-evaluator` verdict: **FAIL** on first implementation. Fixed before PR:

- AC-3 violation: `sys.stderr.write` in `cli.py` bypassed structlog → now logs
  `database_url_unset` via structlog.
- AC-4 violation: `bind_request_context` / `unbind_request_context` existed but
  no middleware called them → added `RequestContextMiddleware`, which also
  emits a per-request `http_request` event so the request context actually
  lands in log output.
- Advisory: `/readyz` timeout budget could exceed 1 s on slow DB → split
  into connect (0.5 s) + query (0.3 s).
- Advisory: silent OTEL stub when endpoint set → now logs
  `otel_export_unimplemented`.

`/pr-review-v2` verdict: 1 block + 5 warn. Fixed in the follow-up commit:

- `[block]` `RequestContextMiddleware` not in LLD → documented in PR body
  under "Design deviations" and now in the LLD itself (Step 1.5).
- `[bug]` `/readyz` query path missed `OSError` → added.
- `[justification]` nested `asyncio.wait_for` around `asyncpg.connect` (which
  already honours `timeout`) → removed the outer wrapper.
- `[justification]` `--dry-run` handling duplicated the setup sequence in
  `main()` → folded into `_cmd_serve`.
- `[compliance]` two `# type: ignore[import-untyped]` comments had no
  justification → added one-line comments explaining asyncpg / testcontainers
  both ship without `py.typed`.
- `[anti-pattern]` per-request asyncpg connect — acknowledged as documented
  Phase 0 deviation, not fixed.

## Cost retrospective

Prometheus textfile collector is not running in this lane, so the cost query
returned `$0.00 / 0 tokens` at both PR creation and final. Useful signal about
cost drivers all the same:

| Driver | Detected? | Impact | Action next time |
|--------|-----------|--------|------------------|
| Context compaction | No — single session | — | — |
| Fix cycles (RED → fix) | Yes (2) | Low | The `test-author` sub-agent wrote unit-level tests only; the `feature-evaluator` then surfaced two middleware-level gaps. Each gap cost ~2 test runs. Action: tighten the `test-author` prompt to always include at least one integration test that exercises the full transport boundary (ASGI request → assertions on captured log lines), not just unit-level contract tests. |
| Agent spawns | test-author, feature-evaluator, ci-probe × 2, pr-review agents Q + B + C | Medium | pr-review ran three agents because diff was 1264 lines — ~half of that is the new test file. Not easily reducible. |
| LLD quality gaps | Yes — no class name for the middleware, prescribed a pool that conflicts with in-process ASGI tests | Medium | LLD could have named the middleware and noted the lifespan trade-off. Feed this back into `/architect` prompt so future LLDs enumerate transport-boundary class names. |
| CI drift | Yes — pre-commit `ruff v0.6.0` vs CI `ruff v0.15.11` | Low, but cost a CI round-trip | Fixed by bumping the pin. Consider pinning in both places via a shared version variable, or let renovate keep them in lockstep. |
| Framework version gotchas | Minimal | — | — |

**Feature cost.**
- PR-creation total: `$0.00 / 0 tokens` (Prometheus not configured).
- Final total: `$0.00 / 0 tokens`.
- Delta is non-signal because collection is off. The post-PR work was real
  (review fixes + CI fix) — real-token estimate is ~30-50k from the four
  extra tool/agent rounds.

## Next steps

Epic #72 (Phase 0 foundation) items remaining — candidates for the next lane:

- E0.5 — test fixture (#77) if not yet shipped
- E0.7 — Docker Compose dev stack
- E0.8 — OTEL export path (waits for E4.2)

Run `gh issue list --label kind:task --state open --limit 5` for the current board.
