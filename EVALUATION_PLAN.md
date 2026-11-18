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

Target at least 30 cases across missing skill detection, validated structure, unsupported assertions, conditional or conflicting preferences, dealbreaker compliance, and repeated rendering. Hosted model evaluation is reported separately from deterministic contract checks and mocked failure tests. Evaluate every explanation against source-linked evidence and job requirements. Keep rejection and uncertain outcomes visible in the report.

## Publish policy

The dashboard loads the generated results file. Demo jobs and any generated load corpus are labeled as such. Report absolute metrics and quality/latency tradeoffs with scope. Release claims come from measured artifacts, including disappointing results.
