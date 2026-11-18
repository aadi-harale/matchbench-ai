import argparse
import json
import platform
import statistics
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from .agent import agent_proposal, local_proposal
from .config import DATA, Settings
from .db import engine_for, sessions
from .ingest import digest, revisions
from .models import EMBED_ID, RERANK_ID, Models
from .ranking import Corpus, explain, rank
from .schemas import Algorithm, Evidence, Job, Preferences, Profile, SearchRequest
from .search import cosine_resolver
from .state import load_json

FIXED_TIME = datetime(2026, 11, 18, tzinfo=UTC)
NAMES = {
    Algorithm.keyword: "Keyword overlap", Algorithm.bm25: "BM25",
    Algorithm.embedding: "Embeddings", Algorithm.hybrid: "Hybrid",
    Algorithm.rerank: "Hybrid + cross-encoder", Algorithm.personalized: "Hybrid + personalization",
}


def quality(order: list[str], grades: dict[str, int]) -> dict[str, float]:
    from math import log2

    relevant = {key for key, grade in grades.items() if grade >= 2}
    p5 = len(set(order[:5]) & relevant) / 5
    r10 = len(set(order[:10]) & relevant) / max(1, len(relevant))
    mrr = next((1 / (index + 1) for index, key in enumerate(order) if key in relevant), 0.0)
    dcg = sum((2 ** grades.get(key, 0) - 1) / log2(index + 2) for index, key in enumerate(order[:10]))
    ideal = sum((2 ** grade - 1) / log2(index + 2)
                for index, grade in enumerate(sorted(grades.values(), reverse=True)[:10]))
    return dict(precision_at_5=p5, recall_at_10=r10, mrr=mrr, ndcg_at_10=dcg / ideal if ideal else 0.0)


def latency(items: list[float]) -> dict[str, float]:
    return {"p50": round(float(np.quantile(items, .5)), 3), "p95": round(float(np.quantile(items, .95)), 3)}


def contract_evaluation(jobs: list[Job], settings: Settings, live: bool) -> dict[str, Any]:
    cases = []
    for job in jobs[:36]:
        evidence = Evidence(id="known-1", skill=job.skills[0], excerpt="Synthetic contract fixture",
                            source="evaluation", method="candidate", review="accepted")
        profile = Profile(evidence=[evidence])
        result = explain(job, profile, [])
        expected_missing = {skill.casefold() for skill in job.skills[1:]}
        actual = {skill.casefold() for skill in result["missing"]}
        evidence_ids = [item["id"] for item in result["evidence"]]
        cases.append({
            "id": job.id, "grounded": set(evidence_ids) == {evidence.id}, "missing": actual == expected_missing,
            "consistent": result == explain(job, profile, []),
        })
    messages = load_json("agent_cases.json")

    def expected_change(proposal, case):
        if case["field"] is None:
            return not proposal.changes and bool(proposal.question)
        return any(patch.field == case["field"] and patch.operation == case["operation"]
                   and str(patch.value).casefold() == str(case["value"]).casefold() for patch in proposal.changes)

    hosted: dict[str, Any] | None = None
    if live:
        if not settings.llm_enabled:
            raise RuntimeError("--live-llm requires OPENAI_API_KEY or an OpenAI-compatible LLM_BASE_URL")
        items = []
        for case in messages:
            proposal, provider, usage, traces = agent_proposal(settings, Preferences(), case["message"], demo=False)
            valid = provider == settings.llm_model and any(
                trace["name"] == "propose_preference_change" and trace["status"] == "validated" for trace in traces
            )
            items.append({"message": case["message"], "valid": valid, "correct": valid and expected_change(proposal, case),
                          "provider": provider, "usage": usage, "tool_calls": traces,
                          "changes": [patch.model_dump(mode="json") for patch in proposal.changes]})
        hosted = {"model": settings.llm_model, "mode": settings.llm_mode,
                  "cases": len(items), "valid": sum(row["valid"] for row in items),
                  "correct": sum(row["correct"] for row in items), "items": items}
    return {
        "explanation_cases": len(cases), "grounded": sum(row["grounded"] for row in cases),
        "missing_skill_correct": sum(row["missing"] for row in cases),
        "consistent": sum(row["consistent"] for row in cases),
        "unsupported_claim_rate": sum(not row["grounded"] for row in cases) / len(cases),
        "local_preference_cases": len(messages),
        "local_preferences_correct": sum(expected_change(local_proposal(case["message"]), case) for case in messages),
        "hosted_llm": hosted,
    }


