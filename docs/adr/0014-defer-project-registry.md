# 0014. Defer project registry — infer projects from store prefix

**Date:** 2026-04-29
**Status:** Accepted (supersedes ADR-0009)
**Deciders:** LS / Claude

## Context

ADR-0009 chose a `projects` table as an explicit allowlist: agents pass a `project_id`, the
server validates it against the table, and unknown IDs are rejected. The table also stores
`display_name` and `created_by` metadata, and a CLI subgroup (`recall projects add|list|remove`)
manages it.

On review, the registration requirement creates friction disproportionate to the problem it solves:

- An operator must register a project before any agent can write memories to it.
- A typo creates a phantom project but does not corrupt existing namespaces — rows with the
  wrong prefix are easy to spot and delete.
- For a small self-hosted deployment (the primary Phase-0 target), the table is ceremony for
  zero real gain.
- The `projects` table also adds a query on every inbound MCP call (registry cache lookup),
  which the simpler model eliminates entirely.

A secondary insight emerged: **`global` is semantically just another project** — a reserved
namespace that all agents can read, rather than a fundamentally different storage dimension.
The current two-scope model (`scope ∈ {project, global}` × `project_id`) could be collapsed to
a single `project_id` axis where `global` is a reserved name. This is noted here for future
consideration; it requires revising ADR-0001 and ADR-0002 and is deferred until the memory
tool layer is designed.

## Decision

1. **Drop the `projects` table.** `ensure_schema` no longer creates it. The set of projects in
   use is inferred from `SELECT DISTINCT prefix FROM store WHERE prefix LIKE 'project.%'`.

2. **No pre-validation of `project_id`.** Any well-formed project ID is accepted on first write.
   The scope CHECK constraint on `store.prefix` (ADR-0002) continues to enforce the namespace
   shape; it is not removed.

3. **Defer the `recall projects` CLI subgroup.** No `add`, `list`, or `remove` commands. If
   explicit project management is needed in the future, the table and CLI can be added then.

4. **Note the global-as-project insight.** Captured here; no code change now. Revisit when
   implementing the memory tools (Epic 1).

## Consequences

**Positive.**
- `ensure_schema` creates two tables (`store`, `store_vectors`) and one constraint — nothing
  more. Schema is as small as it can be.
- No registry cache, no cache invalidation, no lookup on every MCP call.
- Operators do not need to register a project before an agent can run.
- `TestProjectsTable` test class and related CLI tests are removed — fewer tests to maintain.

**Negative / accepted trade-offs.**
- **No explicit project allowlist.** A misconfigured agent can create a phantom namespace. Accepted:
  the isolation guarantee (project A cannot read project B) is enforced by the namespace shape,
  not by the allowlist. Phantom projects are visible in the store and deletable.
- **No display name or created_by metadata.** Accepted for now. Add with the table if needed.
- **If multi-tenant validation becomes required** (unknown agent passes arbitrary project IDs and
  must be rejected), the table should be reinstated. The schema and CLI design from ADR-0009
  remain the reference for that future work.

## References

- ADR-0009 (superseded): original project registry design
- ADR-0001 (flat value schema): CHECK constraint retained
- ADR-0002 (namespace shape): scope CHECK on `store.prefix` retained
- REQUIREMENTS.md — Story 5.3 (marked Deferred)
