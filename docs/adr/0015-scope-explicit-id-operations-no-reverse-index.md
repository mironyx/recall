# 0015. Scope-explicit ID operations: no reverse index

**Date:** 2026-08-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

The tool reference table in REQUIREMENTS.md (Story 1.4, 1.5, 2.4) originally
defined `memory_get` / `memory_update` / `memory_delete` as **id-only**
operations. The storage namespace is `(scope, project_id)` per ADR-0002, and
`AsyncPostgresStore.aget()` requires a namespace tuple. To bridge the two,
the E1.5 LLD (`lld-e1-one-memory-e2e.md`, §E1.5 design note) prescribed a
**reverse index** in the raw store: on `save`, also write a `("_index", "_")`
entry mapping `memory_id → {scope, project_id}`; on `get_by_id`, look the
namespace up in the index, then fetch the record.

During implementation review, the reverse index was challenged:

1. **No user-level use case needs id-only operations.** The dominant flow is
   search-first: an agent searches within a project, gets results that carry
   `scope` (and project context), and acts on a memory. The scope is always
   known at the point of acting; resolving an id to a namespace is never
   required by the product.
2. **The index is pure cost.** It turns `save()` into two non-atomic writes
   (a failed index write orphans the memory — get_by_id would 404 on a
   searchable record), `get_by_id()` into two reads, and it introduces a
   storage namespace outside `(scope, project_id)` — a direct violation of
   ADR-0002 that requires widening the `store_scope_invariant` CHECK
   constraint. None of these are priced by any requirement.

## Decision

**Drop the reverse index.** `memory_get`, `memory_update`, and
`memory_delete` take `scope` + `project_id` + `id` explicitly:

- `save()` is a **single write** (the flat value record, ADR-0001) with an
  embedding index on `content`.
- `get_by_id()` is a **direct namespaced read**: `storage.get(scope,
  project_id, memory_id)`, raising `NotFoundError` when absent.
- The storage namespace stays exactly `(scope, project_id)` — no widening,
  no `("_index", "_")`, no change to the CHECK constraint.
- `update` / `delete` (later phases) take the same explicit scope parameters.

## Consequences

**Positive.**
- No non-atomicity: `save()` is one write, so a stored memory is always
  retrievable by id (Story 1.3 AC4 holds structurally).
- No namespace widening beyond ADR-0002, no CHECK-constraint surgery, no
  migration debt.
- Less code: ~10 lines of index plumbing and one DB exception removed.
- The MCP tool surface stays honest about where data lives — the parameters
  mirror the storage namespace (ADR-0002) directly.

**Negative / accepted trade-offs.**
- **Callers must supply the scope.** A memory cannot be fetched by id alone;
  the caller must know its `(scope, project_id)`. In practice this is free:
  `memory_search` returns `scope` on every result, and the router already
  operates in a project context (it validates `project_id` per ADR-0014).
  Id-only recall with unknown scope is intentionally unsupported — search
  is the discovery path, and the requirements define no flow that needs it.
- **Retroactive interface change.** The requirements tool table and issue
  #90 AC2/AC3 were written against the id-only contract; they are updated
  in sync with this ADR. The LLD §E1.5 design note is superseded.

## References

- Supersedes: `lld-e1-one-memory-e2e.md` §E1.5 design note "memory_get ID
  resolution" and issue #90 AC2/AC3 (id-only contract).
- Implementation: PR #115 (E1.5 Memory Service).
