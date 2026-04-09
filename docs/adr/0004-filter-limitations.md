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

### List-valued tag filters: single-tag `$eq` in v1, revisit if insufficient

- The `tags` field is a list of strings at the root of `value`.
- The built-in filter compiler cannot query inside a list. For v1, tag filtering is **not exposed through the standard filter dict**. If the search tool needs "tagged X", it issues a raw-SQL predicate `value->'tags' ? %s` through a single well-named helper on the store wrapper — not a general "raw SQL" escape hatch, just one tag predicate.
- This is the one crack we allow in "boring storage" (REQUIREMENTS.md principle 5), and it is scoped to a single JSONB operator on a single field. The alternative (per-tag boolean fields) pollutes the schema; post-filtering in Python is unsound at scale.
- `$and` over multiple tags: chain `value->'tags' ?& array[%s, %s, ...]`. `$or`: `?|`. Both are single-expression, no loop.
- Trigger to revisit: if the agent needs richer tag predicates (`NOT`, regex, hierarchical tags), escalate to a new ADR.

### Operator poverty in general

- We design the memory model so the six supported operators are sufficient. If a filter requirement arrives that needs `$in`, we first ask whether the model can be reshaped; only if not do we write a raw-SQL helper.

## Consequences

- Timestamps are ISO strings, not integers or `datetime` objects, in the stored `value`. The Pydantic model serializes on put and parses on read. Documented in the memory model docstring.
- One small raw-SQL helper exists for tag containment. It is the *only* place raw SQL touches the store, and it is covered by integration tests that assert the JSONB `?`, `?&`, `?|` operators behave as expected.
- We do not subclass `AsyncPostgresStore`. The store is used as-is.
- Integration tests that must exist before the search tool ships:
  - `$eq` on top-level `kind` — passes with flat shape (ADR 0001).
  - ISO timestamp `$gte` / `$lte` — guards the "no numeric filters" decision.
  - Tag containment via the raw-SQL helper — guards the single escape hatch.
  - A negative test asserting nested `{"meta.kind": "x"}` returns zero — guards ADR 0001's flatness invariant.
- If upstream fixes the numeric comparison bug (watch for a PR touching `_get_filter_condition`), we can relax the "no numeric filters" rule without code changes — only the ADR needs updating.
