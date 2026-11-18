"""Generate and evaluate the clearly synthetic large retrieval fixture."""
import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import numpy as np

from .benchmark import latency, quality
from .config import DATA, Settings
from .ingest import digest, job_text
from .models import EMBED_ID, RERANK_ID, Models
from .ranking import DEFAULT_CROSS_WEIGHT, Corpus, eligibility, rank
from .schemas import Algorithm, Evidence, Job, Preferences, Profile, SearchRequest

FIXED_TIME = datetime(2026, 11, 18, tzinfo=UTC)
INTENTS = [
    ("agent-backend", "backend", ["Python", "FastAPI", "LLM agents", "Pydantic"],
     ["tool-calling agent backend", "LLM agent API internship", "structured agent tools", "Python agent service",
      "agent memory backend", "validated tool calls", "AI workflow API", "agent reliability internship",
      "conversational agent backend", "typed LLM tools"]),
    ("semantic-search", "search", ["Python", "semantic search", "embeddings", "BM25"],
     ["semantic search internship", "hybrid retrieval engineer", "BM25 and embeddings", "search relevance internship",
      "vector retrieval role", "information retrieval intern", "dense sparse search", "ranking candidate retrieval",
      "embedding search backend", "relevance engineering internship"]),
    ("data-platform", "data", ["Python", "SQL", "ETL", "PostgreSQL"],
     ["data platform internship", "ETL Python SQL", "warehouse pipeline intern", "data quality backend",
      "batch ingestion engineer", "analytics data platform", "SQL pipeline internship", "data reliability intern",
      "schema maintenance role", "Python warehouse backend"]),
    ("frontend-access", "frontend", ["React", "TypeScript", "JavaScript", "accessibility"],
     ["React accessibility internship", "TypeScript frontend role", "accessible web application", "frontend design systems",
      "React product intern", "web accessibility engineer", "JavaScript UI internship", "frontend performance role",
      "TypeScript component systems", "inclusive frontend internship"]),
    ("platform-sre", "platform", ["Docker", "Linux", "AWS", "Kubernetes"],
     ["platform reliability internship", "Docker Linux intern", "cloud infrastructure role", "Kubernetes platform intern",
      "SRE internship", "deployment reliability engineer", "AWS operations intern", "container platform role",
      "production diagnostics internship", "infrastructure automation"]),
    ("application-security", "security", ["Python", "security", "SQL", "Linux"],
     ["application security internship", "secure Python backend", "security engineering intern", "API security role",
      "threat modeling internship", "backend security testing", "secure SQL application", "privacy security intern",
      "vulnerability engineering", "security automation Python"]),
    ("mobile", "mobile", ["Java", "mobile", "APIs", "Git"],
     ["mobile engineering internship", "Android Java intern", "mobile API integration", "client application intern",
      "mobile product engineer", "Android networking role", "mobile reliability internship", "Java app development",
      "mobile platform intern", "Android Git workflow"]),
    ("product-analytics", "data", ["SQL", "Python", "analytics", "experimentation"],
     ["product analytics internship", "SQL experimentation role", "analytics engineer intern", "product metrics Python",
      "A/B test analysis", "growth analytics internship", "product data intern", "experiment measurement role",
      "funnel analytics SQL", "decision science internship"]),
    ("evaluation", "evaluation", ["Python", "pytest", "LLM evaluation", "statistics"],
     ["LLM evaluation internship", "model quality engineer", "agent evaluation harness", "Python evals role",
      "retrieval evaluation intern", "quality benchmark engineer", "pytest evaluation role", "AI output measurement",
      "model regression internship", "evaluation dataset engineer"]),
    ("postgres", "platform", ["PostgreSQL", "SQL", "Alembic", "SQLAlchemy"],
     ["PostgreSQL backend internship", "SQLAlchemy Alembic role", "database reliability intern", "schema migration engineer",
      "Postgres performance internship", "SQL database backend", "migration tooling role", "transaction design internship",
      "relational data engineer", "PostgreSQL API intern"]),
    ("recommendations", "search", ["Python", "recommendation systems", "ranking", "embeddings"],
     ["recommendation systems internship", "personalized ranking role", "candidate job matching", "recommender engineer intern",
      "ranking personalization", "embedding recommendations", "matching system internship", "preference-aware ranking",
      "recommendation evaluation", "Python recommender backend"]),
    ("backend-reliability", "backend", ["Python", "FastAPI", "Redis", "Docker"],
     ["backend reliability internship", "FastAPI Redis role", "Python service engineering", "API operations intern",
      "reliable backend systems", "Docker API internship", "service diagnostics role", "backend production engineer",
      "Python integration backend", "FastAPI platform intern"]),
]


