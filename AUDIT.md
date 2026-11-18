# MatchBench AI audit

Audit date: 18 November 2026  
Audited revision: `38713f8c2701699e2110e6382c665ea78d395f03`

This audit covers the current repository, its benchmark artifacts, the connected Supabase project, the current Vercel production deployment, and the latest GitHub Actions run. It distinguishes implemented behavior from requested or documented behavior. Benchmark figures are treated as unverified until reproduced in `BENCHMARK_REPRODUCTION.md`.

## What is already strong

- The product has a coherent engineering thesis: semantic similarity is separated from deterministic eligibility, evidence coverage, preference adjustments, and the final ranking decision.
- The hosted workflow is real. A natural-language preference produces a typed proposal, Pydantic validates it, deterministic policy code checks it, confirmation is required, and only then is an append-only preference event written.
- The fallback boundary is honest. The API returns the effective provider, and search remains deterministic when the model path is unavailable. Embedding failure falls back to BM25; reranker failure falls back to hybrid.
- Job, profile, preference, model, and match-run state is versioned. Match runs retain the query, profile version, preference version, job revision IDs, scoring weights, model identifiers, effective algorithm, and stored decisions.
- Candidate evidence is review-gated. Only accepted evidence can satisfy a required skill; pending evidence becomes an unknown and absent evidence becomes a missing skill.
- Counterfactual evaluation reuses a recorded run's profile, memory version, query, timestamp, algorithm, weights, model identifiers, and job revisions. A hypothetical skill is kept separate from saved evidence.
- The SQL model is compact and relevant to Elip: versioned profiles, append-only preference events, job revisions, content-addressed embeddings, match decisions, agent runs, and tool calls.
- Ingestion has canonical fingerprints, duplicate handling, transactional locking, job revisions, and embedding reuse when embedding-relevant text is unchanged.
- The project has explicit failure tests for malformed model output, embedding failure, reranker failure, invalid documents, stale/empty states, ownership, version conflicts, and PostgreSQL vector execution.
- Production is live at `https://matchbench-ai-aadi.vercel.app`. The current deployment is `READY` on Vercel, `/ready` reports PostgreSQL, 42 jobs, embeddings, and reranking, and the latest GitHub Actions run for the audited commit passed.
- The connected Supabase project is `ACTIVE_HEALTHY`. All public tables have RLS enabled, no `anon` or `authenticated` table grants were returned, policies are scoped to the dedicated `matchbench_app` role, and the security and health advisors returned no findings.
- The interface is a restrained ranking workbench rather than a generic AI landing page. It supports a visible rejected-role path, decision trace, counterfactual, memory confirmation, evaluation view, dark mode, keyboard focus, reduced motion, and four tested viewport widths.

## What is technically weak

- `create_app()` owns startup, authentication, rate limiting, observability, account operations, agent execution, search orchestration, evaluation delivery, and static serving. This concentration makes failure isolation and focused testing harder.
- Observability stores cumulative duration totals rather than request histograms or p50/p95 values, has no request IDs, and does not directly expose LLM latency, validation failures, fallback counts, or last successful request/index state in a structured schema.
- Rate limiting is per process. It resets on cold start and is not coordinated across Vercel instances.
- CSRF protection relies on `SameSite=Lax` plus an Origin comparison when an Origin header is present. Requests with no Origin are accepted; this is a reasonable demo boundary, not a complete production CSRF design.
- The default session secret is generated at process startup. Production must supply a stable secret or sessions will be invalidated across instances/cold starts; readiness does not currently assert that production security configuration is present.
- Demo users and their historical runs accumulate indefinitely. There is a reset-by-new-session path, but no cleanup/retention policy.
- Exact vector retrieval currently reads the active snapshot and computes exact scores. That is appropriate for 42 jobs but does not establish performance at a realistic changing index size.
- The benchmark measures six methods on 42 authored jobs. Fifty held-out query phrasings come from ten topic families, so query-level counts overstate the number of independent information needs.
- The benchmark tunes only three hybrid-alpha values. It does not test RRF, candidate Recall@100, Recall@20, reranker blend weights, or held-out rerank-depth selection.
- The current cross-encoder experiment confirms a quality/latency tradeoff but does not diagnose it by intent family or blend weight.
- The provider benchmark contains 32 cases, below the requested 60–100 range, and reports validation/correctness counts rather than the full schema-valid, policy-valid, clarification, unsafe-mutation, and fallback metrics.
- Evidence contract evaluation contains 36 mechanically generated fixtures, not 50+ diverse explanation fixtures. It checks cited IDs and missing skills but not every possible unsupported natural-language claim.
- The repository has no application-level replay action that refuses when the exact model artifact is unavailable. `GET /api/runs/{id}` replays stored output; counterfactual recomputation is not the same as an explicit reproducible replay command.
- CI does not run Playwright. The browser suite exists and has been run manually, but it is not a merge gate.
- GitHub Actions uses floating major tags (`actions/checkout@v4`, `actions/setup-*`) rather than reviewed commit SHAs.

## What is misleading or overstated

- README ranking numbers match the committed artifact, but they are not yet independently reproduced in this audit. They must remain provisional until the exact commands, fixture checksums, model revisions, cache state, and resulting outputs are captured.
- “50 held-out queries” is true, but those are five phrasings for each of ten held-out topics. The README should state both counts prominently.
- The repository describes a 3,072-job “index” benchmark. It is a generated SQLite ingestion/runtime workload, not a relevance benchmark and not a PostgreSQL/ANN scale result. The README currently labels it generated, which should be preserved.
- The hosted preview does not currently use an LLM: `/ready` reports `llm_configured: false`. The UI correctly shows the local-rules provider, but recruiter copy must not imply the hosted path used an LLM.
- The README says browser checks cover the recruiter flow at four widths; they exist and have prior passing evidence, but CI currently runs only type-check/build for the frontend.
- The README's “row-level security enabled, public Data API roles have no table grants, dedicated backend role” statement is supported by the current Supabase inspection. It should be described as the present deployment configuration, not a guarantee of every future environment.
- “Replay” currently means reading an immutable stored run. Exact recomputation with artifact-availability checks is not yet implemented.

