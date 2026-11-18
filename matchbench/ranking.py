import logging
import re
from collections.abc import Callable
from datetime import datetime
from math import isfinite
from time import perf_counter
from typing import Any

import bm25s

from .ingest import job_text
from .models import Models
from .schemas import Algorithm, Evidence, Job, Preferences, Profile, SearchRequest

logger = logging.getLogger(__name__)
TOKEN = re.compile(r"(?u)[a-z0-9][a-z0-9+#.\-]*")
STOP = set("a an and as at at least about by for from i in into it of on or the to with working".split())
ALIASES = {"bangalore": "bengaluru", "gurgaon": "gurugram"}
Cosines = Callable[[list[float]], dict[str, float]]
DEFAULT_CROSS_WEIGHT = 0.2


def tokens(text: str) -> list[str]:
    return [word for token in TOKEN.findall(text.casefold()) if (word := token.strip(".-")) not in STOP]


def city(value: str) -> str:
    key = value.strip().casefold()
    return ALIASES.get(key, key)


def eligibility(job: Job, profile: Profile, preferences: Preferences, search: SearchRequest, at: datetime):
    checks: list[dict[str, str]] = []

    def add(key: str, label: str, state: str) -> None:
        checks.append({"key": key, "label": label, "state": state})

    if job.expires_at and job.expires_at <= at:
        add("expiry", "Posting expired", "fail")
    if job.posted_at and job.posted_at > at:
        add("posted_at", "Posting is scheduled for a later date", "fail")
    if job.experience_min is not None and job.experience_min > 0:
        if profile.years is None:
            add("experience", f"{job.experience_min:g}+ years required. Confirm qualifying experience.", "review")
        else:
            state = "pass" if profile.years >= job.experience_min else "fail"
            add("experience", f"{job.experience_min:g}+ years required · {profile.years:g} years in profile", state)
    if job.experience_max is not None:
        state = "review" if profile.years is None else ("pass" if profile.years <= job.experience_max else "fail")
        add("experience_max", f"At most {job.experience_max:g} years of experience", state)
    wanted = preferences.employment
    if wanted:
        state = "review" if job.employment == "unknown" else ("pass" if job.employment == wanted else "fail")
        add("employment", f"Looking for {wanted} roles · listed as {job.employment}", state)
    if search.employment and job.employment != search.employment:
        add("employment_filter", f"Search is filtered to {search.employment}", "fail")
    if job.company.casefold() in {value.casefold() for value in preferences.denied_companies}:
        add("company", f"{job.company} is excluded by your preferences", "fail")
    if job.role.casefold() in {value.casefold() for value in preferences.denied_roles}:
        add("role", f"{job.role.capitalize()} is excluded by your preferences", "fail")

    known = {city(value) for value in job.locations}
    allowed = {city(value) for value in preferences.locations}
    denied = {city(value) for value in preferences.excluded_locations}
    if search.location and city(search.location) not in known:
        add("location_filter", f"Search is filtered to {search.location}", "fail")
    if search.work_mode and job.work_mode != search.work_mode:
        add("mode_filter", f"Search is filtered to {search.work_mode}", "fail")
    if job.work_mode != "remote":
        if known and known <= denied:
            add("location_denied", f"{', '.join(job.locations)} is excluded by your preferences", "fail")
        if allowed and not preferences.allow_relocation:
            if known:
                state = "pass" if (known - denied) & allowed else "fail"
                add("location", f"{', '.join(job.locations)} · accepted cities are {', '.join(preferences.locations)}",
                    state)
            else:
                add("location", "Posting does not specify a work location", "review")

    if preferences.paid_only or preferences.minimum_stipend is not None:
        minimum = preferences.minimum_stipend or 0
        salary = job.salary_min
        if salary == 0 and job.salary_max == 0 and (preferences.paid_only or minimum > 0):
            add("pay", "Posting is unpaid", "fail")
        elif salary is None or job.currency != "INR" or job.salary_period != "month":
            add("pay", "Confirm monthly pay in INR", "review")
        elif salary < minimum or (salary == 0 and preferences.paid_only):
            ceiling = job.salary_max
            state = "fail" if ceiling is not None and (ceiling < minimum or ceiling == 0) else "review"
            add("pay", f"Listed floor ₹{salary:,.0f}/month · your minimum ₹{minimum:,.0f}", state)
        else:
            add("pay", f"At least ₹{salary:,.0f}/month", "pass")

    if job.graduation_years:
        state = "review" if profile.graduation_year is None else (
            "pass" if profile.graduation_year in job.graduation_years else "fail"
        )
        add("graduation", "Accepted graduation years: " + ", ".join(map(str, job.graduation_years)), state)
    if job.authorization:
        state = "review" if not profile.authorization else (
            "pass" if job.authorization.casefold() in {item.casefold() for item in profile.authorization} else "fail"
        )
        add("authorization", f"Requires {job.authorization} work authorization", state)
    if job.starts_by:
        state = "review" if profile.available_from is None else (
            "pass" if profile.available_from <= job.starts_by else "fail"
        )
        add("availability", f"Must start by {job.starts_by:%d %b %Y}", state)
    status = "fail" if any(row["state"] == "fail" for row in checks) else (
        "review" if any(row["state"] == "review" for row in checks) else "pass"
    )
    return status, checks


