# 0008. Embeddings provider abstraction: in-process sentence-transformers + OpenAI-compatible HTTP

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

Embeddings are on the critical path of every save (S1.2) and every search (S1.3). The choice of provider is not neutral: it determines container size, cold-start time, network dependency, cost, and the dimensionality of the `vector(N)` column locked into the schema.

REQUIREMENTS.md (S5.1) names two providers as first-class:

- **`sentence-transformers`** running in-process — no network call, no API cost, but pulls a multi-hundred-megabyte model into the container and into resident memory.
- **`openai`** speaking to any OpenAI-compatible endpoint via `EMBEDDINGS_BASE_URL` — OpenAI proper, OpenRouter, vLLM, `text-embeddings-inference`, anything that honours the OpenAI embeddings API.

Both must coexist: the local-dev story benefits from in-process (no API key needed), and shared deployments will often want a hosted endpoint. The HLD's Embedder component depends on this abstraction without committing to either provider.

We need to record the abstraction shape and the provider semantics now, because:

1. The `EMBEDDINGS_DIM` startup check (S5.1) depends on a provider being able to declare its dimension.
2. The "single retry, structured error" rule (S6.5) lives at the abstraction boundary, not inside provider code.
3. Adding a third provider in the future (a sidecar `text-embeddings-inference` deployment, say) should not require rewriting the Embedder.

## Decision

Recall v1 ships **two embeddings providers behind one interface**, selected by the `EMBEDDINGS_PROVIDER` env var:

1. **`sentence-transformers`** — runs in-process. The model is loaded once at startup from `EMBEDDINGS_MODEL` (e.g. `BAAI/bge-base-en-v1.5`). No network calls. No API key. Cold start blocks `/readyz` until the model is loaded.
2. **`openai`** — calls `POST {EMBEDDINGS_BASE_URL}/embeddings` with `EMBEDDINGS_API_KEY` and `EMBEDDINGS_MODEL`. Any OpenAI-compatible endpoint works (OpenAI, OpenRouter, vLLM, HF TEI, …). The base URL is required even for OpenAI proper, so there is no implicit default endpoint.

The interface is small and provider-agnostic:

```
EmbeddingsProvider:
    dim: int                 # declared up-front, validated against schema at startup
    embed(texts: list[str]) -> list[Vector]    # batch by design
```

The Embedder component owns:

- The startup `EMBEDDINGS_DIM` ↔ `vector(N)` check (hard-fail mismatch).
- The timeout and **single retry** policy from S6.5.
- The structured-error mapping (`EmbeddingError` → `{error: "embedding_failed", hint}` at the tool boundary).
- Concurrency: in-process providers run on a thread pool to avoid blocking the event loop; HTTP providers use the existing async HTTP client.

Caching, batching across requests, and provider warm-up beyond the startup load are **out of scope** for v1.

## Consequences

**Positive.**
- One abstraction, two providers, room for a third. New providers add a class, not a refactor.
- Local development needs zero secrets: `EMBEDDINGS_PROVIDER=sentence-transformers` and a model name is enough.
- Production deployments can swap to a hosted endpoint by changing four env vars, no rebuild.
- The `EMBEDDINGS_DIM` invariant catches the most common foot-gun (model swap without schema migration) on startup, not at first save.

**Negative / accepted trade-offs.**
- **In-process model size.** A 768-dim BGE model adds ~400 MB to the image and ~1 GB resident. The container is no longer "tiny". Mitigated by documenting that hosted endpoints are the recommended production path.
- **Cold start.** First boot can take tens of seconds while the model loads. `/readyz` reflects this; orchestrators must respect readiness probes.
- **Two test surfaces.** Integration tests must cover both providers' happy and error paths. We accept this; the alternative (one provider) sacrifices either local dev ergonomics or production flexibility.
- **No client-side caching in v1.** A second `memory_save` for identical text re-embeds. Acceptable: the scenario is rare, and caching is easy to add later as a decorator on the interface.

**Not chosen, and why.**
- **OpenAI-only.** Forces a network dependency and an API key on every developer; conflicts with the "one team can stand up one shared server" goal.
- **In-process only.** Locks every deployment into shipping the model in the container and bars cheap hosted alternatives.
- **A bespoke gRPC embeddings protocol.** Re-invents what the OpenAI-compatible API already standardises across providers. No.
- **LangChain's embeddings abstraction.** Drags in a heavy dependency for a two-method interface. Disproportionate.

## References

- REQUIREMENTS.md — S1.2, S1.3, S5.1, S6.5
- docs/design/v1-design.md — Embedder component; interactions I1, I2, I3
- ADR-0001 (flat value schema): the embedding lives on the row, not in a side table
