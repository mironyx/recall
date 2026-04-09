# 0002. Namespace shape `(scope, project_id)` and character rules

**Date:** 2026-04-09
**Status:** Accepted
**Deciders:** LS, Claude

## Context

REQUIREMENTS.md S1.7 / S3.7 fixes the storage namespace as `(scope, project_id)`. Recall sits on `AsyncPostgresStore`, which stores the namespace tuple in a single `text` column `prefix` via `_namespace_to_text` — literally `".".join(namespace)`. Namespace prefix search compiles to `store.prefix LIKE 'ns1.ns2.%'` ([base.py:446-447](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/store/postgres/base.py#L446-L447)).

Two concrete issues follow:

1. **Dots in components break the encoding.** A `project_id` containing `.` would alias across tuple boundaries — `("project", "a.b")` and `("project", "a", "b")` hash to the same `prefix`. Not hypothetical: git-style project slugs, domain-style IDs (`acme.recall`), and file paths all contain dots.
2. **`scope=global` needs a concrete tuple.** The store requires a tuple; we cannot put `(scope,)` for globals and `(scope, project_id)` for projects without breaking the "constant arity" assumption that makes `list_namespaces` and prefix search predictable.

## Options Considered

### Option 1: Variable-arity tuple — `("global",)` vs. `("project", pid)`
- **Pros:** Honest about the two shapes.
- **Cons:** `list_namespaces(prefix=("project",))` and max_depth semantics differ per scope; code paths branch on arity.

### Option 2: Constant arity `(scope, project_id)`, globals use a sentinel `"_"`
- **Pros:** One shape everywhere; prefix search works uniformly; `list_namespaces(prefix=("global",))` and `(("project",))` both behave the same.
- **Cons:** Sentinel is a magic value; need to reserve `"_"` as a non-valid project_id.

### Option 3: Hash project_id to a safe form (e.g. base32)
- **Pros:** Any input works; no validation needed.
- **Cons:** Opaque in SQL; humans cannot read the `prefix` column; debugging is harder; no real benefit over validation.

## Decision

**Option 2, plus strict validation of `project_id`.**

- Namespace is always a 2-tuple: `(scope, project_id)`.
- `scope ∈ {"global", "project"}`.
- For `scope="global"`, `project_id` is the sentinel `"_"` (reserved — rejected as a user-supplied project_id).
- `project_id` must match `^[a-zA-Z0-9_-]{1,128}$`. No dots, no whitespace, no Unicode. Enforced at the API boundary, not in storage.

Rationale: constant arity makes every code path simpler. The regex is strict because the cost of a permissive regex is a silent namespace collision — exactly the kind of bug that takes weeks to notice and is unrecoverable once data is written. We can always loosen later; we cannot tighten without migration.

## Consequences

- All project_ids are human-readable in the `store.prefix` column — debugging is trivial.
- Agents passing a "pretty" project name (with dots, slashes, spaces) get a clear validation error at the tool boundary instead of silent data corruption.
- `_` is permanently reserved. Documented in the tool schema.
- Migration: none — we have no data yet.
- First test: assert `project_id="a.b"`, `"a/b"`, `"_"`, `""`, `"a"*129` all raise at the API boundary; assert `"global"/"_"` and `"project"/"my-proj_1"` round-trip through put/search/list_namespaces.
- If we ever need hierarchical projects (e.g. org → project), that's a widening of the namespace and requires a new ADR per REQUIREMENTS.md "never widen the namespace" rule.