def generated_records() -> tuple[list[dict], list[dict], list[dict]]:
    jobs: list[dict] = []
    queries: list[dict] = []
    judgments: list[dict] = []
    for topic_index, (topic, role, skills, phrases) in enumerate(INTENTS):
        topic_jobs = []
        for variant in range(25):
            if variant < 5:
                level, selected_skills = "focused", skills
            elif variant < 12:
                level, selected_skills = "related", skills[:3]
            elif variant < 18:
                level, selected_skills = "adjacent", skills[:2]
            else:
                level, selected_skills = "broad", ["Python", "Git"]
            job_id = f"large-{topic}-{variant + 1:02d}"
            topic_jobs.append(job_id)
            jobs.append({
                "id": job_id,
                "source": "synthetic evaluation fixture",
                "company": f"Synthetic {topic.replace('-', ' ').title()} Lab {variant + 1:02d}",
                "title": f"{role.title()} Engineering Intern — {level.title()} {variant + 1:02d}",
                "description": (
                    f"Synthetic posting for {topic.replace('-', ' ')} work. Build and evaluate "
                    f"{', '.join(selected_skills)} systems with documented tests, APIs, and operational checks. "
                    f"Fixture variation {variant + 1:02d}; this record is not a real opening."
                ),
                "locations": [["Bengaluru"], ["Gurugram"], ["Pune"], ["Remote"]][variant % 4],
                "work_mode": "remote" if variant % 4 == 3 else "hybrid",
                "employment": "internship",
                "role": role,
                "skills": selected_skills,
                "experience_min": 0,
                "salary_min": 25000 + (variant % 5) * 5000,
                "salary_max": 40000 + (variant % 5) * 5000,
                "salary_period": "month",
                "currency": "INR",
                "illustrative": True,
            })
        split = "development" if topic_index < 2 else "heldout"
        for query_index, text in enumerate(phrases, 1):
            query_id = f"{topic}-q{query_index:02d}"
            queries.append({
                "id": query_id, "topic": topic, "split": split, "text": text,
                "preferred_role": role, "evidence_skills": skills[:2],
            })
            grades = {}
            for variant, job_id in enumerate(topic_jobs):
                if variant < 5:
                    grades[job_id] = 3
                elif variant < 12:
                    grades[job_id] = 2
                elif variant < 18:
                    grades[job_id] = 1
            judgments.append({"query_id": query_id, "grades": grades})
    return jobs, queries, judgments


