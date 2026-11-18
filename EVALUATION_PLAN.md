# Evaluation plan

Use a fixed job corpus with realistic hard negatives and graded relevance labels. The development and held-out groups use distinct intents and examples. Freeze labels before comparing models. A motivated engineer can inspect every judgment and rerun the same methods with a single command.

## Ranking experiments

1. Keyword overlap.
2. BM25.
3. Cosine embedding retrieval.
4. Hybrid BM25 and cosine.
5. Hybrid with cross-encoder.
6. Hybrid with cross-encoder and preference ranking.

Use the same labeled query, corpus, and eligibility policy for each variant. Grade a job from 0 (irrelevant) through 3 (strong fit), with grades ≥2 relevant for Precision@5, Recall@10 and MRR. nDCG@10 uses graded gains. Report recall relative to judged relevant items, the judged pool size, and coverage of each variant's top 10. Compare 20/50/100 cross-encoder depths where distinct. Time every stage using a monotonic clock and report p50/p95 with environment and cache state. Index data size and corpus size are measured separately. Record dataset and configuration checksums.

## Agent and evidence checks

The evidence contract has 36 fixtures for citation, missing skills and consistent rendering. The provider benchmark runs separately on 32 labeled preference messages. It requires a provider result that passes schema and policy validation and matches the expected field, operation, and value, or asks for clarification where appropriate. Mocked failure tests cover malformed responses independently. [Preference cases](data/agent_cases.json) · [Measured provider report](data/agent_benchmark.json)

## Publish policy

The dashboard loads the generated results file. Demo jobs and any generated load corpus are labeled as such. Report absolute metrics and quality/latency tradeoffs with scope. Release claims come from measured artifacts, including disappointing results.
