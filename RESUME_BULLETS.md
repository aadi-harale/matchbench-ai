# Résumé bullets

- Built and deployed an evidence-grounded job-ranking platform with Python, FastAPI, PostgreSQL/pgvector, BM25, MiniLM embeddings, a cross-encoder, React, and TypeScript; preference-aware ranking reached **0.624 Precision@5** versus **0.540** for embeddings on 50 held-out authored queries over 42 illustrative jobs.
- Designed versioned SQL records and an approval-gated typed agent so candidate evidence, preference history, exact decision replay, counterfactuals, and rejection/reset flows remain auditable; the deterministic fallback matched **72/72** labeled intents and the evidence contract passed **36/36** cases with 0 unsupported claims.
- Evaluated retrieval on a separate 300-job / 100-query held-out synthetic fixture, tuned fusion and reranking only on disjoint development topics, and benchmarked idempotent ingestion on 3,072 generated jobs with zero re-embeddings on identical import and reuse for all 64 metadata-only updates.

These claims are fixture measurements, not production traffic or hiring outcomes.