def write_generated() -> None:
    jobs, queries, judgments = generated_records()
    for name, value in (
        ("eval_jobs_large.json", jobs),
        ("eval_queries_large.json", queries),
        ("eval_judgments_large.json", judgments),
    ):
        (DATA / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(settings: Settings) -> dict:
    jobs_raw = json.loads((DATA / "eval_jobs_large.json").read_text(encoding="utf-8"))
    queries = json.loads((DATA / "eval_queries_large.json").read_text(encoding="utf-8"))
    judgments = {row["query_id"]: row["grades"] for row in json.loads(
        (DATA / "eval_judgments_large.json").read_text(encoding="utf-8")
    )}
    jobs = [Job.model_validate(row) for row in jobs_raw]
    corpus = Corpus(jobs)
    models = Models(settings.model_dir)
    vectors = models.embed([job_text(job) for job in jobs])
    vector_by_id = dict(zip((job.id for job in jobs), vectors, strict=True))

    def cosines(query_vector: list[float]) -> dict[str, float]:
        query = np.asarray(query_vector, dtype=np.float32)
        return {key: float(vector @ query) for key, vector in vector_by_id.items()}

    for query in queries:
        models.query_vector(query["text"])
    models.load("rank")

    def observe(query: dict, method: Algorithm, alpha: float):
        evidence = [Evidence(id=f"fixture-{index}", skill=skill, excerpt="Synthetic evidence fixture",
                             source="synthetic evaluation profile", method="candidate", review="accepted")
                    for index, skill in enumerate(query["evidence_skills"], 1)]
        profile = Profile(years=0, evidence=evidence)
        preferences = Preferences(employment="internship", preferred_roles=[query["preferred_role"]])
        result = rank(corpus, SearchRequest(query=query["text"], algorithm=method), profile, preferences,
                      FIXED_TIME, models, cosines, alpha=alpha, timeout=25)
        order = [row["job"]["id"] for row in result["ranked"]]
        grades = judgments[query["id"]]
        relevant = {key for key, grade in grades.items() if grade >= 2}
        return {"quality": quality(order, grades), "timing": result["timing"],
                "candidate_recall_at_100": len(set(order[:100]) & relevant) / len(relevant)}

    development = [query for query in queries if query["split"] == "development"]
    heldout = [query for query in queries if query["split"] == "heldout"]
    validation = []
    for alpha in [0.25, 0.5, 0.75]:
        rows = [observe(query, Algorithm.hybrid, alpha) for query in development]
        validation.append({"alpha": alpha, "ndcg_at_10": statistics.mean(
            row["quality"]["ndcg_at_10"] for row in rows
        )})
    alpha = max(validation, key=lambda row: (row["ndcg_at_10"], -abs(row["alpha"] - 0.5)))["alpha"]

    def summarize(method: Algorithm, rows: list[dict]) -> dict:
        return {
            "algorithm": method.value,
            **{key: round(statistics.mean(row["quality"][key] for row in rows), 6)
               for key in rows[0]["quality"]},
            "candidate_recall_at_100": round(statistics.mean(
                row["candidate_recall_at_100"] for row in rows
            ), 6),
            "latency": {stage: latency([row["timing"][stage] for row in rows])
                        for stage in ("retrieval_ms", "rerank_ms", "total_ms")},
        }

    started = perf_counter()
    ranking = [summarize(method, [observe(query, method, alpha) for query in heldout]) for method in Algorithm]

    def rrf(query: dict, k: int):
        profile = Profile(years=0)
        preferences = Preferences(employment="internship", preferred_roles=[query["preferred_role"]])
        allowed = {job.id for job in jobs if eligibility(
            job, profile, preferences, SearchRequest(query=query["text"]), FIXED_TIME
        )[0] == "pass"}
        lexical = corpus.scores(query["text"], keyword=False)
        semantic = cosines(models.query_vector(query["text"]).tolist())
        orders = [
            sorted((key for key in lexical if key in allowed and lexical[key] > 0),
                   key=lambda key: (-lexical[key], key))[:100],
            sorted((key for key in semantic if key in allowed), key=lambda key: (-semantic[key], key))[:100],
        ]
        scores: dict[str, float] = {}
        for order in orders:
            for position, key in enumerate(order, 1):
                scores[key] = scores.get(key, 0) + 1 / (k + position)
        order = sorted(scores, key=lambda key: (-scores[key], key))
        grades = judgments[query["id"]]
        relevant = {key for key, grade in grades.items() if grade >= 2}
        return {"quality": quality(order, grades),
                "candidate_recall_at_100": len(set(order[:100]) & relevant) / len(relevant)}

    rrf_validation = []
    for k in [10, 30, 60, 100]:
        rows = [rrf(query, k) for query in development]
        rrf_validation.append({"k": k, "ndcg_at_10": statistics.mean(
            row["quality"]["ndcg_at_10"] for row in rows
        )})
    rrf_k = max(rrf_validation, key=lambda row: (row["ndcg_at_10"], -abs(row["k"] - 60)))["k"]
    rrf_rows = [rrf(query, rrf_k) for query in heldout]
    return {
        "scope": "Deterministic synthetic retrieval fixture. No real openings, users, or hiring outcomes.",
        "generated_at": datetime.now(UTC).isoformat(),
        "jobs": len(jobs), "development_queries": len(development), "heldout_queries": len(heldout),
        "topics": len(INTENTS), "dataset_hash": digest(jobs_raw),
        "queries_hash": digest(queries), "judgments_hash": digest(judgments),
        "embedding_model": EMBED_ID, "reranker_model": RERANK_ID,
        "cross_encoder_weight": DEFAULT_CROSS_WEIGHT, "alpha": alpha,
        "validation": validation, "ranking": ranking,
        "rrf": {"k": rrf_k, "validation": rrf_validation,
                **{key: round(statistics.mean(row["quality"][key] for row in rrf_rows), 6)
                   for key in rrf_rows[0]["quality"]},
                "candidate_recall_at_100": round(statistics.mean(
                    row["candidate_recall_at_100"] for row in rrf_rows
                ), 6)},
        "elapsed_seconds": round(perf_counter() - started, 3),
        "timing_scope": "Warm local CPU models and cached query vectors; in-process exact cosine.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", type=Path, default=DATA / "large_benchmark.json")
    args = parser.parse_args()
    if args.generate:
        write_generated()
    report = run(Settings())
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "jobs", "development_queries", "heldout_queries", "alpha", "ranking", "rrf", "elapsed_seconds"
    )}, indent=2))


if __name__ == "__main__":
    main()
