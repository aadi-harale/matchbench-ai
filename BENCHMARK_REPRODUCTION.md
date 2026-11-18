# Benchmark reproduction

Reproduced on 18 November 2026 from a fresh, isolated SQLite database. Quality values, selected parameters, normalized hashes, ingestion counts, and contract counts are deterministic. Latency is a local sample and varies by host.

## Environment and pinned dependencies

Windows 11 `10.0.26300` AMD64; Intel Family 6 Model 197; Python 3.12.10; Node 24.16 / npm 11.13; ONNX Runtime 1.32.0; NumPy 2.5.5; BM25S 0.3.16; SQLAlchemy 2.0.58; FastAPI 0.164. Models were warm and query vectors cached before latency measurement.

| Role | Pinned model | ONNX SHA-256 |
| --- | --- | --- |
| Embedding | `sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41:onnx/model_quint8_avx2.onnx` | `b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L6-v2@233902d25c440f23af6f7d6e94d2946bac0bee0a:onnx/model_quint8_avx2.onnx` | `c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9` |

## Commands

```powershell
$env:DATABASE_URL='sqlite:///./.audit/reproduction.db'
$env:MODEL_DIR='.models'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m matchbench.cli ingest data\jobs.json
.\.venv\Scripts\python.exe -m matchbench.benchmark --output data\benchmark.json --ablation-output data\reranker_ablation.json
.\.venv\Scripts\python.exe -m matchbench.benchmark --contracts-only --output data\agent_benchmark.json
.\.venv\Scripts\python.exe -m matchbench.large_benchmark --generate --output data\large_benchmark.json
.\.venv\Scripts\python.exe -m matchbench.load_benchmark --size 3072 --output data\load_benchmark.json
```

## Authored relevance fixture

The 42-job corpus has 10 development query phrasings from 2 topics and 50 held-out phrasings from 10 disjoint topics. Grades 2–3 are relevant; nDCG uses graded labels.

| Method | P@5 | R@10 | R@20 | MRR | nDCG@10 | Candidate R@100 | p95 total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Keyword | .440 | .655 | .804 | .896 | .682 | .808 | 0.53 ms |
| BM25 | .488 | .718 | .804 | .938 | .725 | .808 | 0.58 ms |
| Embeddings | .540 | .892 | .981 | .980 | .848 | 1.000 | 9.23 ms |
| Hybrid | .548 | .881 | .985 | .960 | .832 | 1.000 | 7.82 ms |
| Hybrid + cross-encoder | .556 | .889 | .985 | .970 | .843 | 1.000 | 165.69 ms |
| Hybrid + preferences | .624 | .897 | .985 | .970 | .854 | 1.000 | 152.36 ms |

Development tuning selected weighted-fusion alpha .5, RRF k 60, rerank depth 20, and cross-encoder weight .2. Weighted fusion beat RRF on held-out nDCG@10 (.832 vs .812). The reranker improved nDCG but imposed a large CPU cost. The paired topic-bootstrap interval for personalized minus embedding nDCG crosses zero (`-.021655` to `.028168`).

Raw input SHA-256 values: jobs `b50ca6c48a0394701a41ba7b2c672d3490d93ef5f9767eb67afc7421715496ed`; judgments `4ef6b2aa0217e5a9c3d6487961fde68b988432d88442bf75443a97200220bfb7`; agent cases `a88228802e6b65c69ee2065d7ecdf5e030771b1de80c68092eaebff119df3841`.

## Larger synthetic retrieval fixture

The generated corpus contains 300 explicitly synthetic jobs, 20 development queries, and 100 held-out queries. Dense retrieval produced .956 candidate Recall@100. Hybrid + reranker produced .410 P@5 and .439 nDCG@10 versus .402/.400 for hybrid and .460/.446 for embeddings. This is a reproducible engineering fixture, not a real-job quality claim.

Normalized hashes: dataset `f0b023d1353e22e45dac88d5b4cba5131d439f22b316f55a6f9f09eed93d3363`; queries `cc247de132293a52d66b97e55807ed6db18825fb02849afb0b40ee357267205c`; judgments `94bfd5014d3fd85fa05a6e4c9f61c4041eb0cfcd7de3a2928bd6968df35e5244`.

## Agent, evidence, and ingestion

- Evidence-grounded explanations: 36/36; missing skills: 36/36; unsupported-claim rate: 0%.
- Deterministic agent fallback: 72/72 schema-valid, 72/72 policy-valid, 72/72 expected intents; clarification 100% where required; unsafe mutation 0%.
- Hosted LLM result: `null`. No provider was configured, so no model-quality claim is made.
- Generated load: 3,072 active jobs; zero embeddings on identical re-import; 128 updates split into 64 metadata-only and 64 description changes; only the 64 description changes were re-embedded.

## Limits

The authored corpus is small; the larger corpus is synthetic; paraphrases within topics are dependent; latency is warm local CPU; exact cosine is used; filtered ANN recall, throughput, and peak memory are not yet measured; and no user or hiring-outcome experiment has run.
