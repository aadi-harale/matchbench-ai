"""Measure index churn on generated records in an isolated SQLite database."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .benchmark import latency
from .config import DATA, Settings, validated_alpha
from .db import Base, engine_for, sessions
from .ingest import ingest, revisions
from .models import Models
from .ranking import Corpus, rank
from .schemas import Job, Preferences, Profile, SearchRequest
from .search import cosine_resolver
from .state import load_json


def run(size: int, settings: Settings) -> dict:
    models = Models(settings.model_dir)
    templates = [item for item in load_json("jobs.json") if not item.get("expires_at")]
    focuses = ["service diagnostics", "query analysis", "batch ownership", "reliability checks",
               "schema maintenance", "customer onboarding", "integration validation", "operational reporting"]
    records = []
    for index in range(size):
        template = templates[index % len(templates)]
        records.append(template | {
            "id": f"load-{index:05d}", "source": "generated load fixture",
            "company": f"Load test team {index // len(templates) + 1:03d}",
            "description": template["description"] + f" Rotation focus: {focuses[index % len(focuses)]}.",
        })
    with TemporaryDirectory() as temp:
        db_path = Path(temp) / "load.db"
        engine = engine_for(f"sqlite:///{db_path.as_posix()}")
        Base.metadata.create_all(engine)
        factory = sessions(engine)
        try:
            with factory.begin() as session:
                initial = ingest(session, records, models)
            with factory.begin() as session:
                repeat = ingest(session, records, models)
            count = min(64, size // 2)
            updated = [row | {"work_mode": "hybrid" if row["work_mode"] != "hybrid" else "on-site"}
                       for row in records[:count]]
            changed = [row | {"description": row["description"] + f" Own release batch {index}."}
                       for index, row in enumerate(records[count:count * 2])]
            with factory.begin() as session:
                delta = ingest(session, updated + changed, models)
            with factory() as session:
                rows = revisions(session)
                corpus = Corpus([Job.model_validate(row.data) for row in rows])
                resolver = cosine_resolver(session, rows)
                profile = Profile.model_validate(load_json("demo_profile.json"))
                prefs = Preferences.model_validate(load_json("demo_preferences.json"))
                prompts = [query for family in load_json("judgments.json") for query in family["queries"]][:30]
                times: dict[str, list[float]] = {}
                for query in prompts:
                    models.query_vector(query)
                models.load("rank")
                for query in prompts:
                    search = SearchRequest(query=query)
                    result = rank(corpus, search, profile, prefs, datetime.now(UTC), models, resolver,
                                  alpha=validated_alpha(), timeout=20.0)
                    if result["warnings"]:
                        raise RuntimeError(result["warnings"])
                    for field, value in result["timing"].items():
                        times.setdefault(field, []).append(value)
                return {
                    "scope": "Generated workload on embedded SQLite with exact vector scores. No relevance claims.",
                    "jobs": len(rows), "queries": len(prompts), "database_bytes": db_path.stat().st_size,
                    "initial": initial, "identical_reimport": repeat, "change_batch": delta,
                    "metadata_only_updates": count, "description_updates": count,
                    "latency": {field: latency(values) for field, values in times.items()},
                    "timing_scope": "Warm model and query cache; database vector reads and ranking included.",
                }
        finally:
            engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=3072)
    parser.add_argument("--output", type=Path, default=DATA / "load_benchmark.json")
    args = parser.parse_args()
    if not 2 <= args.size <= 50000:
        parser.error("--size must be between 2 and 50000")
    result = run(args.size, Settings())
    body = json.dumps(result, indent=2)
    args.output.write_text(body + "\n", encoding="utf-8")
    print(body)


if __name__ == "__main__":
    main()
