# 0012. Test strategy: integration tests against real Postgres via testcontainers, no DB mocks

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

Recall's correctness story rests almost entirely on the Storage Adapter and the Memory Service behaving correctly under real Postgres + pgvector semantics. The interesting failure modes — namespace mis-binding, the ADR-0001 flat-value-schema constraint, the ADR-0004 filter limitations, the S1.7 CHECK constraint, vector dimension mismatches, migration drift — are all things a mock will happily lie about.

LangMem v1 had a partially-mocked store and the result was predictable: tests passed locally, schema changes broke prod, and "the test suite is green" stopped meaning anything. CLAUDE.md already lists "never mock the database in tests" as a rule. Promoting that rule to an ADR is not redundant — it makes the rule citable in PR review even if CLAUDE.md is later edited, and it puts the *reason* on record so a future contributor cannot quietly relitigate it as "modernisation".

S6.1 mandates "every MCP tool has integration tests against a real Postgres (testcontainers), not mocks". S6.2 lists the cases that must be covered. S6.6 requires CI to run lint + tests on every PR. The HLD's component decomposition assumes this — there is no "test double store" component, and there isn't going to be one.

## Decision

Recall's test strategy has two tiers, and exactly two:

**Unit tests.** Pure functions only — ranking math (ADR-0010), value-serialisation helpers, env-var parsing, the S1.8 decision-rule prose (as a fixture, not a class), the Project Registry's name-validation predicate. No I/O. No fakes for I/O. If a function takes a store or a connection, it is not a unit-test target — it is an integration-test target. Marked with the default pytest marker (no marker), runnable as `uv run pytest -m "not integration"`.

**Integration tests.** Spin a real Postgres+pgvector container via `testcontainers-python` per test session (or per test where isolation matters more than speed). Run migrations against it. Exercise the full Storage Adapter, Memory Service, Tool Router, and Transport against that container. Marked `@pytest.mark.integration`, runnable as `uv run pytest -m integration`.

The integration tier **must** cover, at minimum:

- save → search round-trip across both project and global scopes
- the S1.7 CHECK constraint rejects illegal `(scope, project_id)` combinations
- the ADR-0004 filter operators behave as documented (positive *and* negative cases)
- project isolation: a memory in project A is invisible to a search in project B
- auth rejection: the Transport refuses requests without a resolvable `user_id`
- update with metadata-only does not re-embed; update with content does
- the search ranking rule from ADR-0010: a strong global hit outranks a weak project hit, and ties go to project
- migration apply against an empty database brings the schema to the current version

**Mocking is permitted only at hard external boundaries** that are not Postgres: the embeddings provider HTTP endpoint (mocked with a stub server, not a Python double — see below), the compaction LLM, and outbound HTTP in general. The rule of thumb: **never mock anything Recall owns; mock only what Recall calls over a network it does not control.**

For embeddings in integration tests, the default is a **deterministic in-process stub provider** that returns reproducible vectors derived from the input text (e.g. a hash-to-vector function). This keeps tests fast, offline, and reproducible without re-engaging the real model. The real `sentence-transformers` and OpenAI providers each get their own *contract* test that runs against the real thing and is gated to nightly CI, not the per-PR run.

CI runs `uv run ruff check .`, `uv run mypy`, `uv run pytest` on every PR. The "everything" pytest run includes integration tests; CI must therefore have Docker available. There is no "fast lane" that skips integration.

## Consequences

**Positive.**
- The test suite is allowed to mean what it says. If green, the schema applies, the namespace invariants hold, the filters work, and the auth boundary is enforced — because all of those were exercised against real Postgres.
- Schema migrations (ADR-0013, forthcoming) are exercised on every PR. Drift is impossible to merge accidentally.
- The temptation to introduce a "fast in-memory store double" is closed off by ADR, not by vibe.
- Onboarding contributors only need Docker. No extra services to mock or stub.

**Negative / accepted trade-offs.**
- **CI runs Docker.** Slower than a pure-Python test suite; needs a runner image with Docker available. Acceptable — we are buying truthfulness with seconds.
- **Per-test container is slow** if used naively. Mitigated by sharing one container across the session and isolating tests via per-test schemas or transactional rollbacks. The LLD picks the exact strategy.
- **Real provider contract tests are nightly, not per-PR.** A real-model regression can land in main and be caught hours later, not minutes. Accepted: per-PR runs would couple every PR to OpenAI uptime.
- **Local test runs require Docker too.** Documented in `CLAUDE.md` and the README.

**Not chosen, and why.**
- **In-memory fake of the store.** The exact failure mode that motivated this ADR. Hard no.
- **SQLite as a stand-in.** No pgvector, no Postgres-specific JSONB semantics, no realistic `vector(N)` validation. Lies in a different costume.
- **Separate "unit-only" CI pipeline that runs on every PR, with integration on merge.** Re-creates the LangMem v1 failure mode by letting unit-only PRs land green.
- **Mocking the embeddings provider with a `MagicMock`.** Tests that pass while saying nothing. The deterministic stub provider is the supported pattern.

## References

- REQUIREMENTS.md — S6.1, S6.2, S6.6
- CLAUDE.md — "Things to never do" rule on database mocking, now ADR-backed
- docs/design/v1-design.md — Storage Adapter, Memory Service, Embedder
- ADR-0001 (flat value schema), ADR-0002 (namespace shape), ADR-0004 (filter limitations) — all enforced by the integration tier