def explain(job: Job, profile: Profile, checks: list[dict[str, str]]) -> dict[str, Any]:
    supported: dict[str, Evidence] = {}
    for evidence in profile.evidence:
        if evidence.review == "accepted":
            supported.setdefault(evidence.skill.casefold(), evidence)
    known = set(supported)
    pending = {item.skill.casefold() for item in profile.evidence if item.review == "pending"}
    required = {skill.casefold(): skill for skill in job.skills}
    return {
        "evidence": [supported[skill].model_dump(mode="json") for skill in required if skill in known],
        "missing": [name for skill, name in required.items() if skill not in known | pending],
        "unknowns": [row["label"] for row in checks if row["state"] == "review"]
        + [f"{required[skill]} evidence awaits review" for skill in required if skill in pending - known]
        + (["No compensation is listed"] if job.salary_min is None and
           not any(check["key"] == "pay" for check in checks) else []),
    }


def personalization(job: Job, preferences: Preferences) -> dict[str, float]:
    role = job.role.casefold()
    skills = {skill.casefold() for skill in job.skills}
    preferred = {skill.casefold() for skill in preferences.preferred_skills}
    return {
        "role": 0.45 if role in {value.casefold() for value in preferences.preferred_roles} else (
            -0.45 if role in {value.casefold() for value in preferences.less_roles} else 0.0
        ),
        "technology": 0.35 * len(skills & preferred) / max(1, len(preferred)),
        "location": 0.12 if {city(loc) for loc in job.locations} &
        {city(loc) for loc in preferences.locations} else 0.0,
        "work_mode": 0.08 if job.work_mode in preferences.preferred_work_modes else 0.0,
    }


def top_scores(values: dict[str, float], allowed: set[str], depth: int) -> dict[str, float]:
    top = sorted((key for key in values if key in allowed and isfinite(values[key])),
                 key=lambda key: (-values[key], key))
    return {key: values[key] for key in top[:depth]}