## What is missing

- `BENCHMARK_REPRODUCTION.md`, `SECURITY.md`, `TEST_MATRIX.md`, `INTERVIEW_GUIDE.md`, and `RECRUITER.md`.
- A 250–500 record, clearly licensed/manual/synthetic evaluation corpus with 100+ queries, graded judgments, a development split, and a held-out test split.
- Candidate-generation Recall@100 and Recall@20 reporting.
- RRF versus normalized weighted fusion.
- Reranker depth × blend-weight × hybrid-alpha ablation with quality, latency, throughput, and memory reporting.
- A pgvector exact-versus-HNSW experiment and a documented crossover threshold.
- At least 60 diverse preference-agent cases, including reversal, temporary/non-storage instructions, protected attributes, company exclusions, conditional relocation, multiple simultaneous changes, and the “Kubernetes interest is not evidence” boundary.
- Explicit reject/dismiss persistence for an agent proposal. The frontend dismisses locally, but the backend run remains pending.
- A reset-demo endpoint/button that deletes or resets the current demo state instead of creating another session implicitly.
- An explicit replay-run endpoint/action with model-artifact availability checks.
- Job expiration/deletion accounting in ingestion, and benchmark fields for peak memory and database size across full and incremental imports.
- Request IDs and complete structured observability counters.
- CI Playwright execution or a documented reason to keep it out of CI.
- High-quality README screenshots and a concise preference-proposal-to-rerank animation.
- Repository description/topics/public visibility and a pinned-profile repository. The repository is currently private.

## What is unnecessary

- Multi-agent ranking would add indirection without improving the deterministic decision boundary. One bounded interpretation agent is the correct scope.
- Kafka, Kubernetes, a separate vector database, and distributed services are not justified by the current corpus or traffic.
- Decorative AI animations, confidence percentages, and broad “smart matching” claims would weaken the project's technical honesty.
- Further visual polishing is lower priority than benchmark reproduction, larger held-out evaluation, agent cases, and reproducible experiments.
- `graphify-out/` is an audit aid, not a product deliverable. It should remain ignored unless the team explicitly wants to publish the architecture graph.

## What could fail during an interview demo

- A Vercel cold start can make the first interaction noticeably slow, especially when models and the database connection initialize.
- The hosted demo uses local rules. A recruiter trying a preference outside the narrow supported phrases will receive a clarification rather than an LLM-derived proposal.
- Demo visitor rows accumulate; high use can increase database size and make cleanup a concern.
- Process-local rate limits and observability reset on cold starts, so the counters are not deployment-wide.
- If `SESSION_SECRET` is missing or changes, the browser appears to lose its session.
- Counterfactual recomputation correctly fails if a required model is unavailable, but there is no UI recovery path beyond the error message.
- “Add evidence for Kubernetes” in the counterfactual menu may be misread as mutating the profile even though it is simulated only; the UI needs a stronger explicit disclaimer.
- Opening the private GitHub link would block a recruiter until repository visibility is changed.
- The current README has strong content but delays the one-sentence product definition and measured proof below “Why this project exists,” weakening the first 15 seconds.

## What most directly maps to Elip's internship requirements

| Elip signal | Current evidence | Gap to close |
| --- | --- | --- |
| LLM prompting, tools, structured outputs | OpenAI-compatible tool/schema path, typed proposal, policy validation, confirmation, audit trail | Configure and visibly test a hosted LLM path or clearly demo a reproducible local-provider run; expand agent evaluation |
| Conversational agents with memory | Append-only preference events, source message, version checks, persistent account state | Persist rejection, add reset/replay UX, test more complex/reversal language |
| Retrieval, ranking, personalization | BM25, MiniLM embeddings, hybrid fusion, cross-encoder, deterministic preferences | Larger held-out corpus, Recall@100, RRF, ablation, ANN experiment |
| Semantic search over changing jobs | Versioned ingestion, fingerprints, content-addressed embeddings, duplicate handling | Expiration/deletion accounting, larger PostgreSQL benchmark, ANN threshold |
| LLM/output evaluation | Provider cases, malformed-output tests, explanation contract | 60–100 agent cases and separate schema/policy/clarification/unsafe-mutation metrics |
| Python backend, SQL, APIs | FastAPI, SQLAlchemy, Alembic, PostgreSQL/pgvector, owner-scoped endpoints | Split the app factory, strengthen observability, pin CI actions |
| Reliability and production shipping | Docker, PostgreSQL CI, Vercel/Supabase deployment, fallbacks, readiness | Distributed rate limiting/metrics are out of scope, but request IDs, demo cleanup, Playwright CI, and configuration readiness are justified |

## Audit conclusion and priority

The current project is already stronger than a screenshot-oriented student demo. Its best proof is the boundary between model interpretation and deterministic ranking, plus versioned evidence/memory and visible degraded modes. The strongest next work is not a rebuild or another visual redesign.

1. Reproduce every committed metric and correct any mismatch.
2. Complete security/test/recruiter documentation and make the repository publicly reviewable only after the final secret audit.
3. Expand agent evaluation and expose honest hosted/local provider behavior.
4. Add larger held-out retrieval data, candidate Recall@100, RRF, and reranker ablations.
5. Add replay/reset/observability improvements and only then refine presentation/screenshots.
