# Session — /architect Phase 4 (E4 real deployment)

## Summary

The user asked whether the April Phase 4 plan was still valid before designing it. It was not:
it missed startup configuration (Story 6.4), the real dimension check, Compose auth and allowed
hosts, and named `asyncpg` where the store uses `psycopg`. After three gate decisions (both
providers, recreate the database on a provider change, `EMBEDDINGS_*` names) the plan, the
requirements (v0.6) and ADR-0008/0011 were revised, one LLD covering six tasks was written and
reviewed, and epic REC-14 with tasks REC-15 to REC-20 was created in Jira.

## Shipped

| Commit | Scope |
|--------|-------|
| 482cd8e | ADR-0008 amendment 1 (sync interface, retry seam, `stub`, recreate DB); ADR-0011 amendment 1 (psycopg) |
| 81b359d | Plan Phase 4 rewritten; requirements v0.6 (Stories 6.1, 6.3, 6.4, 6.5) |
| a7706bf | Story 6.3 AC: model loads before listening; ADR-0011 openai-v2 embedding spans |
| d046f51 | `lld-e4-deployment.md`, `coverage-e4.yaml` |
| 69fdf50 | LLD review follow-ups |
| 79f9b94 | Task issues backfilled into LLD and manifest |

## Board state

- Epic REC-14 `epic: E4 — Real deployment` (phase-4), body carries the dependency graph and waves.
- Tasks: REC-15 settings, REC-16 OpenAI-compatible provider, REC-17 sentence-transformers,
  REC-18 dimension check, REC-19 Compose and docs, REC-20 OTEL. All Todo.
- Waves: REC-15 → REC-16 + REC-18 → REC-17 → REC-19 + REC-20.
- REC-1 (empty placeholder) still open; not touched.

## Cross-cutting decisions

- `EMBEDDINGS_DIM` is required for every provider (no silent 1536 default).
- The in-process model loads before uvicorn listens; failure or mismatch exits 1. No background
  loading state.
- Retry once in `guarded_embed`; the OpenAI SDK's own retries (default 2) are turned off.
- Compose defaults `RECALL_ALLOWED_HOSTS=localhost,127.0.0.1` because it ships a committed
  development token (DNS-rebinding guard).
- Only `cli.main` reads `os.environ`.

## What didn't go to plan

- The first gate proposal checked API shapes against the local venv. The user rejected that:
  "do not rely on what is installed… we need more recent ones". Re-checked against the latest
  PyPI wheels; this surfaced `openai` 3.60 `DEFAULT_MAX_RETRIES = 2`, `httpx2`,
  sentence-transformers' renamed `get_embedding_dimension()`, and that openai-v2 instrumentation
  wraps the SDK method (so embedding spans are possible after all).
- The Story 6.3 AC was written as "503 while loading", then reversed to a synchronous load once
  the dimension check made background loading costly.
- LLD review found 5 blockers: Compose DNS rebinding, CLI flag defaults parsing `RECALL_PORT`
  before settings, `Resource.create` overriding `OTEL_SERVICE_NAME`, missing test files in Task 1,
  and an I1 grep that the design itself failed. All fixed; re-review confirmed.
- `tag-session.py` reported a session-ID mismatch and wrote the Prometheus file under
  feature-comprehension-score's monitoring directory, so this session's cost may be misattributed.

## Process notes for `/retro`

- The architect skill's vendor-shape step should say "latest published release, not the local
  install" explicitly.
- Task sizes above 200 lines (REC-15 ~250, REC-16 ~220, REC-19 ~230) were accepted without
  splitting; check actual PR sizes against these estimates.
- `kb/architecture.md` and `kb/file-map.md` still describe a `src/recall/migrations/` directory
  that does not exist; REC-15 corrects it.

## Skill self-reflection

- Got right: reading the code before sizing caught the plan's stale assumptions; the review agent
  caught real defects (the OTEL resource precedence would have shipped broken).
- Struggled: `/lld` assumes `docs/design/v<N>/v<N>-design.md`; this repo's HLD is
  `docs/design/v2-design.md`, which had to be used by precedent. Running `tracker.py` from a
  worktree fails because `.env` is gitignored; it had to run from the main checkout.
- Suggestion: `/architect` Step 1a should symlink `.env` into the docs worktree (as
  `/feature-team` does for feature worktrees) so tracker calls work there.

## Next step

Human reviews this docs PR and merges it, then `/edf:feature-team epic REC-14`.
