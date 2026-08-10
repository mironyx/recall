# 0006. Streamable HTTP as the sole MCP transport

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

LangMem v1 exposed its MCP surface over a Server-Sent Events shim fronted by an intermediate service, because Streamable HTTP did not yet exist as an MCP standard when v1 was built. The shim accreted reconnect logic, ad-hoc framing, and a parallel "local mode" entrypoint, and was the single largest source of operational friction.

REQUIREMENTS.md (Context, S2.4) makes Streamable HTTP a hard constraint for v1: "the current MCP standard. The old SSE-via-intermediate-service shim goes away." The HLD's Transport component is built around this assumption — it terminates one connection type, routes to one Tool Router, and exposes `/healthz` and `/readyz` as ordinary HTTP endpoints on the same listener.

We need to record the decision so that:

1. Future contributors do not re-introduce SSE or stdio transports as a "convenience" in dev.
2. The single-entrypoint property (design principle 4) is enforceable in code review by citing this ADR.
3. The dependency on a Streamable-HTTP-capable MCP server library is a deliberate, named choice rather than incidental.

## Decision

Recall v1 exposes its MCP surface **exclusively over the Streamable HTTP transport**, served by the official MCP Python SDK's `streamable_http` server. There is one HTTP listener, one transport, one entrypoint (`recall serve`). No SSE shim, no stdio fallback, no parallel "local mode".

`/healthz` and `/readyz` are served on the same HTTP listener as the MCP endpoint, so a single port and a single ingress rule are sufficient to deploy Recall.

## Consequences

**Positive.**
- One transport to test, document, and operate. Integration tests hit the real HTTP server, not a transport-specific harness.
- The Transport component in the HLD has a single, well-defined responsibility: terminate Streamable HTTP and route to the Tool Router.
- Operators get one port, one health-check semantics, one log format for connection lifecycle.
- The "one server, one transport, one entrypoint" principle from REQUIREMENTS.md is mechanically enforced by the absence of alternative code paths.

**Negative / accepted trade-offs.**
- MCP clients that only speak stdio (some IDE plugins still do) cannot point at Recall directly. Mitigation: those clients can run a thin local proxy. This is the operator's problem, not Recall's, and is documented in the MCP-config snippet shipped with the server (S5.6).
- We are coupled to the MCP Python SDK's Streamable HTTP implementation. If that implementation regresses or stalls, we do not have a second transport to fall back on. Accepted because the SDK is the upstream reference implementation.
- Local development can no longer rely on a stdio loopback; `docker compose` (S5.2) or `recall serve` against a local Postgres is the supported dev path.

**Not chosen, and why.**
- **SSE shim (v1 status quo).** The very thing this rewrite removes; no.
- **stdio transport in addition.** Doubles the test matrix and re-introduces a parallel entrypoint. The benefit (works with one class of dated client) does not justify the structural cost.
- **gRPC.** Not an MCP transport. Out of scope.

## References

- REQUIREMENTS.md — "Hard constraints" section; S2.4
- docs/design/v1-design.md — Transport component; interaction I1
- Design principle 4 ("one server, one transport, one entrypoint")

## Amendment 1 (2026-08-10, PR #117): 2026-07-28 protocol revision, mcp SDK 2.0.0

The transport is served by the **mcp SDK 2.0.0** (PyPI, 2026-07-28 — the same
day the 2026-07-28 MCP spec revision was published). The original #117
implementation used mcp 1.27.0 (2025-11-25 spec revision) in its `stateless`
manager mode; the user directed a rewrite onto the latest published revision
("in our doc we says that we should use latest"). What changed at the protocol
level, all adopted here:

- **Sessions removed from Streamable HTTP** (SEP-2567) — no MCP-Session-Id,
  no session map, no SSE stream. Stateless is the protocol itself, not a
  manager mode; every tool call completes in one round trip.
- **Initialize handshake removed** (SEP-2575) — version negotiation and
  capabilities moved to the first request's `_meta`; clients call tools
  directly.
- **`resultType` is required** on call-tool requests; responses default to
  `complete`.
- Wire types are pydantic models (snake_case fields: `structured_content`,
  `input_schema`, ...); the v2 `Server` is built on a dispatcher engine with
  `on_list_tools`/`on_call_tool` callbacks.

Composition on this revision: `Server("recall", on_list_tools=..., on_call_tool=...)`
→ `streamable_http_app(json_response=True, stateless_http=True, host="0.0.0.0")`
→ mounted as a Starlette sub-app at `/`; the dispatcher task group runs in the
app lifespan. `host="0.0.0.0"` mirrors `cli.DEFAULT_HOST` and keeps the SDK's
DNS-rebinding auto-protection off (it only engages for localhost binds) — a
public deploy should pass its configured hostname explicitly (serve epic).

**Deferred (tracked, not in #117):** the SDK's `tasks` extension and DPoP are
not yet implemented in 2.0.0; adopt when upstream lands them.
