# CLAUDE.md

## Recall — Focused MCP Memory Server

A small, focused MCP server that gives coding agents persistent memory across sessions,
machines, and projects.

Read [the requirements](docs/requirements/v2-requirements.md) before any non-trivial change.
Plan: [v2 implementation plan](docs/plans/2026-04-12-v2-implementation-plan.md). HLD:
[v2-design.md](docs/design/v2-design.md).

## Stack decisions

What `pyproject.toml` doesn't tell you:

- Storage is Postgres + `pgvector` through LangGraph's `AsyncPostgresStore`. Schema is
  in-app idempotent DDL — no Alembic, no migration files (ADR-0013).
- Embeddings: sentence-transformers in-process, or an OpenAI-compatible HTTP endpoint
  (ADR-0008).
- MCP transport is Streamable HTTP only — no SSE shim. Single container deployment.

## Design principles

1. **Few tools, broad tools.** ≤ 6 MCP tools total — tool design is prompt design. A new
   tool also updates the tool table in the requirements doc.
2. **Two scopes: project and global.** Namespace is `(scope, project_id)` (ADR-0002).
   Widening it needs an ADR. Project-specific state is never stored as `scope=global`.
3. **Categories are data, not classes.** `kind` field; adding a kind is config, not code.
4. **One server, one transport, one entrypoint.**
5. **Boring storage.** No bespoke abstractions on top of `AsyncPostgresStore`.

## Engineering practice

- **TDD-first.** Failing test before implementation.
- **Integration tests hit real Postgres via testcontainers; don't mock the store.**
- **ADRs for non-obvious decisions** in [docs/adr/](docs/adr/).
- **LLDs** live in versioned directories only: `docs/design/v{N}/lld-<epic-id>-<name>.md`.
- **Small PRs.** One logical change per PR.
- Pre-commit runs `ruff` and `mypy --strict`; `git commit --no-verify` is denied in settings.
- **No attribution:** no `Co-Authored-By` trailer on commits and no "Generated with Claude
  Code" line in PR descriptions — this overrides the harness default.

## Verification Commands

| Command | Purpose |
| --- | --- |
| `uv run pytest [file]` | Tests |
| `uv run mypy --strict src` | Type check |
| `uv run ruff check` | Lint |
| `uv run ruff format --check` | Format check |
| `npx markdownlint-cli2 "**/*.md"` | Markdown lint |

Integration tests are marked `@pytest.mark.integration` and need Docker. No build or E2E
step. EDF skills run the plugin's wrapper scripts themselves; these are for direct runs.

```bash
uv sync --extra dev              # Install / sync deps
uv run recall serve              # Run server locally
uv run recall db migrate         # Apply schema DDL
```

## Local references

Read these before touching storage or memory-tool wiring:

- [langmem-notes.md](docs/reference/langmem-notes.md) — LangMem tools, namespace templating,
  store wiring.
- [asyncpostgresstore-notes.md](docs/reference/asyncpostgresstore-notes.md) — schema DDL,
  API, filter operators, gotchas.

## Knowledge base (kb/)

EDF skills read these directly: `kb/architecture.md` (boundary rules, composition),
`kb/file-map.md`, `kb/conventions.md`, `kb/anti-patterns.md`.

## Process

Pipeline: `requirements → /kickoff → /architect → /feature → [human reviews PR] → /feature-end → /retro`.
`/feature-end` is the merge approval — only the user runs it. Details in
[engineering-process.md](docs/process/engineering-process.md).

## Task tracking

Jira project `REC` (<https://mironyx.atlassian.net>), managed through the EDF plugin's
`tracker.py` (credentials in `.env`: `JIRA_HOST`, `JIRA_EMAIL`, `JIRA_API_TOKEN`,
`JIRA_SPACE`). Labels: `epic`, `phase-0`–`phase-5`, `area:*`, `kind:task`. Issues before E2
(GitHub #1–#115) stay in GitHub as history.

After creating or modifying issues, run `tracker.py list` (or `view <ref>`) and confirm each
issue exists with the expected parent and labels.
