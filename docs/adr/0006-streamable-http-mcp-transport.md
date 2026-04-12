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
