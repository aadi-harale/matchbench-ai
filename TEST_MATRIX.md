# Test matrix

| Layer | What is verified | Command / CI |
| --- | --- | --- |
| Static Python | Ruff lint and mypy types | `ruff check matchbench migrations tests`; `mypy matchbench` |
| Unit | eligibility, exact terms, evidence grounding, parser failures, ranking fallbacks, agent policy, fairness invariance, synthetic fixture splits | `pytest -q tests/test_core.py` |
| API | auth/ownership, preference confirmation and rejection, profile versions, feedback, replay, counterfactual, reset, export/delete, observability, ingestion reuse | `pytest -q tests/test_api.py` |
| PostgreSQL | migrations, pgvector path, RLS-compatible backend behavior | GitHub Actions PostgreSQL/pgvector service |
| Frontend | TypeScript and production bundle | `npm run check --prefix frontend`; `npm run build --prefix frontend` |
| Browser | recruiter walkthrough, exact replay, rejected role, counterfactual, persistence, reject/reset, keyboard focus, dark mode | `npm run test:e2e --prefix frontend` at 320/768/1024/1440 px |
| Container | image build, migration, ingestion, `/ready`, bundled frontend | GitHub Actions Docker Compose job |
| Ranking | six methods, Recall@20/100, RRF, reranker grid, hashes, stage latency | `python -m matchbench.benchmark` |
| Larger retrieval | 300 jobs, 20 development and 100 held-out synthetic queries | `python -m matchbench.large_benchmark --generate` |
| Agent/evidence | 36 evidence contracts and 72 preference/safety cases | `python -m matchbench.benchmark --contracts-only` |
| Load | 3,072 jobs, identical re-import, metadata/description churn | `python -m matchbench.load_benchmark --size 3072` |

The browser suite uses the actual API and persisted state. Provider tests are not silently mocked: a live-model result is emitted only when credentials and a provider are configured.
