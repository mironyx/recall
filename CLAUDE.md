# CLAUDE.md

## Behavioral guidelines

- **Think before coding.** State assumptions. If uncertain, ask. If multiple interpretations exist, present them.
- **Simplicity first.** Minimum code that solves the problem. No speculative features, abstractions, or error handling for impossible scenarios.
- **Surgical changes.** Touch only what you must. Match existing style. Don't "improve" adjacent code. Every changed line should trace to the request.
- **Goal-driven execution.** Transform tasks into verifiable goals. Write the failing test first, then make it pass.
- **No re-reads.** Do not re-read a file already loaded in the current session. Reference it by path only.

## Recall — Focused MCP Memory Server

A small, focused MCP server that gives coding agents persistent memory across sessions, machines, and projects.

**Current phase:** Phase 0 — Foundation. See [implementation plan](docs/plans/2026-04-12-v2-implementation-plan.md) and [HLD](docs/design/v2-design.md).

**Read [REQUIREMENTS.md](docs/requirements/v2-requirements.md) before starting any non-trivial change.**

## Tech stack

- **Language:** Python 3.12+
- **Package manager:** `uv`
- **Lint / format:** `ruff` (lint + format in one tool)
- **Type checker:** `mypy --strict`
- **Tests:** `pytest` + `pytest-asyncio`; integration tests use `testcontainers` against real Postgres
- **Storage:** Postgres + `pgvector`, accessed via `AsyncPostgresStore`
- **Embeddings:** sentence-transformers (in-process) or OpenAI-compatible HTTP (ADR-0008)
- **MCP transport:** Streamable HTTP (no SSE shim)
- **Deployment:** single container

## Design principles

1. **Few tools, broad tools.** ≤ 6 MCP tools total. Tool design is prompt design.
2. **Two scopes: project and global.** Namespace is `(scope, project_id)` (ADR-0002).
3. **Categories are data, not classes.** `kind` field; adding a kind is config, not code.
4. **One server, one transport, one entrypoint.**
5. **Boring storage.** No bespoke abstractions on top of `AsyncPostgresStore`.

## Engineering practice

- **TDD-first.** Failing test before implementation. Integration tests hit real Postgres; never mock the store.
- **Issue-driven.** No work without a GitHub issue. Epics group tasks.
- **ADRs for non-obvious decisions.** Stored in [docs/adr/](docs/adr/).
- **LLDs per task.** `docs/design/lld-<epic-slug>-<task-slug>.md`.
- **Small PRs.** One logical change per PR.

## Verification (script contract)

Skills and agents invoke these scripts. Each project provides its own implementation.

| Script | Purpose |
|---|---|
| `./scripts/run-tests.sh` | Run unit tests; optional file path arg |
| `./scripts/run-typecheck.sh` | Type check (`mypy --strict`) |
| `./scripts/run-lint.sh` | Lint (`ruff check`) |
| `./scripts/run-build.sh` | Build (N/A — `exec true`) |
| `./scripts/run-markdown-lint.sh` | Markdown lint |
| `./scripts/run-format-check.sh` | Format check (`ruff format --check`) |
| `./scripts/run-e2e.sh` | E2E (N/A — `exec true`) |

## Operational commands

```bash
uv sync --extra dev              # Install / sync deps
uv run recall serve              # Run server locally
uv run recall db migrate         # Database migrations
```

## Repository layout

```
src/recall/            # Application code
src/recall/migrations/ # SQL migration files (ADR-0013)
tests/                 # pytest tests; integration marked @pytest.mark.integration
docs/                  # ADRs, design, plans, requirements, references
scripts/               # Operational + helper scripts
.claude/               # Skills, agents, commands, hooks, settings
```

## Things to never do

- **Never mock the database in tests.** Real Postgres via testcontainers only.
- **Never bypass `ruff` / `mypy` / pre-commit hooks** with `--no-verify`.
- **Never add a new MCP tool** without updating the tool table in requirements and respecting the ≤ 6 budget.
- **Never store project-specific state as `scope=global`.**
- **Never widen the storage namespace** beyond `(scope, project_id)` without an ADR.

## Local references

Read these before touching storage or memory-tool wiring:

- [langmem-notes.md](docs/reference/langmem-notes.md) — LangMem tools, namespace templating, store wiring.
- [asyncpostgresstore-notes.md](docs/reference/asyncpostgresstore-notes.md) — schema DDL, API, filter operators, gotchas.
- [docs/adr/](docs/adr/) — All architectural decisions (ADR-0001 through ADR-0014).

## Knowledge base (kb/)

Project-specific conventions used by plugin skills and agents:

- [kb/architecture.md](kb/architecture.md) — Boundary rules, composition pattern
- [kb/file-map.md](kb/file-map.md) — Concept → path mapping
- [kb/conventions.md](kb/conventions.md) — Test naming and file conventions
- [kb/anti-patterns.md](kb/anti-patterns.md) — Project-specific anti-pattern checklist

## Process

Pipeline: `requirements → /kickoff → /architect → /feature → /feature-end → /retro`. Full details in [engineering-process.md](docs/process/engineering-process.md).

## Task tracking

GitHub Issues + Project #3. Labels: `epic`, `phase-0`–`phase-5`, `area:*`, `kind:task`. Manage via `./scripts/gh-project-status.sh`.
