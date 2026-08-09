# Session log — E1-88

## Approach rationale
- **Issue:** #88
- **Approach chosen:** Sync `EmbeddingsProvider` ABC (`dim` property + `embed()` method) in
  `embeddings/provider.py`; `StubEmbeddingsProvider` inherits it unchanged in behaviour;
  pure `validate_dim(provider, configured_dim)` fail-fast check in `provider.py`.
- **LLD deviations:** The LLD specifies an **async** `embed()`. Reality: the only embed
  consumer in v1 (LangGraph `AsyncPostgresStore`) invokes the embed callable **synchronously**
  inside a thread-pool executor (`aput → run_in_executor → batch → embed_documents`); an
  async-only callable raises at runtime ("EmbeddingsLambda was initialized with an async
  function but no sync function" — verified in installed langgraph 1.1.9 source). A sync
  interface needs zero bridge code at every wiring point (conftest now, store wiring in E1.4).
  ADR-0008's interface sketch is sync-shaped (`embed(texts) -> list[Vector]`, no await) and
  its "don't block the event loop" intent is already guaranteed by langgraph's executor;
  E4's HTTP provider can use a sync client inside that thread without blocking the loop.
- **Pressure:** standard — ~35 new/modified src lines across 2 source files
  (`provider.py` new, `stub.py` small), 1 new test file.

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T13:05:00Z | $0.0000 | 0 in / 0 out | pressure: standard |
| 4bF  | 2026-08-09T12:10:22Z | $0.0000 | 0 in / 0 out | test-author complete (14 tests, 12 properties) |
| 4dF  | 2026-08-09T12:10:57Z | $0.0000 | 0 in / 0 out | implementation complete (17/17 target tests) |
| 5    | 2026-08-09T12:15:29Z | $0.0000 | 0 in / 0 out | green on attempt 3 (87/87; mypy+ruff clean) |
| 6    | 2026-08-09T12:16:04Z | $0.0000 | 0 in / 0 out | diag pass (CodeScene 10.0 x4; no SonarQube project; no editor diagnostics) |
| 6b   | 2026-08-09T12:19:08Z | $0.0000 | 0 in / 0 out | evaluator: PASS WITH WARNINGS (3 adversarial tests added) |
| 8    | 2026-08-09T12:19:46Z | $0.0000 | 0 in / 0 out | [PR #113](https://github.com/mironyx/recall/pull/113) |
| 9    | 2026-08-09T12:27:52Z | $0.0000 | 0 in / 0 out | review re-run: 1 block fixed (Justification), 2 warns tracked (TODO #89, lld-sync) |
| 10   | 2026-08-09T12:27:52Z | $0.0000 | 0 in / 0 out | report to lead; CI reconciled (pre-existing lint failures only) |

## Work completed

- Implemented Issue #88 — E1.3: Embedder interface + stub upgrade.
- **PR:** [mironyx/recall#113](https://github.com/mironyx/recall/pull/113) (branch `feat/embedder-interface`).
- New `src/recall/embeddings/provider.py` — `EmbeddingsProvider` ABC (abstract `dim` property + `embed()`), `validate_dim(provider, configured_dim)` fail-fast check.
- `src/recall/embeddings/stub.py` — now inherits the ABC; `dim` became a property; deterministic hashed vectors unchanged.
- Tests: `tests/test_embeddings.py` (14 unit tests), `tests/evaluation/test_e13_embedder_interface_eval.py` (3 adversarial cross-instance determinism tests), plus a fixture-ordering fix in `tests/test_smoke.py` (pre-existing failure on main: suite red before this PR).
- Total: 90 tests pass (87 suite + 3 eval); mypy --strict and ruff clean; CodeScene 10.0 on all changed files.

## Decisions made

- **Sync over async `embed()`** — see "LLD deviations" in Approach rationale. Locked by `test_embed_is_synchronous`; independently verified against installed langgraph 1.1.9 source during PR review.
- **`validate_dim` shipped in #88, wired in #89** — the mechanism is this issue's scope; the startup call site belongs to E1.4 store creation (`TODO(#89)` marker in provider.py). AC-5 ("dim mismatch fails fast at startup") is intentionally split across the two issues.
- **mypy-strict-driven shape** — abstract property overridden by an instance attribute fails mypy strict ("Property dim ... is read-only"), so the stub uses a `@property` backed by `_dim`.
- **Co-Authored-By trailer kept** despite the EDF review rule flagging it — mandated by the harness commit instructions; project CLAUDE.md does not prohibit it.
- **test_smoke.py fixture fix kept** — adjacent-code change, but the suite was already red on main (reproduced: 1 failed / 22 passed); Step 5 requires zero failures.

## Review feedback addressed

- **Block (design conformance):** `validate_dim` absent from the LLD's internal decomposition table with no justification → fixed by adding a `Justification:` comment referencing the BDD spec (commit `3e0b7db`); lld-sync folded the function into the decomposition table at feature-end.
- **Warn (justification):** `validate_dim` has zero production call sites → accepted and tracked via `TODO(#89)` (commit `ad6a3a1`).
- **Warn (design conformance):** sync deviation discoverable only outside the LLD → documented in PR body `## Design deviations` (the channel lld-sync reads) and reconciled into the LLD at feature-end.
- **Warn (compliance):** Co-Authored-By trailer → kept, harness-mandated (see Decisions made).
- **Docs nit:** session log said "langgraph 0.2.x"; corrected to 1.1.9.

## LLD Sync report

## LLD Sync — Issue #88: E1.3: Embedder interface + stub upgrade

### Corrections (spec was wrong)
- `embed()` was specified as **`async`**; built **synchronous** (`def embed(self, texts) -> list[list[float]]`). The only v1 consumer, LangGraph's `AsyncPostgresStore`, invokes the embed callable synchronously inside a thread-pool executor (`aput → run_in_executor → batch → embed_documents`); an async-only callable raises at runtime ("EmbeddingsLambda was initialized with an async function but no sync function" — verified in installed langgraph 1.1.9). ADR-0008's interface sketch is sync-shaped, and the executor already guarantees the event loop is not blocked — E4's HTTP provider can use a sync client inside that thread. The `Raises: EmbeddingError` clause was dropped: retry/error machinery is provider-level (E4), not interface-level.

### Additions (not in spec)
- `validate_dim(provider, configured_dim)` — pure fail-fast check for EMBEDDINGS_DIM vs provider dim, added as a public function in `provider.py`. The LLD's BDD spec `test_dim_mismatch_fails_fast` named the behaviour but no mechanism; the function carries a `Justification:` comment referencing that spec. Startup wiring is deferred to E1.4 (issue #89, `TODO(#89)` marker at the call site).
- `kb/architecture.md`: added the `EmbeddingsProvider` ABC + `validate_dim` to the reusable-artefact catalogue (embedder contract for stub now, HTTP provider in E4).

### Omissions (in spec but not built)
- Startup call of the fail-fast dim check — deferred → issue #89 (E1.4 store creation); the mechanism ships in #88, the call site in #89.

### Confirmations (notable)
- `dim` as an abstract **property** (not a method) — built exactly as specified.
- The E0.5 stub moved from a plain class to inheriting `EmbeddingsProvider` — built as specified.
- BDD specs `test_stub_deterministic` / `test_stub_correct_dim` built as specified.

### LLD updated
File: `docs/design/v2/lld-e1-one-memory-e2e.md` §LLD-e1-embedder, §LLD-e1-internal-decomposition, Document Control
Status: Approved → Revised (Last revised: 2026-08-09, issue #88)
Coverage manifest: `docs/design/v2/coverage-e1.yaml` — REQ-story-13 flipped Approved → Revised

## Cost retrospective

- **Data source:** Cost checkpoints table above (steps 3c → 4bF → 4dF → 5 → 6 → 6b → 8 → 9 → 10). Prometheus reports $0.0000 / 0 tokens for every row — no cost telemetry available in this environment, so the retrospective is qualitative.
- **Implementation friction (3c → 5):** green on attempt 3. Drivers: (1) pre-existing integration-test failure (`test_container_boots_and_schema_applies` — fixture ordering, schema not applied) reproduced on main before fixing; (2) mypy strict surprises — abstract-property override and `assert validate_dim(...) is None` on a None-returning function. Improvement: run the full suite on the target branch before writing any code; add "mypy strict on tests" to the test-author checklist.
- **Quality gate overhead (5 → 8):** low — diagnostics and evaluator each one pass; evaluator added 3 adversarial tests (cross-instance determinism) rather than finding defects.
- **Post-PR rework (8 → 9):** two extra commits — `TODO(#89)` wiring marker (review warn) and the `Justification:` comment (review block). Both were traceability-only; no behaviour changes. Improvement: anticipate the LLD-gap finding — the LLD named BDD behaviour without a mechanism, which guarantees a design-conformance finding for any new public function; the test-author/implementer prompt should flag new public functions not present in the LLD decomposition.
- **Cost:** final query `$0.0000` — no usable telemetry; recorded for completeness.

## Next steps

- E1.4 — Storage adapter (issue #89): wire `validate_dim` at store creation with `EMBEDDINGS_DIM` from env (resolves `TODO(#89)`); the embedder interface is ready for `PostgresIndexConfig(dims=..., embed=...)`.
- Follow-up suggested board item: `gh issue list --label kind:task --state open --limit 3`.