def normalized(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return dict.fromkeys(values, 1.0)
    return {key: (value - low) / (high - low) for key, value in values.items()}


class Corpus:
    def __init__(self, jobs: list[Job]):
        self.jobs = {job.id: job for job in jobs}
        self.documents = {job.id: job_text(job) for job in jobs}
        self.tokens = {key: tokens(doc) for key, doc in self.documents.items()}
        self.lexical = bm25s.BM25(method="lucene") if self.jobs else None
        if self.lexical:
            self.lexical.index(list(self.tokens.values()), show_progress=False)

    def scores(self, query: str, *, keyword: bool) -> dict[str, float]:
        terms = tokens(query)
        if not terms or self.lexical is None:
            return {}
        if keyword:
            query_terms = set(terms)
            return {key: float(len(query_terms.intersection(words))) for key, words in self.tokens.items()}
        return {key: float(score) for key, score in zip(self.jobs, self.lexical.get_scores(terms), strict=True)}


def rank(
    corpus: Corpus, search: SearchRequest, profile: Profile, preferences: Preferences, at: datetime,
    models: Models, cosines: Cosines, *, alpha: float = 0.5, depth: int = 20, timeout: float = 2.5,
    hypothetical: set[str] | None = None, cross_weight: float = DEFAULT_CROSS_WEIGHT,
) -> dict[str, Any]:
    start = perf_counter()
    states = {key: eligibility(job, profile, preferences, search, at) for key, job in corpus.jobs.items()}
    eligible = {key for key, (status, _) in states.items() if status == "pass"}
    filter_ms = (perf_counter() - start) * 1000
    retrieve_start = perf_counter()
    mode = search.algorithm
    fallback = []
    lexical = corpus.scores(search.query, keyword=mode == Algorithm.keyword)
    lexical = {key: value for key, value in lexical.items() if value > 0}
    semantic: dict[str, float] = {}
    if mode not in (Algorithm.keyword, Algorithm.bm25):
        try:
            if not corpus.jobs:
                semantic = {}
            else:
                semantic = cosines(models.query_vector(search.query).tolist())
                if not semantic:
                    raise ValueError("No vectors for this snapshot")
        except Exception as error:
            logger.warning("Embedding retrieval unavailable (%s)", type(error).__name__)
            fallback.append("Embedding search unavailable. Showing BM25 results.")
            mode = Algorithm.bm25
    lexical_top = top_scores(lexical, eligible, 100)
    semantic_top = top_scores(semantic, eligible, 100)
    lex_normal, vec_normal = normalized(lexical_top), normalized(semantic_top)
    if mode in (Algorithm.keyword, Algorithm.bm25):
        base = lex_normal
    elif mode == Algorithm.embedding:
        base = vec_normal
    else:
        lex_weight, vec_weight = ((1 - alpha, alpha) if lex_normal and vec_normal else
                                  (1.0, 0.0) if lex_normal else (0.0, 1.0))
        base = {key: lex_weight * lex_normal.get(key, 0) + vec_weight * vec_normal.get(key, 0)
                for key in sorted(lex_normal.keys() | vec_normal.keys())}
    ordered = sorted(base, key=lambda key: (-base[key], key))
    retrieve_ms = (perf_counter() - retrieve_start) * 1000

    cross: dict[str, float] = {}
    rerank_start = perf_counter()
    if ordered and mode in (Algorithm.rerank, Algorithm.personalized):
        keys = ordered[:depth]
        try:
            results = models.rerank(search.query, [corpus.documents[key] for key in keys], timeout)
            if len(results) != len(keys) or not all(isfinite(result) for result in results):
                raise ValueError("Invalid reranker scores")
            cross = dict(zip(keys, results, strict=True))
        except Exception as error:
            logger.warning("Reranker unavailable (%s)", type(error).__name__)
            fallback.append("Cross-encoder unavailable. Showing hybrid results.")
            mode = Algorithm.hybrid
    rerank_ms = (perf_counter() - rerank_start) * 1000
    cross_normal = normalized(cross)

    def row(key: str, final: float | None) -> dict[str, Any]:
        job = corpus.jobs[key]
        status, checks = states[key]
        matched = explain(job, profile, checks)
        requirements = {skill.casefold() for skill in job.skills}
        tech = len(requirements & (profile.supported_skills | (hypothetical or set()))) / max(1, len(requirements))
        components = personalization(job, preferences)
        return {
            "job": job.model_dump(mode="json"),
            "status": status,
            "checks": checks,
            "explanation": matched,
            "scores": {
                "lexical": lexical.get(key), "semantic": semantic.get(key), "hybrid": base.get(key),
                "reranker": cross.get(key), "skill_coverage": tech,
                "preference_alignment": sum(components.values()), "preference_components": components, "final": final,
            },
            "sources": (["Keyword" if search.algorithm == Algorithm.keyword else "BM25"] if key in lexical_top else [])
            + (["Cosine"] if key in semantic_top else []) + (["Cross-encoder"] if key in cross else []),
        }

    scored = []
    for key in ordered:
        entry = row(key, base[key])
        if key in cross_normal:
            entry["scores"]["final"] = cross_weight * cross_normal[key] + (1 - cross_weight) * base[key]
        if mode == Algorithm.personalized:
            entry["scores"]["final"] = (
                0.70 * entry["scores"]["final"] + 0.12 * entry["scores"]["skill_coverage"]
                + 0.18 * entry["scores"]["preference_alignment"]
            )
        scored.append(entry)
    scored.sort(key=lambda entry: (
        0 if not cross or entry["job"]["id"] in cross else 1, -entry["scores"]["final"], entry["job"]["id"],
    ))
    for position, entry in enumerate(scored, 1):
        entry["rank"] = position
    visible = scored
    if search.strong_only:
        visible = [entry for entry in scored if entry["scores"]["skill_coverage"] >= 0.5
                   and entry["scores"]["final"] >= 0.38
                   and (entry["scores"]["semantic"] or 0) >= 0.25]

    diagnostic_keys = set(corpus.jobs) - eligible
    hidden = [row(key, None) | {"rank": None} for key in sorted(
        diagnostic_keys, key=lambda key: (states[key][0] != "fail", -semantic.get(key, -1),
                                         -lexical.get(key, 0), key)
    )]
    return {
        "matches": visible[:search.limit], "excluded": hidden,
        "ranked": scored,
        "algorithm": mode.value, "requested_algorithm": search.algorithm.value, "warnings": fallback,
        "timing": {"filter_ms": filter_ms, "retrieval_ms": retrieve_ms, "rerank_ms": rerank_ms,
                   "total_ms": (perf_counter() - start) * 1000},
        "counts": {"indexed": len(corpus.jobs), "eligible": len(eligible), "retrieved": len(scored),
                   "excluded": len(hidden)},
    }
