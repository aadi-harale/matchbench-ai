from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import Decision, JobEmbedding, JobVersion, Run, User
from .ingest import revisions
from .models import EMBED_ID, RERANK_ID, Models
from .ranking import Corpus, rank
from .schemas import Counterfactual, Job, SearchRequest
from .state import apply_changes, preference_at, profile_at

DEFAULT_QUERY = "AI/backend internships working on agents and search"


@lru_cache(maxsize=4)
def corpus_for(documents: tuple[str, ...]) -> Corpus:
    return Corpus([Job.model_validate_json(document) for document in documents])


def cosine_resolver(session: Session, rows: list[JobVersion]):
    jobs = {row.id: row.job_id for row in rows}
    keys = list(jobs)
    postgres = session.bind and session.bind.dialect.name == "postgresql"

    def scores(query: list[float]) -> dict[str, float]:
        statement = (
            select(JobVersion.id).join(JobEmbedding, JobEmbedding.key == JobVersion.embedding_key)
            .where(JobVersion.id.in_(keys), JobEmbedding.model == EMBED_ID)
        )
        if postgres:
            similarity = 1 - JobEmbedding.vector.cosine_distance(query)
            # Keep the BM25 fallback usable when a database-side vector operator
            # is unavailable. PostgreSQL otherwise leaves the whole request
            # transaction aborted after the caught retrieval error.
            with session.begin_nested():
                # Supabase installs pgvector in `extensions`, while local
                # Postgres commonly installs it in `public`. SET LOCAL works
                # with transaction poolers and makes both layouts resolvable.
                session.execute(text("SET LOCAL search_path TO public, extensions"))
                results = session.execute(statement.add_columns(similarity)).all()
            return {jobs[key]: float(value) for key, value in results}
        results = session.execute(statement.add_columns(JobEmbedding.vector)).all()
        if not results:
            return {}
        matrix = np.asarray([row[1] for row in results], dtype=np.float32)
        similarities = matrix @ np.asarray(query, dtype=np.float32)
        return {jobs[entry[0]]: float(value) for entry, value in zip(results, similarities, strict=True)}

    return scores


def execute(
    session: Session, user: User, search: SearchRequest, models: Models, timeout: float,
    *, alpha: float = 0.5,
) -> dict[str, Any]:
    profile_version, profile = profile_at(session, user)
    version, preferences = preference_at(session, user)
    rows = revisions(session)
    at = datetime.now(UTC)
    corpus = corpus_for(tuple(Job.model_validate(row.data).model_dump_json() for row in rows))
    result = rank(corpus, search, profile, preferences, at, models, cosine_resolver(session, rows),
                  alpha=alpha, timeout=timeout)
    matches, hidden = result.pop("ranked"), result["excluded"]
    visible = [entry["job"]["id"] for entry in result["matches"]]
    context = {
        "search": search.model_dump(mode="json"), "at": at.isoformat(), "job_revisions": [row.id for row in rows],
        "weights": {"vector": alpha, "cross_encoder": 0.6, "skill_coverage": 0.12, "preferences": 0.18},
        "rerank_depth": 20, "embedding_model": EMBED_ID, "reranker_model": RERANK_ID,
        "visible": visible, **{key: value for key, value in result.items() if key not in {"matches", "excluded"}},
    }
    run = Run(user_id=user.id, profile_version=profile_version, preference_version=version, context=context)
    session.add(run)
    session.flush()
    session.add_all([
        Decision(run_id=run.id, job_id=entry["job"]["id"], position=index, result=entry)
        for index, entry in enumerate(matches + hidden)
    ])
    return result | {"run_id": run.id, "preference_version": version, "profile_version": profile_version}


def replay(session: Session, run: Run) -> dict[str, Any]:
    entries = list(session.scalars(select(Decision).where(Decision.run_id == run.id).order_by(Decision.position)))
    visible = set(run.context["visible"])
    return {**run.context, "run_id": run.id, "profile_version": run.profile_version,
            "preference_version": run.preference_version,
            "matches": [row.result for row in entries if row.job_id in visible],
            "excluded": [row.result for row in entries if row.result["status"] != "pass"]}


def counterfactual(
    session: Session, user: User, run: Run, action: Counterfactual, models: Models, timeout: float,
) -> dict[str, Any]:
    from .schemas import PreferencePatch

    original = session.scalar(select(Decision).where(Decision.run_id == run.id, Decision.job_id == action.job_id))
    if not original:
        raise ValueError("Select a job in the recorded match run.")
    _, profile = profile_at(session, user, run.profile_version)
    _, preferences = preference_at(session, user, run.preference_version)
    rows = revisions(session, run.context["job_revisions"])
    search = SearchRequest.model_validate(run.context["search"] | {"algorithm": run.context["algorithm"]})
    job = Job.model_validate(original.result["job"])
    hypothetical: set[str] = set()
    patches: list[PreferencePatch] = []
    if action.change == "add_skill":
        if not action.value or action.value.casefold() not in {skill.casefold() for skill in job.skills}:
            raise ValueError("Choose a skill named in the job requirements.")
        hypothetical.add(action.value.casefold())
    elif action.change == "allow_location":
        if not action.value or action.value not in job.locations:
            raise ValueError("Choose a city named in the posting.")
        patches.extend([
            PreferencePatch(field="excluded_locations", operation="remove", value=action.value),
            PreferencePatch(field="locations", operation="add", value=action.value),
        ])
    elif action.change == "remove_role_exclusion":
        patches.append(PreferencePatch(field="denied_roles", operation="remove", value=job.role))
    else:
        patches.extend([
            PreferencePatch(field="minimum_stipend", operation="clear"),
            PreferencePatch(field="paid_only", operation="clear"),
        ])
    changed = apply_changes(preferences, patches)
    result = rank(
        corpus_for(tuple(Job.model_validate(row.data).model_dump_json() for row in rows)),
        search, profile, changed, datetime.fromisoformat(run.context["at"]),
        models, cosine_resolver(session, rows), alpha=run.context["weights"]["vector"],
        depth=run.context["rerank_depth"], timeout=timeout, hypothetical=hypothetical,
    )
    if result["algorithm"] != run.context["algorithm"]:
        raise RuntimeError("This run requires a model that is temporarily unavailable. Retry the comparison.")
    after = next((item for item in result["ranked"] + result["excluded"] if item["job"]["id"] == job.id), None)

    def summarize(entry):
        if entry is None:
            return {"status": "outside pool", "rank": None, "skill_coverage": None, "checks": []}
        return {"status": entry["status"], "rank": entry["rank"],
                "skill_coverage": entry["scores"]["skill_coverage"], "checks": entry["checks"]}

    return {"before": summarize(original.result), "after": summarize(after),
            "query": search.query, "corpus_size": len(rows), "hypothesis": action.model_dump(mode="json")}
