# Research

## Internship signals

The supplied Elip SDE Intern listing is the application reference. It describes a two-month role in Gurugram or Bengaluru and explicitly screens for prompting, tool use, structured outputs, and designing tables and queries for a real system. The public Software Engineer listing also emphasizes changing job indexes, ranking and personalization, LLM evaluation, and reliable production Python APIs. Elip's public product describes remembering preferences, honoring dealbreakers, and showing candidates which facts still need checking.

- [Public role listing](https://dashboard.tryelip.ai/jobs/PsnWr)
- [Product](https://tryelip.ai/) and [fairness boundary](https://tryelip.ai/fairness)

## Prior work

I reviewed the public project documentation for four accessible repositories. These are design lessons, with fresh code and data for MatchBench.

| Project | Lesson carried into MatchBench |
| --- | --- |
| [ArogyaMitra](https://github.com/aadi-harale/ArogyaMitra) | A bounded planner/tool loop with a durable record of tool execution. |
| [SahiAaya / Graph Hacks](https://github.com/aadi-harale/graphhacks) | Require approval for writes, preserve provenance, and compare fairly against baselines with the same inputs. |
| [DisburseProof](https://github.com/aadi-harale/disburseproof) | Make a replay from stored events inspectable, and bind an ingestion mutation to its idempotency key. |
| [LegalEase](https://github.com/aadi-harale/LegalEase) | Separate document ingestion and extraction; show actionable feedback when an upload fails. |

The brief's examples are illustrative. Public repository documentation can support specific, attributed project evidence. Individual ownership and employment facts require their own source or candidate review. Demo job records are explicitly marked illustrative. A larger generated corpus is appropriate for load tests, with separate reporting from the relevance benchmark.

## Technical choices

- **Postgres is the source of truth.** pgvector supports exact cosine search and HNSW/IVFFlat if measured load warrants approximate indexing. On a small corpus, exact search makes the filtered results easier to verify. [pgvector documentation](https://github.com/pgvector/pgvector#filtering)
- **BM25 is a measured baseline.** BM25S provides a real sparse BM25 implementation with score access. Tokenization preserves technology names; the same versioned corpus feeds both modalities. [BM25S](https://github.com/xhluca/bm25s)
- **Embedding and reranking models are CPU-capable.** Use the published MiniLM encoders with quantized ONNX artifacts, tokenizer files, and pinned model revisions. Both model cards list Apache-2.0. [Embedding model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) · [Cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) · [Retrieve and rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)
- **Structured agent responses are validated at the service boundary.** Tool calls use named schemas, a narrow allowlist, and typed arguments. Validate every model response server-side and record outcome, elapsed time, usage where available, and retries. [Function calling](https://platform.openai.com/docs/guides/function-calling) · [Structured outputs](https://platform.openai.com/docs/guides/structured-outputs)
- **Ranking labels are versioned artifacts.** Store query/job relevance labels, preserve a held-out split, and report coverage and scoring conventions alongside metrics. [NIST TREC relevance judgments](https://trec.nist.gov/data/qrels_eng/index.html)
