# 0003. TTL: not used in v1

**Date:** 2026-04-09
**Status:** Accepted
**Deciders:** LS, Claude

## Context

`AsyncPostgresStore` supports per-record TTL via `expires_at` and `ttl_minutes` columns. Expiry is **not enforced by queries** — `asearch` and `aget` happily return expired rows. Rows only disappear when something calls `sweep_ttl()`, which runs `DELETE FROM store WHERE expires_at < NOW()`. The store provides `start_ttl_sweeper()` ([aio.py:311](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/aio.py#L311)) that loops the sweep on an interval.

This means any process that enables TTL also owns a background task, owns its startup/shutdown lifecycle, and must reason about expired-but-not-yet-swept rows being visible to `search` in the gap between expiry and the next sweep.

REQUIREMENTS.md does not mention memory expiry. There is no requirement for memories to auto-vanish.

## Options Considered

### Option 1: No TTL — memories are permanent until explicitly deleted
- **Pros:** No background tasks; no lifecycle complexity; matches user intuition ("memory" that silently disappears is surprising); no "visible-but-expired" window to reason about.
- **Cons:** Unbounded growth; no auto-cleanup for ephemeral notes.

### Option 2: TTL with sweeper owned by the server process
- **Pros:** Full feature, opt-in per record.
- **Cons:** Server lifecycle gains a background task; multi-replica deployments run N redundant sweepers; the visibility gap is a correctness footgun for any "definitely gone" contract; every integration test touching TTL must either wait or call `sweep_ttl()` directly.

### Option 3: TTL with sweeper as an external cron / `pg_cron` job
- **Pros:** Server stays stateless; one sweeper regardless of replica count.
- **Cons:** Extra operational surface; not portable to local dev; still has the visibility gap.

## Decision

**Option 1. Recall v1 does not use TTL.** No `ttl` config passed to `AsyncPostgresStore`, no sweeper in the server lifecycle. If a caller passes `ttl_minutes` on a memory write, **we raise** rather than silently ignore — silent-ignore would mislead the agent into believing expiry works.

Rationale: TTL is a feature we do not need. Every line of lifecycle code we write for it is load-bearing (get startup/shutdown wrong and memories leak or vanish), and the visible-but-expired window breaks the "memory is authoritative" contract we want the agent to trust. Deletion stays explicit via the MCP tool.

## Consequences

- Server startup = open store + run migrations. Shutdown = close store. No background tasks.
- Memories grow until explicitly deleted — this is a feature, not a bug. If unbounded growth becomes a real problem, the fix is a retention policy decision, not a TTL toggle.
- The `expires_at` / `ttl_minutes` columns will exist in the schema (the store's migrations create them unconditionally) but will always be NULL. Acceptable — we do not own that schema.
- Trigger to revisit: a concrete requirement for auto-expiring memories (e.g. "ephemeral session scratch notes"). A future ADR would need to specify: sweeper owner, sweep interval, whether `search` post-filters for strict-gone semantics, shutdown-race tests.
