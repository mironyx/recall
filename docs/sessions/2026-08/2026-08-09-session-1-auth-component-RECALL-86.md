# Session log — RECALL-86

## Approach rationale
- **Issue:** #86
- **Approach chosen:** Follow the LLD §E1.1 contract exactly — frozen `AuthConfig` dataclass, `load_auth_config(auth_file_path)` pure loader, `authenticate(auth_config, authorization_header)` pure function; `UnauthenticatedError` with `{error, hint}` shape in shared `errors.py`.
- **LLD deviations:** none
- **Pressure:** standard — ~75 src lines across 2 source files (errors.py ~20, auth.py ~55), 1 test file.

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c   | 2026-08-09T13:04:00Z | $0.0000 | 0/0/0/0 | pressure: standard |
| 4bF  | 2026-08-09T13:06:00Z | $0.0000 | 0/0/0/0 | test-author complete (25 tests, 14 properties) |
| 4dF  | 2026-08-09T13:08:00Z | $0.0000 | 0/0/0/0 | implementation complete — 25/25 tests pass |
| 5    | 2026-08-09T13:12:00Z | $0.0000 | 0/0/0/0 | 94/95 pass; 1 pre-existing smoke-test failure on main (E0.5 pg_conn teardown ordering) — reproduced on clean main; mypy/ruff clean |
| 6    | 2026-08-09T13:15:00Z | $0.0000 | 0/0/0/0 | diag pass — CodeScene 10.0×3; SonarQube N/A (project not analyzed); no .diagnostics in worktree |
| 6b   | 2026-08-09T13:20:00Z | $0.0000 | 0/0/0/0 | evaluator: FAIL → fixed (user_id str check); 3 adversarial tests added, 28/28 now pass |
| 5r   | 2026-08-09T13:22:00Z | $0.0000 | 0/0/0/0 | re-run after evaluator fix: 97/98 (1 pre-existing smoke fail), mypy/ruff clean, CodeScene 10.0 |
| 8    | 2026-08-09T13:26:00Z | $0.0000 | 0/0/0/0 | [PR #112](https://github.com/mironyx/recall/pull/112) — body patched with pre-existing failure notes |
| 9    | 2026-08-09T13:35:00Z | $0.0000 | 0/0/0/0 | review clean after 3 rounds — 6 findings fixed, 1 N/A (Co-Authored-By), 31/31 tests |
| 10   | 2026-08-09T13:42:00Z | $0.0000 | 0/0/0/0 | report done — CI fail solely on pre-existing markdownlint (MD033/MD028 in v2 design docs); session-log MD058 fixed |

## Work completed

Implemented E1.1 (issue #86) — bearer token authentication component, merged as [PR #112](https://github.com/mironyx/recall/pull/112):

- `src/recall/auth.py` — frozen `AuthConfig` dataclass, `load_auth_config(path)` loader, `authenticate(config, header)` pure function (ADR-0007, LLD §E1.1).
- `src/recall/errors.py` — `RecallError` base with `{error, hint}` envelope; `UnauthenticatedError` (LLD §E1-errors).
- `tests/test_auth.py` — 31 unit tests covering all 5 acceptance criteria (env-var file loading, token resolution, rejection paths, purity, error shape).
- Session log with full cost checkpoint table (Steps 3c–10).

## Decisions made

- **Loader takes an explicit path** (per LLD §E1.1) — `RECALL_AUTH_FILE` env-var wiring deferred to E1.6 (issue #91), tracked via `TODO(#91)` in `load_auth_config` docstring.
- **RFC 7235 §2.1 case-insensitive scheme matching** — auth-scheme tokens are case-insensitive; review-driven (PR #112 review round 1).
- **Strict shape validation** — non-string `user_id` values raise `ValueError`; evaluator-driven (would otherwise corrupt the `-> str` contract).
- **Token redaction** — loader error messages never embed token values (live credentials per ADR-0007).
- Zero design deviations from LLD.

## Review feedback addressed

3 review rounds, all findings fixed:
- **Round 1** (1 block + 5 warns): `Co-Authored-By` trailer treated as block — N/A (project has no such rule; harness-required, matches main history). Fixed: case-insensitive Bearer scheme, token redaction, `TODO(#91)` for env wiring, amended docs commit with issue ref, stale test docstring.
- **Round 2** (2 warns): added `test_bearer_scheme_is_case_insensitive` regression test (proven to fail on pre-fix code); added `from __future__ import annotations` to errors.py.
- **Round 3**: clean — 31/31 tests, no new issues. Design conformance: zero findings.

## LLD Sync report

## LLD Sync — Issue #86: E1.1 Auth component — token-file loader, authenticate()

### Corrections (spec was wrong)
- None — the LLD §E1.1 / §E1-errors spec was accurate. All five symbols
  (AuthConfig, load_auth_config, authenticate, RecallError, UnauthenticatedError)
  were built with exact signatures and the {error, hint} envelope as specified.

### Additions (not in spec)
- Case-insensitive Bearer scheme match (RFC 7235 §2.1): the LLD did not state
  how the auth-scheme token is compared; implementation (and a regression test)
  match the scheme case-insensitively.
- user_id string validation in load_auth_config: the LLD specified ValueError
  on "wrong shape" generally; implementation additionally rejects non-string
  user_id values, protecting authenticate()'s documented -> str contract.
  Loader error messages never embed token values (live credentials, ADR-0007).
- RECALL_AUTH_FILE wiring: the LLD says the file is "read once at startup";
  implementation makes the loader take an explicit path and defers the env-var
  read to E1.6 (issue #91, TODO in load_auth_config docstring).
- errors.py ships with `from __future__ import annotations`.

### Omissions (in spec but not built)
- None.

### Confirmations (notable)
- AuthConfig is a frozen dataclass with token_map: dict[str, str] — exactly as
  specified; authenticate() is a pure function (no I/O, no DB); UnauthenticatedError
  carries error="unauthenticated" and the exact hint string from the spec.

### LLD updated
File: docs/design/v2/lld-e1-one-memory-e2e.md §E1.1 (LLD-e1-auth), §E1-errors (LLD-e1-errors)
Document Control: added "Revised" row (2026-08-09, issue #86)
kb: no changes (kb/architecture.md has no per-module helper catalogue; auth is
    already anticipated by the API composition pattern section)
Coverage manifest: no changes (no corrections to flip, no new sections, no Rev N blocks)

## Cost retrospective

Final feature cost (Prometheus, stage=final, applied to issue #86 and PR #112):
**$13.5448** — 415,326 input / 153,794 output / 15,246,720 cache-read tokens.
(Checkpoints recorded during the run showed unavailable / $0.0000; the final
query recovered the true figures after the session-continuation tag.)
Checkpoint table analysis (step gaps):
- **3c → 5 (implementation friction):** moderate — one pre-existing smoke-test
  failure on the full suite (E0.5 fixture ordering, reproduced on clean main);
  implementation itself green on first full-suite run.
- **5 → 8 (quality gate overhead):** one evaluator FAIL (non-string user_id
  accepted) → single-line fix + 3 adversarial tests; diag clean on first pass.
- **8 → 9 (post-PR rework):** 3 review rounds, 6 findings fixed, 1 N/A — small
  diff, so rounds were cheap; main token spend was review-agent re-launches.
- **Improvement actions:** (1) add "user_id must be string" to contract
  properties checklist — the evaluator caught what test-author missed;
  (2) RFC 7235 scheme case-insensitivity is a recurring pattern — put it in
  the auth contract checklist for E1.6 (tool router) and future auth work.

## Next steps

- E1.2 (issue #87) is in progress — validation.py will add ValidationError to
  errors.py, extending the module the LLD already sketches.
- E1.6 (issue #91) wires `RECALL_AUTH_FILE` at server startup (TODO in auth.py).
- Lead: coordinate the pre-existing CI blockers on main — markdownlint
  MD033/MD028 in docs/design/v2/ (blocks every E1 PR's lint job) and the
  smoke-test fixture-ordering failure (blocks full-suite runs).
