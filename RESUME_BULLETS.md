# Résumé bullets

- Built a job-ranking and evaluation platform with Python, FastAPI, PostgreSQL, pgvector, BM25, and a MiniLM cross-encoder. Personalized ranking reached 0.624 Precision@5 versus 0.540 for embeddings on 50 held-out queries over 42 curated job fixtures.
- Designed versioned SQL records for candidate evidence, preference events, and match replay. Implemented deterministic dealbreakers and a counterfactual inspector. Benchmarked incremental indexing on 3,072 generated jobs and reused existing embeddings for all 64 metadata-only updates in a 128-job change batch.
- Built a typed preference agent and evaluation harness with 36 explanation checks and 32 live local-model cases. Deployed a React and FastAPI preview backed by PostgreSQL, with Docker packaging, GitHub Actions, and browser regression tests.
