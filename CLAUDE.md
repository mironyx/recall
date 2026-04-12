# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Recall — Focused MCP Memory Server

A small, focused MCP server that gives coding agents persistent memory across sessions, machines, and projects. Successor to LangMem v1, deliberately rebuilt to be smaller, simpler, and agent-first.

**Current phase:** Phase 0 — Foundation (scaffolding, CI, container, real-Postgres test fixture). See [docs/plans/2026-04-12-v2-implementation-plan.md](docs/plans/2026-04-12-v2-implementation-plan.md) for the full phasing and [docs/design/v2-design.md](docs/design/v2-design.md) for the HLD.

**The full product spec lives in [docs/requirements/v2-requirements.md](docs/requirements/v2-requirements.md). Read it before starting any non-trivial change.**

## Tech stack

- **Language:** Python 3.12+
- **Package manager:** `uv`
- **Lint / format:** `ruff` (lint + format in one tool)
- **Type checker:** `mypy --strict`
- **Tests:** `pytest` + `pytest-asyncio`; integration tests use `testcontainers` against real Postgres
- **Storage:** Postgres + `pgvector`, accessed via LangGraph `AsyncPostgresStore`
- **Embeddings:** Dual provider — sentence-transformers (in-process) or OpenAI-compatible HTTP (ADR-0008)
- **MCP transport:** Streamable HTTP (no SSE shim)
- **Deployment:** single container

## Design principles (from REQUIREMENTS.md)