def run_benchmark(settings: Settings, live: bool = False) -> dict[str, Any]:
    engine = engine_for(settings.database_url)
    models = Models(settings.model_dir)
    profile = Profile.model_validate(load_json("demo_profile.json"))
    source = load_json("judgments.json")
    dataset = load_json("jobs.json")
    with sessions(engine)() as session:
        rows = revisions(session)
        jobs = [Job.model_validate(row.data) for row in rows if row.job_id in {item["id"] for item in dataset}]
        if len(jobs) != len(dataset):
            raise RuntimeError("Ingest the versioned benchmark fixture before running evaluation")
        if sorted(digest(job.model_dump(mode="json")) for job in jobs) != sorted(
            digest(Job.model_validate(item).model_dump(mode="json")) for item in dataset
        ):
            raise RuntimeError("The database fixture differs from the versioned benchmark corpus")
        with TemporaryDirectory() as temp:
            corpus = Corpus(jobs)
            assert corpus.lexical is not None
            corpus.lexical.save(temp)
            lexical_bytes = sum(path.stat().st_size for path in Path(temp).rglob("*") if path.is_file())
        cosines = cosine_resolver(session, [row for row in rows if row.job_id in corpus.jobs])
        trials = [
            (family, query, Preferences(employment="internship", preferred_roles=[family["preferred_role"]]))
            for family in source for query in family["queries"]
        ]
        allowed_labels = {job.id for job in jobs if job.employment == "internship"
                          and (job.expires_at is None or job.expires_at > FIXED_TIME)}
        for _, query, _ in trials:
            models.query_vector(query)
        models.load("rank")
        vector_bytes = 4 * 384 * len(cosines(models.query_vector(trials[0][1]).tolist()))

        def trial(item, method: Algorithm, alpha: float, depth: int = 20):
            family, query, preferences = item
            result = rank(corpus, SearchRequest(query=query, algorithm=method), profile, preferences, FIXED_TIME,
                          models, cosines, alpha=alpha, depth=depth, timeout=25)
            if result["warnings"]:
                raise RuntimeError(f"Benchmark cannot publish degraded {method} measurements: {result['warnings']}")
            order = [row["job"]["id"] for row in result["ranked"]]
            grades = {key: value for key, value in family["grades"].items() if key in allowed_labels}
            return {"topic": family["topic"], "quality": quality(order, grades), "timing": result["timing"],
                    "pairs": sum(row["scores"]["reranker"] is not None for row in result["ranked"])}

        development = [item for item in trials if item[0]["split"] == "development"]
        holdout = [item for item in trials if item[0]["split"] == "holdout"]
        validation = [
            {"alpha": alpha, "ndcg": statistics.mean(trial(item, Algorithm.hybrid, alpha)["quality"]["ndcg_at_10"]
                                                     for item in development)}
            for alpha in [0.25, 0.5, 0.75]
        ]
        alpha = max(validation, key=lambda sample: (sample["ndcg"], -abs(sample["alpha"] - .5)))["alpha"]

        def summarize(method, observations):
            quality_keys = list(observations[0]["quality"])
            return {
                "algorithm": method.value, "name": NAMES[method],
                **{key: round(statistics.mean(row["quality"][key] for row in observations), 6)
                   for key in quality_keys},
                "latency": {stage: latency([row["timing"][stage] for row in observations])
                            for stage in ("filter_ms", "retrieval_ms", "rerank_ms", "total_ms")},
                "mean_reranker_pairs": round(statistics.mean(row["pairs"] for row in observations), 2),
            }

        runs = {method: [trial(item, method, alpha) for item in holdout] for method in Algorithm}
        table = [summarize(method, observations) for method, observations in runs.items()]
        depth_curve = [
            {"depth": depth, **summarize(Algorithm.rerank, runs[Algorithm.rerank] if depth == 20 else
                                         [trial(item, Algorithm.rerank, alpha, depth) for item in holdout])}
            for depth in [20, 50, 100]
        ]

    groups: dict[str, list[float]] = {}
    for before, after in zip(runs[Algorithm.embedding], runs[Algorithm.personalized], strict=True):
        groups.setdefault(before["topic"], []).append(after["quality"]["ndcg_at_10"] - before["quality"]["ndcg_at_10"])
    cluster_means = [statistics.mean(values) for values in groups.values()]
    rng = Random(19)
    interval = np.quantile(
        [statistics.mean(rng.choices(cluster_means, k=len(cluster_means))) for _ in range(2000)], [.025, .975]
    )
    return {
        "dataset": "Curated illustrative job fixtures with explicit per-topic grades",
        "scope": "Graded relevance on curated fixtures. All omitted pairs in a topic were judged grade 0.",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_hash": digest(dataset), "judgments_hash": digest(source),
        "jobs": len(jobs), "indexed_vectors": vector_bytes // (4 * 384),
        "index_bytes": lexical_bytes + vector_bytes, "lexical_artifact_bytes": lexical_bytes,
        "vector_payload_bytes": vector_bytes, "queries": len(holdout),
        "development_queries": len(development), "judgments": len(holdout) * len(jobs),
        "nonzero_judgments": sum(len(item[0]["grades"]) for item in holdout),
        "heldout_topics": len(groups), "embedding_model": EMBED_ID, "reranker_model": RERANK_ID,
        "device": f"{platform.system()} {platform.machine()} · {platform.processor() or 'CPU'}",
        "database": engine.dialect.name, "python": platform.python_version(), "alpha": alpha,
        "timing_scope": "Warm models and cached query vectors. Stage timing covers in-process ranking and vector lookup.",
        "validation": validation, "ranking": table, "rerank_depths": depth_curve,
        "paired_cluster_bootstrap_ndcg_delta": [round(float(value), 6) for value in interval],
        "contracts": contract_evaluation(jobs, settings, live),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-llm", action="store_true")
    parser.add_argument("--contracts-only", action="store_true")
    args = parser.parse_args()
    output = args.output or DATA / ("agent_benchmark.json" if args.contracts_only else "benchmark.json")
    if args.contracts_only:
        jobs = sorted((Job.model_validate(job) for job in load_json("jobs.json")), key=lambda job: job.id)
        report = contract_evaluation(jobs, Settings(), args.live_llm)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({key: value if key != "hosted_llm" or value is None else {
            k: v for k, v in value.items() if k != "items"
        } for key, value in report.items()}, indent=2))
        return
    report = run_benchmark(Settings(), args.live_llm)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"queries": report["queries"], "jobs": report["jobs"], "ranking": report["ranking"]}, indent=2))


if __name__ == "__main__":
    main()
