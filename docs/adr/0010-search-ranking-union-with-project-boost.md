# 0010. Search ranking: union of project + global with a fixed project boost

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** LS / Claude

## Context

`memory_search` is the most consequential tool in the Recall surface — it is what the agent calls every time it asks "what do we already know?". The requirements (S1.3) state two non-trivial properties:

1. A project-scoped search returns hits from the named project **and** from `scope=global` in a single ranked list, each tagged with its scope.
2. Project hits get a small ranking boost so that they win ties, **but** a high-confidence global hit can still outrank a weak project hit.

That second clause is a real product decision, not a stylistic note: it means the boost is *additive and bounded*, not a hard sort key. Get the magnitude wrong and either (a) global memories dominate the list and project context gets buried, or (b) the boost is so large it amounts to a hard filter and global memories become invisible.

The Memory Service component (HLD Level 2) owns this logic, and the Level 3 interaction I2 names it as a Level-4 contract. Pinning the formula in an ADR means the ranking rule is reviewable as a product decision in one place, and the LLD does not have to re-derive it under a deadline.

## Decision

Recall v1's `memory_search` follows the **union-then-merge with a fixed additive boost** strategy:

1. The Memory Service computes the query embedding **once**.
2. It issues a vector search against the `("project", project_id)` namespace and another against `("global", null)`, each requesting `limit + boost_window` rows so the merge has headroom. Filters (`kind`, `user_id`) are applied at the storage layer in both queries.
3. Each row carries the raw cosine similarity returned by the store as `raw_score`.
4. The Memory Service computes the final `score`:
   - `score = raw_score + PROJECT_BOOST` for project hits
   - `score = raw_score` for global hits
   - where `PROJECT_BOOST` is a **fixed, configurable constant** with a documented v1 default (target: small enough that a global hit at `raw_score = 0.92` can still outrank a project hit at `raw_score = 0.75`; large enough that two hits within `0.02` of each other resolve in favour of the project). The exact constant is set by the LLD and tunable via env var; the *rule* is what this ADR pins.
5. The merged list is sorted by `score` descending and truncated to `limit`. Each result carries `scope` so the agent can see why a result is ranked where it is.
6. If `scope="project"` or `scope="global"` is passed explicitly, the corresponding query is skipped entirely and no merge happens.

What this ADR does **not** decide:
- The numeric value of `PROJECT_BOOST`, `boost_window`, or the default `limit`. Those are LLD-level knobs.
- Whether the store's vector search uses cosine, inner product, or L2 — the store's default suffices, the boost is applied to whatever the store returns.
- Re-ranking with a cross-encoder. Out of scope for v1.

## Consequences

**Positive.**
- The product rule from S1.3 ("project hits win ties, but a strong global hit can still outrank a weak project hit") is mechanically guaranteed by an additive boost — no edge case where global is silently invisible.
- One embedding call per search regardless of how many namespaces are queried.
- The merge happens in application code, not in a complex SQL union, so the Storage Adapter stays a thin wrapper (per ADR-0001 / ADR-0002 spirit).
- The boost constant is a single tuning knob; reviewers can argue about its magnitude in one place.
- `scope=project` / `scope=global` shortcuts cost zero at the merge stage — a single store query, no special-casing.

**Negative / accepted trade-offs.**
- **Two store round-trips per default search.** Mitigated by issuing them concurrently. The alternative (one query against a union view) couples the Storage Adapter to a query shape it does not otherwise need.
- **An additive boost is crude.** A learned re-ranker would do better. We are deliberately not building one in v1; the boost is tunable post-deployment via env var, which is the right level of mechanism for v1.
- **The constant will be wrong on first attempt.** Accepted — it is an env var, not a code change. The LLD will name a starting value and a tuning procedure (eyeball search results across a dozen real queries, adjust, repeat).
- **Headroom (`boost_window`) costs a few extra rows per query.** Negligible.

**Not chosen, and why.**
- **Hard sort by scope, then by score.** Violates the "strong global hit can outrank weak project hit" clause. Hard no.
- **Multiplicative boost (`score *= 1.1`).** Behaves badly when raw scores cluster near 1.0 — the boost shrinks exactly when ties are most likely. Additive is more predictable.
- **Cross-encoder re-rank.** Adds latency and a model dependency. Out of v1 scope; can land later behind the same Memory Service interface without changing the ADR.
- **Letting the store do it via SQL union + a CASE expression.** Pushes ranking logic into the Storage Adapter, which the design wants kept thin. The merge belongs in the Memory Service.

## References

- REQUIREMENTS.md — S1.3, S2.3
- docs/design/v1-design.md — Memory Service; interaction I2
- ADR-0004 (filter limitations): the `kind` / `user_id` filters in step 2 use only the operators that actually work
