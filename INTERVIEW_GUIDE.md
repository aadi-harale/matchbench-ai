# Interview guide

## Architecture

**Why one FastAPI service?** It keeps the demonstration operationally legible while separating domain modules for ingestion, eligibility, retrieval, ranking, agent policy, and persistence. PostgreSQL is the durable boundary; workers or services can be split when throughput justifies it.

**What is deterministic?** Eligibility, score fusion, bounded preference adjustments, tie-breaking, proposal validation, confirmation, replay dependency checks, and every fallback. The LLM may draft a typed proposal; it never writes memory directly.

**How does exact replay differ from display?** Display reads stored results. Exact replay recomputes with frozen job revisions, profile and preference versions, query, time, weights, and model revisions, then compares ordering. It returns a dependency error if the recorded model is unavailable.

## Retrieval and ranking

**Why BM25 plus embeddings?** BM25 preserves exact technical terms; embeddings recover semantic paraphrases. Weighted fusion beat development-tuned RRF on the authored holdout, so the simpler weighted path stayed in production.

**When does the reranker help?** On the authored holdout it raises hybrid nDCG@10 from .832 to .843, but p95 rises from about 8 ms to 166 ms. On the larger synthetic fixture its gain is weaker. The 20-result / .2-weight setting came from a development-only grid, not the test set.

**Why exact cosine instead of ANN?** At the demo corpus size exact cosine is simpler and provides a recall reference. Filtered HNSW recall has not been measured on this project, so enabling ANN would be an unsupported scale claim.

**How would you scale to millions of jobs?** Push selective structured filters into indexed SQL, batch and deduplicate embedding work, measure filtered HNSW/IVFFlat recall against exact cosine, bound reranker concurrency, use a queue for ingestion, and roll model revisions side by side before promotion.

## Agent and memory

**How is prompt injection contained?** Provider output must match a narrow schema and allowed preference fields. Unknown/protected attributes and contradictions are rejected. Attempts are bounded, tool calls are audited, and a candidate must confirm the proposal.

**What is memory?** An append-only event stores the patch, source, base version, resulting state, and time. Search records the version it read. Rejecting a proposal adds an audit outcome but does not create a preference event.

**What happens when the provider fails?** The attempt is recorded and the request falls back to a deterministic interpreter for supported phrases. Search independently degrades from reranker to hybrid and from embeddings to BM25.

## Evaluation and operations

**How did you avoid leakage?** Topic-disjoint development and held-out splits select fusion, RRF, depth, and blend settings. Final results are computed once on held-out topics. Hashes pin the normalized artifacts.

**What do you monitor?** Readiness exposes database, corpus, ingestion freshness, and model availability. Observability tracks request IDs, counts, errors, fallbacks, tool validation, and latency aggregates. Production needs histogram export and a shared rate limiter before meaningful traffic.

**What is the largest weakness?** Relevance evidence is still authored or synthetic. The next defensible step is a licensed changing jobs feed, independent graded labels, filtered ANN experiments, and online reliability monitoring—not a bigger unverified model.
