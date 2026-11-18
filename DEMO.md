# Interview demo

**Opening.** “MatchBench ranks jobs against candidate evidence, dealbreakers, and preferences. Each recommendation comes with a trace and a reproducible benchmark.”

| Time | Show |
| --- | --- |
| 0:00–0:22 | Open the public demo. Point out the senior role with high raw similarity and a five-year requirement. Click **Inspect a rejected match**. |
| 0:22–0:50 | Open **Decision trace**. Show the experience check, raw similarity, and unranked result. Run **Exact replay** and show that the frozen ordering matches. Switch back to **Ranked** and open the internship. |
| 0:50–1:25 | Choose **Set aside**, select **Agent Infrastructure Intern**, and open **What if?**. Recompute with Hyderabad allowed. Show the before/after eligibility and rank. |
| 1:25–1:58 | Open **Memory**, select **No frontend-heavy roles**, interpret it, and inspect the typed patch. Reject it first to prove memory is unchanged; repeat and approve to create an event. |
| 1:58–2:32 | Open **Evaluation**. Compare P@5, Recall@20/100, nDCG, and p95. Explain the small authored scope, the separate synthetic result, weighted fusion vs RRF, and the reranker tradeoff. |
| 2:32–2:55 | Open the stored run or architecture, and point to one test proving that memory survives restart or login and one that checks the PostgreSQL cosine path. |

**Close.** “The agent proposes preference changes. The candidate controls memory, and every ranking decision is inspectable, challengeable, and replayable.”

## Interview notes

| Prompt | Answer |
| --- | --- |
| What are the system boundaries? | FastAPI owns the domain API. PostgreSQL owns history, snapshots and vectors. BM25S, exact cosine, and the cross-encoder provide independent signals. The browser renders actual run records and computed counterfactuals. |
| Why use both retrieval channels? | BM25 rewards precise terms such as FastAPI and pgvector. The embedding retrieves related descriptions even when wording differs. The evaluation measures both channels, so fusion is an empirical choice. |
| When does reranking help? | It can improve the first few jobs by jointly encoding each query and posting. It also adds CPU cost and can degrade order on particular query families. The dashboard shows actual 20, 50 and 100 depth caps and effective pair counts. |
| How is ranking kept reproducible? | Python computes eligibility, SQL reads versioned inputs, and scoring uses pinned models and explicit parameters. The agent produces a typed proposal gated by confirmation. |
| How does memory work? | Store patch, resulting state, version, source and supersession link in the same transaction. Match runs record the memory version they read. Direct edits and criticism follow the same write path after approval. |
| How were labels made? | Each authored topic specifies explicit grades for plausible matches and assigns zero to omitted fixture pairs. Five query formulations share each topic’s judgments. Report coverage, query count, and topic count. |
| How did you avoid tuning leakage? | Pick fusion weight on distinct development intent families. Keep holdout topics grouped. Bootstrap paired topic means because paraphrases are dependent. |
| What do the metrics mean? | Precision@5 counts qualifying hits among five slots. Recall@10 divides qualifying hits by eligible judged positives. MRR gives credit for the first relevant placement. nDCG discounts lower ranks and uses graded relevance. |
| How would you scale from 10K to 10M jobs? | Add indexed structured prefilters first. Measure exact and filtered ANN recall. Partition on stable dimensions, batch vector generation, and evaluate HNSW versus IVFFlat under real filters. Bound CPU reranker concurrency and use connection pooling. |
| How does incremental indexing work? | Resolve the canonical fingerprint, create a new job revision on change, and derive the vector key from embedding input and model revision. Keep old revisions available for replay. |
| How would you replace a model? | Backfill vectors under new keys while serving the old release. Compare on frozen labels and out-of-time queries, then promote the new revision. Save the revision used by every match run. |
| How is candidate privacy handled? | Use owner-scoped queries, secure cookies, Argon2, upload limits and no retained raw resume file. Export and deletion cover versioned personal records. |
| How do you evaluate fairness? | Exclude protected attributes from the ranking projection. Perturb candidate identity fields while keeping the same evidence and compare outputs. Measure subgroup performance only with appropriate, consented data and report label coverage. |
| What breaks first under load? | Exact vector transfer/scan and cross-encoder CPU. Index growth and retained decision rows also need partitioning, TTLs aligned with privacy policy, and smaller stored result sets. |
| What would you build in two more weeks? | License a stronger corpus, obtain independent graded judgments, tune per-intent retrieval with guardrails, improve structured preference evaluation, and instrument deploy latency on real traffic. |
