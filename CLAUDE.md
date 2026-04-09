# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Recall — Focused MCP Memory Server

A small, focused MCP server that gives coding agents persistent memory across sessions, machines, and projects. Successor to LangMem v1, deliberately rebuilt to be smaller, simpler, and agent-first.

**The full product spec lives in [REQUIREMENTS.md](REQUIREMENTS.md). Read it before starting any non-trivial change.**

## Tech stack

- **Language:** Python 3.12+
- **Package manager:** `uv`
- **Lint / format:** `ruff` (lint + format in one tool)
- **Type checker:** `mypy --strict`
- **Tests:** `pytest` + `pytest-asyncio`; integration tests use `testcontainers` against real Postgres
- **Storage:** Postgres + `pgvector`, accessed via LangGraph `AsyncPostgresStore`
- **Embeddings:** OpenAI (or any OpenAI-compatible endpoint)
- **MCP transport:** Streamable HTTP (no SSE shim)
- **Deployment:** single container

## Design principles (from REQUIREMENTS.md)

1. **Few tools, broad tools.** ≤ 6 MCP tools total. Tool design is prompt design — the agent is the user.
2. **Two scopes: project and global.** A memory is bound to a `project_id` or marked `scope=global`. Storage namespace is `(scope, project_id)`. See REQUIREMENTS.md S1.7 / S3.7 for the invariant.
3. **Categories are data, not classes.** A memory has a `kind` field; adding a kind is a config change, not a new class.
4. **One server, one transport, one entrypoint.** No parallel implementations.
5. **Boring storage.** No bespoke abstractions on top of `AsyncPostgresStore` until proven necessary.

## Engineering practice (carried over from feature-comprehension-score)

This repo follows the same delivery framework as our sibling project. The framework — not the domain — is what's being reused.

- **TDD-first.** Write the failing test before the implementation. Integration tests hit a real Postgres (testcontainers); never mock the store.
- **Issue-driven work.** No work without a GitHub issue. Epics group tasks; tasks live as separate issues. See the `/feature` skill in `.claude/skills/`.
- **Specialised role agents.** Tester → Developer → Reviewer flow via the agents in `.claude/agents/`.
- **ADRs for non-obvious decisions.** Use the `/create-adr` skill. Store in `docs/adr/`.
- **LLDs per task.** `docs/design/lld-<epic-slug>-<task-slug>.md`. Use the `/lld` skill.
- **Small PRs.** One logical change per PR. Don't bundle refactors with features.
- **Commit messages explain *why*.** The diff already shows what.

## Common commands

```bash
# Install / sync deps (creates .venv)
uv sync --extra dev

# Run the server locally
uv run recall serve

# Lint & format
uv run ruff check .
uv run ruff format .

# Type-check
uv run mypy

# Tests
uv run pytest                          # everything
uv run pytest -m "not integration"     # unit only
uv run pytest -m integration           # integration only

# Database migrations
uv run recall db migrate
```

## Repository layout

```
src/recall/        # Application code (package)
tests/             # pytest tests; integration tests marked with @pytest.mark.integration
scripts/           # Operational + Claude-Code helper scripts
docs/              # ADRs, LLDs, runbooks (created as needed)
.claude/           # Skills, agents, commands, hooks, settings
REQUIREMENTS.md    # Product spec — source of truth for what we're building
```

## Things to never do

- **Never mock the database in tests.** Integration tests must hit a real Postgres via testcontainers. The whole point is catching schema/migration drift.
- **Never bypass `ruff` / `mypy` / pre-commit hooks** with `--no-verify`. If a check fails, fix the underlying issue.
- **Never add a new MCP tool without updating REQUIREMENTS.md E2** and getting agreement that the tool budget (≤ 6) is still respected.
- **Never store project-specific state in `scope=global` memories.** See REQUIREMENTS.md S1.8 for the decision rule.
- **Never widen the storage namespace** beyond `(scope, project_id)` without an ADR.

## Local references

Upstream docs and source for the two libraries we build on are distilled locally — read these before touching storage or memory-tool wiring, and prefer them over re-fetching upstream:

- [docs/reference/langmem-notes.md](docs/reference/langmem-notes.md) — LangMem tools, namespace templating, store wiring.
- [docs/reference/asyncpostgresstore-notes.md](docs/reference/asyncpostgresstore-notes.md) — schema DDL, API signatures, filter operators, the two gotchas (top-level-only keys, lexicographic numeric comparison), TTL, migrations.

Key architectural decisions live in [docs/adr/](docs/adr/) — 0001 (flat value schema), 0002 (namespace shape), 0003 (no TTL in v1), 0004 (filter limitations & ISO-string dates).

## Task tracking

GitHub Issues are the source of truth. The board, labels, and milestone conventions will be set up when the first epic lands. Until then, REQUIREMENTS.md drives the work.
