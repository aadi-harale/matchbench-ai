# MatchBench AI — recruiter brief

MatchBench is an evidence-grounded job matcher and evaluation workbench built for the problems Elip described: conversational preference updates, retrieval and ranking, semantic search over a changing index, LLM-quality evaluation, and reliable backend delivery.

## See the engineering in three minutes

1. Open the [live demo](https://matchbench-ai-aadi.vercel.app) and choose **Inspect a rejected match**. A semantically strong senior role is blocked by the experience gate; the decision trace shows why.
2. Run **Exact replay**. The service reuses the recorded query, time, profile, preferences, job revisions, weights, and pinned models, then compares the result order.
3. Open **What if?** on the Hyderabad role. Changing one assumption recomputes the rank without changing saved evidence or memory.
4. In **Memory**, interpret a preference, inspect the typed patch, then approve or reject it. Rejecting leaves memory unchanged. Reset restores a clean demo session.
5. In **Evaluation**, compare six ranking variants, candidate Recall@100, RRF, reranker cost, agent contracts, and index churn.

## What was measured

- 0.624 Precision@5 for preference-aware ranking vs 0.540 for embeddings on 50 held-out authored queries and 42 illustrative jobs.
- 0.956 dense candidate Recall@100 on a separate 100-query / 300-job held-out synthetic fixture.
- 72/72 deterministic preference intents and 36/36 evidence-contract cases. No hosted-LLM number is claimed.
- 3,072-job generated load run: zero re-embeddings on identical import and reuse for every metadata-only update.

The architecture is FastAPI + PostgreSQL/pgvector with versioned jobs, append-only preference events, owned run snapshots, BM25, MiniLM embeddings, a cross-encoder, React/TypeScript, Docker, CI, and Vercel/Supabase deployment. The small authored relevance corpus and synthetic larger corpus are explicit limitations, not hidden behind product language.
