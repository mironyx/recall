# 0005. Embedding provider and model configuration

**Date:** 2026-04-12
**Status:** Accepted
**Deciders:** LS, Claude

## Context

Recall generates a vector embedding for every memory's content so that
`memory_search` can rank results by semantic similarity. The embedding is
stored in the `store_vectors` table via `AsyncPostgresStore`'s index
configuration. The vector column type is `vector(dims)` — the dimension is
baked into the column at migration time and cannot be changed without
dropping and recreating the vector table.

Two decisions must be made before implementation:

1. **Which embedding provider and model to use by default.**
2. **How operators configure the provider, model, and dimensions.**

The operator (LS) already uses OpenRouter as an API gateway for LLM calls.
OpenRouter exposes an OpenAI-compatible API at
`https://openrouter.ai/api/v1`, meaning any code written against the OpenAI
embeddings endpoint works with OpenRouter by changing the base URL and API
key.

## Options Considered

### Provider default

1. **OpenAI direct** — simplest for users who already have an OpenAI key.
2. **OpenRouter as default** — the operator already uses it; one API key for
   both LLM and embedding calls; access to multiple models through one
   gateway.
3. **No default — require explicit configuration** — flexible but increases
   setup friction.

### Model default

1. **`text-embedding-3-small`** (1536 dims) — good quality, low cost, fast.
   The standard choice for most use cases.
2. **`text-embedding-3-large`** (3072 dims) — higher quality, 2× storage and
   compute cost. Overkill for short memory records.
3. **`text-embedding-ada-002`** (1536 dims) — legacy, no advantage over
   3-small.

## Decision

### Provider: OpenRouter by default, any OpenAI-compatible endpoint supported

- Default `OPENAI_BASE_URL` in Docker Compose and documentation:
  `https://openrouter.ai/api/v1`
- The Embedding Client uses the standard OpenAI Python SDK
  (`openai.AsyncOpenAI`), which works with any OpenAI-compatible endpoint.
- Operators who prefer direct OpenAI, Azure OpenAI, or a local endpoint
  (Ollama, vLLM) simply change `OPENAI_BASE_URL` and `OPENAI_API_KEY`.

Rationale: the operator already has an OpenRouter account. One API key is
simpler than two. OpenRouter's fallback routing adds resilience. The code
is identical regardless of provider — it's purely a configuration choice.

### Model: `text-embedding-3-small` (1536 dims)

- Default `RECALL_EMBEDDING_MODEL`: `text-embedding-3-small` (or
  `openai/text-embedding-3-small` if the provider requires a prefix).
- Default `RECALL_EMBEDDING_DIMS`: `1536`.
- Good enough for short text (memory records are typically 1–5 paragraphs).
  The quality difference vs. `text-embedding-3-large` is marginal for this
  content length, but the cost and storage difference is 2×.

### Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENAI_API_KEY` | Yes | — | API key for the embedding provider |
| `OPENAI_BASE_URL` | No | `https://openrouter.ai/api/v1` | Embedding API base URL |
| `RECALL_EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model name |
| `RECALL_EMBEDDING_DIMS` | No | `1536` | Embedding vector dimensions |

### Dimension immutability

The `dims` value is baked into the `store_vectors` table's `vector(dims)`
column type at migration time. **Changing the model to one with different
dimensions after data exists requires:**

1. Dropping the `store_vectors` table (losing all existing embeddings).
2. Re-running migrations with the new `RECALL_EMBEDDING_DIMS`.
3. Re-embedding all existing memories.

This is a destructive operation. The ADR documents it as a known constraint,
not a bug. The migration runner will validate that the configured `dims`
matches the existing column if vectors already exist, and refuse to start
with a mismatch (fail-fast, not silent corruption).

## Consequences

- One API key (`OPENAI_API_KEY`) serves both embedding and any future LLM
  needs (e.g., instruction compaction in v2.1) when using OpenRouter.
- The Embedding Client is a thin wrapper around `openai.AsyncOpenAI` — no
  custom HTTP code.
- Integration tests use a mock or a cheap model; they do not call OpenRouter
  in CI. The embedding dimension in test fixtures matches the configured
  default (1536).
- Docker Compose `.env.example` ships with `OPENAI_BASE_URL` pointing to
  OpenRouter and `RECALL_EMBEDDING_MODEL=text-embedding-3-small`.
- Switching providers is a config change, not a code change — no ADR needed.
- Switching to a model with different dimensions is a destructive migration —
  document in the operator runbook.
