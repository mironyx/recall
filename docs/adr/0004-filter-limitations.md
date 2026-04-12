# 0004. AsyncPostgresStore filter limitations and workarounds

**Date:** 2026-04-09
**Status:** Accepted
**Deciders:** LS, Claude

## Context

Source reading of `AsyncPostgresStore` ([base.py:622-637](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py#L622-L637)) surfaced two filter gotchas beyond the "top-level keys only" rule captured in ADR 0001:

### Gotcha A: lexicographic numeric comparison

```python
elif op == "$gt":  return "value->>%s > %s",  [key, str(value)]
elif op == "$gte": return "value->>%s >= %s", [key, str(value)]
elif op == "$lt":  return "value->>%s < %s",  [key, str(value)]
elif op == "$lte": return "value->>%s <= %s", [key, str(value)]
```

`value->>%s` returns JSONB as text, and the bound value is `str(value)`. Comparison is therefore lexicographic: `"9" > "11"` is true, `"10" < "2"` is true. Any numeric range filter is wrong. The sibling project `../langmem` discovered this and subclassed the store with a `CAST(value->>%s AS NUMERIC)` override ([fixed_postgres_store.py:17-67](../../../../langmem/src/mcp_memory_server/langmem/fixed_postgres_store.py)).

Strange that this is unfixed upstream — the patch is three lines and the bug is obvious — but we must assume it stays broken until we verify the pinned langgraph version.

### Gotcha B: operator poverty

The entire operator set is `$eq $ne $gt $gte $lt $lte`. Missing: `$in`, `$nin`, `$exists`, `$contains`, `$regex`, logical `$and`/`$or`. Multiple top-level keys in a filter dict are implicitly AND-ed ([base.py:452](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py#L452)).

This hurts list-valued fields most. `tags: ["python", "async"]` cannot be filtered with "memories tagged `python`" using the built-in compiler — there is no `$contains` and `$eq` compares the whole array.

## Options Considered

### For numeric ranges

1. **Avoid numeric filters entirely.** Store timestamps as ISO-8601 strings (lexicographically sortable and correct when same-length UTC), store counts as zero-padded strings if ever filtered, otherwise keep numbers in `value` but never filter on them.
2. **Subclass and override** `_get_filter_condition` with `CAST(... AS NUMERIC)`, like `../langmem`.
3. **Drop to raw SQL** for numeric-range queries, bypassing `asearch`.

### For list-valued tag filters

1. **Post-filter in Python** after a broader fetch. Cheap for small result sets, wrong for large ones.
2. **Store a per-tag boolean** (`tag_python: true`, `tag_async: true`) at the top level. Ugly but filterable with `$eq`.
3. **Raw SQL using JSONB operators** (`value->'tags' ? 'python'`, or `@>`).
4. **One search per tag + union in Python.** Works for small tag sets, blows up for `$and` semantics.

## Decision

### Numeric ranges: avoid them, don't patch the store

- Timestamps are stored as ISO-8601 UTC strings (`"2026-04-09T12:34:56Z"`). Lexicographic `$gte`/`$lte` is correct for same-length UTC strings and matches human intuition.
- Any other numeric field at the root of `value` is **not filterable** by contract. If we ever need a numeric range filter, that's the trigger to either patch the store (subclass) or drop to raw SQL — and we decide at that point, with a real use case in hand.
- We will **not** carry a `FixedAsyncPostgresStore` subclass pre-emptively. Every line of code compensating for an upstream bug is a liability when upstream fixes it.
- Verification: first integration test writes two memories with ISO timestamps one hour apart, asserts `$gte` on the midpoint returns only the later one. This locks the contract.

### List-valued tag filters: not filterable in v2

**Amended 2026-04-12.** The original decision proposed a raw-SQL helper for
tag containment. After further discussion, we decided against it:

- The `tags` field is a list of strings stored at the root of `value`.
- The built-in filter compiler cannot query inside a list (`$eq` compares
  the whole array, not individual elements).
- **Tags are stored but not filterable in v2.** The `memory_search` tool
  does not accept a `tags` filter parameter. Tags exist on the record for
  display and future use, but the server does not filter on them.
- **No raw-SQL escape hatch.** The original proposal for a `value->'tags' ?`
  helper is withdrawn. It would be the only raw SQL touching the store,
  violating the "boring storage" principle (design principle 6) for a
  feature that semantic search already handles well — if an agent needs
  memories about "python", a semantic query for "python" works.
- Trigger to revisit: if agents demonstrably need structured tag filtering
  that semantic search cannot satisfy, propose a new ADR. Options at that
  point: raw-SQL helper (scoped), post-filter in Python, or upstream
  `$contains` support.

### Operator poverty in general

- We design the memory model so the six supported operators are sufficient. If a filter requirement arrives that needs `$in`, we first ask whether the model can be reshaped; only if not do we write a raw-SQL helper.

## Consequences

- Timestamps are ISO strings, not integers or `datetime` objects, in the stored `value`. The Pydantic model serializes on put and parses on read. Documented in the memory model docstring.
- **No raw SQL in v2.** The store is used strictly through its public API (`asearch`, `aput`, `aget`). Zero raw-SQL helpers.
- We do not subclass `AsyncPostgresStore`. The store is used as-is.
- Tags are stored on the record but ignored by the search filter. Agents rely on semantic search to find memories by topic.
- Integration tests that must exist before the search tool ships:
  - `$eq` on top-level `kind` — passes with flat shape (ADR 0001).
  - ISO timestamp `$gte` / `$lte` — guards the "no numeric filters" decision.
  - A negative test asserting nested `{"meta.kind": "x"}` returns zero — guards ADR 0001's flatness invariant.
- If upstream fixes the numeric comparison bug (watch for a PR touching `_get_filter_condition`), we can relax the "no numeric filters" rule without code changes — only the ADR needs updating.