1. **Few tools, broad tools.** ≤ 6 MCP tools total (5 in v2). Tool design is prompt design — the agent is the user.
2. **Two scopes: project and global.** A memory is bound to a `project_id` or marked `scope=global`. Storage namespace is `(scope, project_id)` (ADR-0002).
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
src/recall/           # Application code (package)
src/recall/migrations/ # Numbered SQL migration files (ADR-0013)
tests/                # pytest tests; integration tests marked with @pytest.mark.integration
scripts/              # Operational + Claude-Code helper scripts
docs/                 # ADRs, design, plans, requirements, references
.claude/              # Skills, agents, commands, hooks, settings
```

## Things to never do

- **Never mock the database in tests.** Integration tests must hit a real Postgres via testcontainers. The whole point is catching schema/migration drift.
- **Never bypass `ruff` / `mypy` / pre-commit hooks** with `--no-verify`. If a check fails, fix the underlying issue.
- **Never add a new MCP tool without updating the tool reference table in v2-requirements.md** and getting agreement that the tool budget (≤ 6) is still respected.
- **Never store project-specific state in `scope=global` memories.** The scope decision rule: "if this fact would still be true and useful in a brand-new empty repo tomorrow, save it as global; otherwise project."
- **Never widen the storage namespace** beyond `(scope, project_id)` without an ADR.

## Local references

Upstream docs and source for the two libraries we build on are distilled locally — read these before touching storage or memory-tool wiring, and prefer them over re-fetching upstream:

- [docs/reference/langmem-notes.md](docs/reference/langmem-notes.md) — LangMem tools, namespace templating, store wiring.
- [docs/reference/asyncpostgresstore-notes.md](docs/reference/asyncpostgresstore-notes.md) — schema DDL, API signatures, filter operators, the two gotchas (top-level-only keys, lexicographic numeric comparison), TTL, migrations.

Key architectural decisions live in [docs/adr/](docs/adr/) — 0001 (flat value schema), 0002 (namespace shape), 0003 (no TTL in v1), 0004 (filter limitations & ISO-string dates), 0005 (project bootstrap pipeline), 0006 (Streamable HTTP sole transport), 0007 (shared bearer-token auth, OIDC/mTLS deferred), 0008 (embeddings provider abstraction), 0009 (project registry table), 0010 (search ranking: union with project boost), 0011 (observability: structlog + OTEL auto-instrumentation only), 0012 (test strategy: real Postgres via testcontainers, no mocks), 0013 (in-app DDL migrations, no Alembic).

## Engineering Process

Pipeline: `requirements → /kickoff → /architect → /feature → /feature-end → /retro`.
For the full lifecycle, stages, human gates, artefact map, skills index, and ADR index, see [docs/process/engineering-process.md](docs/process/engineering-process.md). Rationale for the bootstrap shape lives in [ADR-0005](docs/adr/0005-project-bootstrap-pipeline.md).

### Custom skills

- `/kickoff` — Bootstrap a new project (or major version) from `REQUIREMENTS.md`. Produces the HLD (Levels 1–3), load-bearing ADRs, and the implementation plan, with human gates after each. Use once per project/version before `/architect`. See [ADR-0005](docs/adr/0005-project-bootstrap-pipeline.md).
- `/architect` — Read a plan and produce all design artefacts in one pass (ADRs, LLDs, design doc updates, enriched issue bodies). Stops for human review before implementation.
- `/feature` — Autonomous implementation cycle: picks top Todo item (or specified issue), creates branch, TDD implementation, `/diag`, commit, PR, `/pr-review-v2`. Stops after review for human approval.
- `/feature-end` — Post-review wrap-up: writes session log, commits remaining changes, merges PR (with approval), switches to parent branch, cleans up local branch, updates project board.
- `/drift-scan`, `/retro` — Periodic maintenance sweeps across requirements, design and code.

## Custom Skills

- `/discovery` — Explore a problem space from a freeform idea using adapted Lean Inception. Produces a structured discovery document (vision, boundaries, personas, journeys, features, MVP sequencing). Use before `/requirements` when starting a new project or major version.
- `/requirements` — Transform discovery output or a freeform brief into a structured requirements document with epics, prioritised user stories, and testable acceptance criteria. Use after `/discovery` (or standalone) and before `/kickoff`.
- `/kickoff` — Bootstrap a new project from a requirements document. Produces the HLD (Levels 1–3), load-bearing ADRs, and the implementation plan, with human gates after each. Use once per project/version before `/architect`.
- `/architect` — Read a plan and produce all design artefacts in one pass (ADRs, LLDs, design doc updates, enriched issue bodies). Stops for human review before implementation.
- `/feature` — Autonomous implementation cycle: picks top Todo item (or specified issue), creates branch, TDD implementation, `/diag`, commit, PR, `/pr-review-v2`. Stops after review for human approval.
- `/feature-end` — Post-review wrap-up: writes session log, commits remaining changes, merges PR (with approval), switches to parent branch, cleans up.
- `/feature-team` — Parallel implementation using Claude Code agent teams (CLI only). Each teammate autonomously implements one issue in its own worktree.
- `/create-adr` — Create Architecture Decision Records for significant technical decisions.
- `/create-plan` — Create detailed implementation plans for features or work phases.
- `/lld` — Generate Low-Level Design documents for a phase or section. Produces LLDs with implementation detail, file paths, types, and task breakdowns.
- `/lld-sync` — Sync the LLD back to the implementation after a feature is complete. Compares spec vs what was built, updates the LLD in-place.
- `/diag` — Batch check diagnostics-exporter output for changed files. Detects, fixes, and verifies resolution.
- `/pr-review-v2` — Review a PR for bugs, CLAUDE.md compliance, design contract adherence, and best practices. Usage: `/pr-review-v2 <pr-number>` or `/pr-review-v2` (local diff).
- `/drift-scan` — Run garbage collection scan for drift between requirements, design artefacts, and implemented code.
- `/retro` — Run a process retrospective: review sessions, assess process health, produce improvement actions.

## Task tracking

GitHub Issues are the source of truth. The board (GitHub Project #3) is set up with epics for all phases and task issues for Phase 0. Labels: `epic`, `phase-0` through `phase-5`, `area:*`, `kind:scaffold`. Use `./scripts/gh-project-status.sh` to manage board state.
