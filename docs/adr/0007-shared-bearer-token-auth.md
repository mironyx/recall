# 0007. Shared bearer tokens for v1 auth, OIDC and mTLS deferred

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

Recall is shared infrastructure: one server, multiple humans, multiple machines, multiple agents. Every request must resolve to a `user_id` because that id appears in audit logs (S6.3) and in stored memories (S1.1). Without an identity per request, we cannot tell who saved what, and the audit trail is worthless.

The requirements (S3.5) explicitly defer OIDC and mTLS beyond v1, leaving "shared bearer token per user, configured out-of-band" as the v1 mechanism. The HLD's Auth component is built around this assumption — bearer-token lookup, `user_id` injection, hard-reject on miss.

We need to record the choice so that:

1. Reviewers can cite this ADR when someone proposes adding OIDC mid-v1.
2. The upgrade path to OIDC/mTLS in a later version is named explicitly, not left as a vague "we'll figure it out".
3. The token-storage shape (a flat map of `token → user_id`, sourced from env or a config file) is fixed before two parallel implementations appear.

## Decision

Recall v1 authenticates every MCP request with a **shared bearer token per human user**, presented as `Authorization: Bearer <token>` on the Streamable HTTP request. The Auth component resolves the token to a `user_id` against an in-memory map loaded at startup from configuration. If the token is missing, malformed, or unknown, the request is rejected with a structured `{error: "unauthenticated", hint: ...}` envelope and an audit log line; no MCP tool runs.

Token-to-user mapping is configured **out-of-band** as a YAML or JSON file referenced by an env var (e.g. `RECALL_AUTH_FILE`), or inline as a JSON-encoded env var for single-user dev. The file format is a flat object: `{"<token>": {"user_id": "<id>"}}`. There is no token-issuing endpoint — operators rotate tokens by editing the file and restarting (or sending SIGHUP, if cheap to wire).

OIDC, mTLS, per-user scoping rules, and per-project ACLs are **explicitly deferred** beyond v1. They will get their own ADR when the time comes. v1 ships one knob.

## Consequences

**Positive.**
- Auth component has one code path: read header, look up token, inject `user_id`. Trivially testable.
- No external dependency on an identity provider; `docker compose up` is genuinely self-contained.
- Operators can stand up Recall in five minutes for a small team.
- The audit-log invariant (every request has a `user_id`) is enforced at the Transport→Auth boundary, not scattered.

**Negative / accepted trade-offs.**
- **Token leakage is total compromise** for the affected user. Mitigation: tokens go in a config file with `0600` perms, never in source. Documented in the deployment artefacts (S5.6).
- **No revocation without restart** in v1. SIGHUP-based reload is a stretch goal; if we don't ship it, operators rotate by restart. Acceptable for v1 because the audience is small teams.
- **No multi-factor**, no session expiry, no rate limiting per token. All deferred. Recall is shared *internal* infrastructure, not internet-exposed; if anyone deploys it on the public internet, that's a downstream operator decision and they need to put a real auth proxy in front.
- The upgrade to OIDC/mTLS in v2 will mean a new ADR and a real Auth refactor. We accept that cost in exchange for v1 simplicity.

**Not chosen, and why.**
- **OIDC.** Right answer for v2; for v1 it adds an IdP dependency, a callback endpoint, JWT validation, and a JWKS cache — none of which advance the v1 product goal.
- **mTLS.** Strong, but operationally heavy and forces a cert-management story Recall does not have.
- **API keys with scopes.** Re-creates a permission model; v1 has none (every authed user can read every memory in every project they touch).
- **Anonymous mode.** Breaks the audit invariant. Hard no.

## References

- REQUIREMENTS.md — S3.2, S3.5, S3.6
- docs/design/v1-design.md — Auth component; interaction I5
- ADR-0006 (transport): bearer header rides on the same Streamable HTTP listener
