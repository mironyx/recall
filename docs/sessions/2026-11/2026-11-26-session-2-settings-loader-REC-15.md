# Session log — REC-15

## Approach rationale

- **Issue:** REC-15
- **Approach chosen:** One pure `settings.py` loader over a mapping (LLD §4.1); `cli.main` passes
  `os.environ` once; `create_app`, `ensure_schema` and `configure_telemetry` receive values.
- **LLD deviations:** `load_db_settings` requires only `DATABASE_URL` and `EMBEDDINGS_DIM` but also
  rejects any other settings variable that is set and invalid (issue AC: reported for `db migrate`
  too); `configure_telemetry(env)` changes here, not in §4.6, because I1 needs it.
- **Pressure:** heavy — ~250 src lines across 6 source files (settings, cli, server, schema,
  telemetry, provider comment); not split (LLD OQ1).

## Cost checkpoints

| Step | Timestamp | Cost (cumulative) | Tokens (cumulative) | Note |
|------|-----------|--------------------|----------------------|------|
| 3c | 2026-11-26T15:03:53Z | $0.75 | 2,689 in / 5,124 out | pressure: heavy — ~250 src lines, 6 src files [models: claude-sonnet-5-5 $0.75, claude-haiku-5-5 $0.00] |
| 4bF | 2026-11-26T15:09:46Z | $1.81 | 7,280 in / 53,724 out | test-author complete — 23 BDD properties, all covered — brief: used as-is [models: claude-sonnet-5-5 $1.81, claude-haiku-5-5 $0.00] |
| 4dF | 2026-11-26T15:09:46Z | $1.81 | 7,280 in / 53,724 out | implementation complete — second challenge pass: 1 addition (DSN parse check), 0 deferred [models: claude-sonnet-5-5 $1.81, claude-haiku-5-5 $0.00] |
| 5 | 2026-11-26T15:11:50Z | $2.11 | 8,850 in / 58,999 out | green on attempt 2 (590/590; mypy run directly, no pyright); audit: no known vulnerabilities; e2e: skip — no E2E tests (e2e-dir unset or empty) [models: claude-sonnet-5-5 $2.10, claude-haiku-5-5 $0.00] |
| 6 | 2026-11-26T15:14:23Z | $2.61 | 9,604 in / 68,431 out | diag pass — CodeScene findings fixed in settings.py and test helper; remaining ones logged; SonarQube skipped (no analysis tool); 590/590 after fixes [models: claude-sonnet-5-5 $2.61, claude-haiku-5-5 $0.01] |
| 6b | 2026-11-26T15:43:46Z | $3.86 | 18,588 in / 100,847 out | evaluator: FAIL (search vars first-only and echoed; URL fragment leak) → fixed → recheck PASS WITH WARNINGS — brief: used as relayed by lead; recheck n/a [models: claude-sonnet-5-5 $3.85, claude-haiku-5-5 $0.01] |

## Concerns & Deferred Items

- Challenge pass: indexes, constraints, concurrency, pagination do not apply (config loading only).
- `docker-compose.yml` and README lack the newly required variables, so `docker compose up` exits 1
  until REC-19 (LLD Task 5 owns both files); not edited here.
- `server._build_store` wires the stub for every provider until REC-16/REC-17; added a
  `embeddings_provider_not_wired` warning so a configured `openai` is not silently stubbed.
- Added beyond the LLD: an unparseable `DATABASE_URL` is a `SettingsError` entry (libpq's own
  error quotes the string, breaking I2); `RECALL_PORT` is bounded 1–65535; timeout must be
  positive and finite.
- EDF `run-typecheck.sh p` calls `pyright`, which this repo does not have; typecheck verified with
  the project's `uv run mypy` and `uv run mypy --strict src`.
- `tests/evaluation/test_e01_scaffolding_eval.py` (not in the LLD file list) needed a stub env:
  `serve --dry-run` no longer starts without configuration.
- Checkpoint rows 4bF and 4dF were appended together, after implementation.
- CodeScene findings left: `server._build_lifespan` argument count (9.68, function not changed;
  REC-16/19 edit the file); `test_settings.py` low cohesion (8.54); `test_schema.py` duplication
  (9.38) and `test_memory_service.py` cohesion/arguments (8.03) are in test bodies this issue only
  touched for imports and call signatures.
- SonarQube: skipped — the MCP exposes no analysis tool in this session.
- Evaluator FAIL (search variables: only the first named, value echoed) fixed in `settings._search`;
  `config.py` unchanged, LLD §4.1 reconciled.
- User decision: no output may reveal any part of `DATABASE_URL`. `describe_db_error`
  (`db/schema.py`) covers CLI and lifespan; `health.readyz` (not in the LLD file list) now reports
  only the exception type.
- Follow-ups, not fixed here: `config.py` accepts zero or negative search limits; `--port` skips
  the range check.
- Evaluator recheck PASS WITH WARNINGS: `describe_db_error` still quotes statement errors carrying
  a SQLSTATE (may name a role or database; not a connection error); `tool_router.py:104`
  tracebacks for runtime database failures are untested for URL parts. Neither changed.
