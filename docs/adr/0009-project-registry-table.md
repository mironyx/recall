# 0009. Project registry sourced from a `projects` table

**Date:** 2026-04-10
**Status:** Superseded by ADR-0014 (2026-04-29)
**Deciders:** LS / Claude

## Context

The Project Registry component (HLD Level 2) owns the list of valid `project_id`s and rejects requests that name an unknown project or the reserved name `global` (S3.8). The requirements (S3.1) leave the source open: "config file or `projects` table".

That ambiguity is fine in a spec but expensive in code: two parallel sources of truth means two loaders, two test suites, and two ways to drift. Recall is multi-machine shared infrastructure, so a config file would need to be identical across replicas — there is no "the file" without a shared filesystem, and shipping a config-file source-of-truth implicitly forces operators to bind-mount or templating.

A database table is already a hard dependency (Postgres + pgvector for memories themselves). Adding one more table is free. The table is the natural place to enforce uniqueness, the case-insensitive `global` exclusion, and the audit columns operators will eventually want.

We need to pin the choice now because:

1. The Auth and Tool Router components both call into the registry — splitting later means refactoring two consumers.
2. The Migrations component (ADR-0013 to come) needs to know whether `projects` is part of the schema or not.
3. Two parallel loaders is exactly the kind of "small convenience" that becomes the next entrypoint to delete in v2.

## Decision

Recall v1 sources its project list from a **`projects` table** in the same Postgres database that holds memories. There is no config-file fallback in v1.

Schema sketch (the LLD will pin types and indexes):

```
projects(
    id           text primary key,            -- the project_id agents pass
    display_name text not null,
    created_at   timestamptz not null default now(),
    created_by   text not null                -- user_id of the operator
)
```

Constraints:

- A `CHECK` constraint rejects `lower(id) = 'global'` to enforce S3.8 at the schema level.
- The Project Registry component caches the table contents in memory and refreshes on demand (CLI command) or on a fixed interval. It does not query Postgres on every request.
- Operators manage projects with a small `recall projects add|list|remove` CLI subgroup. There is no MCP tool for project management — projects are operator concerns, not agent concerns.
- The cache miss path (agent passes a `project_id` not in the cache) triggers exactly **one** refresh from the database before rejecting, so a freshly-added project is usable without restart.

## Consequences

**Positive.**
- One source of truth across all replicas — Postgres is already shared.
- The `global`-name exclusion is a schema constraint, not a Python check that can be bypassed.
- Operators get audit columns for free (`created_at`, `created_by`).
- Adding a project does not require a deploy or a config-file edit; the CLI suffices.
- The Migrations component (ADR-0013) gets one more table to manage, not a separate concern.

**Negative / accepted trade-offs.**
- **An extra table in the schema** that some operators might find unnecessary if they truly only have one project. Acceptable: the table is tiny, and the consistency story is worth more than one row of overhead.
- **No configuration-as-code workflow** (commit a YAML, deploy, project exists). Operators who want that pattern can run a startup script that calls `recall projects add` from a checked-in script — Recall does not need to own the workflow.
- **Cache staleness window** between operator add and agent retry. Mitigated by the single-refresh-on-miss rule above.

**Not chosen, and why.**
- **Config file (YAML / TOML).** Forces a shared-filesystem assumption that the rest of the design carefully avoids. Re-introduces the multi-machine drift problem v1 exists to fix.
- **Both file and table.** Two loaders, two test paths, two ways to be wrong. Exactly the kind of accretion the rewrite is rejecting.
- **No registry; trust the agent.** Removes the S3.8 reserved-name guard and lets typos pollute the namespace. Hard no.

## References

- REQUIREMENTS.md — S3.1, S3.7, S3.8
- docs/design/v1-design.md — Project Registry, Auth, Tool Router components
- ADR-0002 (namespace shape): `(scope, project_id)` is the only namespace shape
