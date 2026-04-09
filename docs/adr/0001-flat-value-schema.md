# 0001. Flat `value` schema for stored memories

**Date:** 2026-04-09
**Status:** Accepted
**Deciders:** LS, Claude

## Context

Recall stores memories via LangGraph's `AsyncPostgresStore`. The store schema ([base.py:62-89](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py#L62-L89)) is a single table `store(prefix, key, value jsonb, ...)` — everything user-supplied lives inside the `value` JSONB column. There is no separate metadata column.

The filter compiler ([base.py:622-637](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py#L622-L637)) compiles every predicate to `value->%s <op> ...` or `value->>%s <op> ...` with the field name bound as a SQL parameter. This means **only top-level keys of `value` are filterable** — no JSONPath, no nested traversal. A filter like `{"metadata.kind": "fact"}` silently matches zero rows.

The sibling POC at `../langmem` discovered this the hard way and works around it by hoisting every scalar field from a `metadata` sub-dict to the top level of `value` before `aput`, then re-nesting on read ([memory_manager.py:178-188, 563-576](../../../../langmem/src/mcp_memory_server/langmem/memory_manager.py)). The hoist/unhoist dance is purely compensating for a wrong-shaped schema.

We design our shape from day one, so we have a choice.

## Options Considered

### Option 1: Nested `metadata` sub-dict with hoist/unhoist
Model memories as `{text, metadata: {scope, project_id, kind, tags, ...}}` and hoist fields before store, unhoist after read.
- **Pros:** Clean domain model; metadata is visibly grouped.
- **Cons:** Two data shapes (stored vs. returned); every put/get touches a transformer; easy to add a new metadata field and forget to hoist it — silent filter failure; extra test surface.

### Option 2: Flat `value` with all filterable fields at the root
Store `{text, scope, project_id, kind, tags, created_at, ...}` directly. The Pydantic model *is* the stored shape.
- **Pros:** One shape; filters "just work"; no transformer code; adding a field is a one-line model change; matches the store's actual contract.
- **Cons:** The root dict mixes "content" (`text`) and "classification" (`kind`, `tags`) — aesthetically less tidy.

### Option 3: Bypass `asearch` and query raw SQL
Issue our own SQL against the public `store` table to get richer predicates on nested fields.
- **Pros:** Full Postgres expressiveness.
- **Cons:** Violates REQUIREMENTS.md principle 5 ("Boring storage"). Couples us to internal schema. First crack in the abstraction.

## Decision

**Option 2: flat `value`.** The Recall memory record is a single flat dict; every field that the agent or the server may filter on sits at the root of `value`. No `metadata` sub-dict, no hoist/unhoist layer. The Pydantic model and the stored JSONB are the same shape.

The reasoning: LangGraph's store contract *is* "top-level keys of `value` are queryable". Pretending otherwise means running a transformer on every read and write to paper over a mismatch we invented ourselves. The `../langmem` experience shows the failure mode — a new metadata field lands, the hoist list isn't updated, search silently breaks, and the bug is invisible until a user reports missing results. Flat shape makes that class of bug impossible.

"Content vs. classification" tidiness is cosmetic; we pay for it with a transformer layer and a silent-failure footgun.

## Consequences

- Adding a filterable field is a one-line addition to the memory model. No transformer to update.
- The memory model must reserve root-level names (no collisions between "content" and "classification" fields). We document reserved keys in the model docstring.
- List-valued fields like `tags` still suffer from the operator-poverty problem (no `$in`, no `$contains`) — see ADR 0004.
- Numeric fields at the root still hit the lexicographic comparison bug — see ADR 0004.
- We will NOT build a metadata sub-dict abstraction "for cleanliness". If a future requirement genuinely needs nested non-filterable metadata, we add a single `meta` key with the explicit contract "not filterable" and cover it with a test.
- First integration test to write: put a record with `kind="pref"` at the root, search with `filter={"kind": "pref"}`, assert one hit. This single test guards the invariant forever.
