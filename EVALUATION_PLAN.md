# Evaluation plan

MatchBench keeps three claims separate: relevance quality on authored fixtures, retrieval behavior on a larger synthetic fixture, and ingestion/runtime behavior on generated load data. None of these artifacts is described as user or hiring-outcome evidence.

## Datasets and splits

| Artifact | Purpose | Split |
| --- | --- | --- |
| 42 illustrative jobs, 60 query phrasings, 12 intent topics | Inspectable graded relevance and end-to-end ranking | 10 development queries from 2 topics; 50 held-out queries from 10 disjoint topics |
| 300 synthetic jobs, 120 queries, 12 topics | Larger candidate-retrieval check | 20 development queries from 2 topics; 100 held-out queries from 10 disjoint topics |
| 72 agent messages | Typed preference, clarification, safety, and multi-change behavior | Fixed contract suite, no model tuning |
| 3,072 generated jobs | Idempotency, embedding reuse, index size, and latency | Initial import, identical re-import, 128-record change batch |

Job labels are 0–3. Grades 2–3 are relevant for Precision@5, Recall@10, Recall@20, MRR, and candidate Recall@100; nDCG@10 uses graded gains. Query paraphrases are dependent, so the primary comparison also reports a paired topic bootstrap interval.

## Ranking experiments

The same eligibility and ranking service evaluates keyword overlap, BM25, cosine embeddings, weighted hybrid fusion, hybrid plus cross-encoder, and preference-aware ranking. RRF is an explicit fusion alternative. Fusion alpha, RRF k, rerank depth, and cross-encoder weight are selected only on the development topics and then frozen for held-out evaluation.

The reranker grid is depth 10/20/50/100 by blend weight .2/.4/.6/.8/1.0. The selected 20-result, .2-weight configuration improves held-out nDCG@10 over hybrid on the authored fixture but adds material CPU latency. The synthetic fixture reveals weaker generalization and is published unchanged. Timings use a monotonic clock and report warm-model p50/p95 by retrieval, rerank, and total stage.

## Agent and evidence checks

The evidence contract checks 36 citation and missing-skill cases and computes unsupported-claim rate. The 72 agent cases cover role, location, work mode, relocation, company and skill preferences; multiple simultaneous edits; clarification; temporary/no-store language; and protected attributes. Report schema-valid rate, policy-valid rate, expected-intent accuracy, clarification rate, unsafe-mutation rate, fallback rate, and latency when a provider is configured.

Provider evaluation is opt-in and separate. A hosted result is `null` unless the configured provider actually ran. The deterministic path is a reliability fallback, not evidence that an LLM is accurate.

## Reproduction and release policy

Pin corpus, query, label, model revision, and normalized hashes. Publish absolute metrics and disappointing results. Do not promote a result when only latency changed, when a development win does not survive held-out evaluation, or when the model/dependency needed for exact replay is missing. [Commands and environment](BENCHMARK_REPRODUCTION.md)
