# 0011. Observability: structlog + OTEL auto-instrumentation only, no hand-rolled spans in v1

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

Observability is the difference between "this server works" and "we can prove this server works to the team using it". REQUIREMENTS.md is unusually specific here:

- **S6.3** mandates one structured JSON log event per MCP call, with a fixed field set (`timestamp`, `level`, `request_id`, `user_id`, `project_id`, `tool`, `latency_ms`, `result_status`, `trace_id`, `span_id`, `extra`), implemented via `structlog`.
- **S6.3a** mandates OpenTelemetry tracing via auto-instrumentation only — HTTP, `asyncpg`, outbound HTTP — with the exporter off by default, activated only by `OTEL_EXPORTER_OTLP_ENDPOINT`. No hand-rolled spans. No custom metrics in v1.

These constraints are the most prescriptive in the entire requirements document, and they are prescriptive deliberately: LangMem v1 accreted ad-hoc logging across modules with no shared schema, and the result was a debugging experience where every incident started with "let me grep for the right log line". v2 ships a contract.

We need to record the contract as an ADR so that:

1. Reviewers can reject any new `print(...)`, `logging.info(...)`, or hand-rolled OTEL span on sight.
2. The "exporter off by default" rule is mechanically defended — a noisy default would break the "single container with sane defaults" deployment story.
3. The fixed log-field set is a public contract operators can build dashboards against, not an implementation detail that drifts with each PR.

## Decision

**Logging.** All log output goes through a single `structlog` logger configured at startup. The logger emits one JSON object per line on stdout. Every MCP call emits exactly one `mcp_call` event with the fields named in S6.3, plus a free-form `extra` for tool-specific detail. The `request_id`, `trace_id`, and `span_id` are bound to a contextvar at the Transport boundary so every downstream log line carries them automatically. Log level is controlled by `LOG_LEVEL`. There is no second logger, no `print`, no module-level `logging.getLogger(__name__).info(...)`. Library log output (asyncpg, httpx, MCP SDK) is bridged into structlog via the standard `logging` integration.

**Tracing.** OpenTelemetry is wired via **auto-instrumentation only**:

- HTTP server (the Streamable HTTP listener)
- `asyncpg` (the Postgres driver)
- Outbound HTTP (`httpx` for embeddings and the compaction LLM)

No hand-rolled spans in v1. The exporter is **off by default**: if `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, OTEL is initialised in a no-op mode with effectively zero runtime cost. If the env var is set, the OTLP exporter is configured against it; the rest of the OTEL configuration follows the standard `OTEL_*` env vars.

`trace_id` and `span_id` are pulled from the active OTEL context and added to every `structlog` event, **regardless of whether the exporter is on**, so logs and traces correlate as soon as someone turns the exporter on.

**Metrics.** Custom metrics are explicitly out of scope for v1. The latency_ms field on every `mcp_call` log line is enough for "is this slow?" investigations until proven otherwise.

## Consequences

**Positive.**
- One log shape across the whole codebase. Operators write one parser, build one dashboard.
- Tracing is free when off and useful when on, with no code change to flip it.
- Reviewing PRs gets easier: any new logging call that is not a structlog event with the standard binding is a finding.
- The S6.3 field set is the contract, recorded once.

**Negative / accepted trade-offs.**
- **No fine-grained spans for "save then embed then put".** Auto-instrumentation gives us the HTTP span, the embedding HTTP span, and the asyncpg span — that is enough for v1 latency forensics. If a real performance question demands more, we revisit this ADR.
- **No metrics dashboard out of the box.** Operators who want one can derive counters from the structured logs. Acceptable for v1; revisit if a real operator pushes back.
- **Bridging library logging into structlog has a one-time cost** to set up correctly. Worth it.

**Not chosen, and why.**
- **`logging` stdlib only, JSON formatter.** Works, but loses structlog's contextvar binding, which is what makes "every line has the request_id" cheap.
- **OTEL with hand-rolled spans from day one.** Encourages span sprawl before we know which spans matter. v1 ships auto-instrumentation; v2 can add hand-rolled spans where evidence demands them.
- **Exporter on by default.** Breaks the "no external dependencies on day one" deployment promise.
- **Prometheus metrics endpoint.** A second observability axis to maintain and document. Out of scope for v1.

## References

- REQUIREMENTS.md — S6.3, S6.3a
- docs/design/v1-design.md — Observability component; cross-cutting through every other component
- ADR-0006 (transport): the Streamable HTTP listener is what OTEL HTTP auto-instrumentation hooks into
