# Anti-Patterns

## Mocking the database

**Never mock `AsyncPostgresStore` or any Postgres connection in tests.** All storage-touching tests must use real Postgres via testcontainers (ADR-0012). Mocking the store masks divergence between mock and real behavior.

## Bypassing quality gates

Never use `--no-verify`, `--no-gpg-sign`, or skip pre-commit hooks. `ruff`, `mypy --strict`, and format checks must pass before every commit.

## Scope smuggling

Never store project-specific data with `scope="global"`. Every write must use the correct `(scope, project_id)` tuple. The CHECK constraint on `store` enforces this at the DB level.

## Namespace creep

Never widen the storage namespace beyond `(scope, project_id)` without an ADR. The two-level namespace is a deliberate design choice (ADR-0002).

## Unbounded tool surface

Never add an MCP tool without updating the tool table in requirements and respecting the ≤ 6 tool budget. Each tool must be broad and composable, not a single-purpose endpoint.

## Premature abstraction

No abstraction layers on top of `AsyncPostgresStore`. The store is the storage API. No repositories, no DAOs, no query builders that wrap it.

## Speculative features

No features beyond what the issue or requirements ask for. No "we might need this later" code. No error handling for scenarios that cannot occur given the current implementation.

## Adjacent-code changes

Don't refactor, reformat, or "improve" code not directly related to the task. Don't remove pre-existing dead code unless asked. Every changed line must trace to the request.
