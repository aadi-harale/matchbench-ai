import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import JobEmbedding, JobRow, JobVersion
from .models import EMBED_ID, Models
from .schemas import Job


def digest(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def job_text(job: Job) -> str:
    return f"{job.title}. {job.role}. {', '.join(job.skills)}. {job.description}"


def read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            records = []
            for row in csv.DictReader(stream):
                record: dict[str, Any] = {key: value for key, value in row.items() if value}
                for field in ("skills", "locations", "graduation_years"):
                    if field in record:
                        record[field] = record[field].split("|")
                records.append(record)
            return records
    with path.open(encoding="utf-8-sig") as stream:
        records = json.load(stream)
    if not isinstance(records, list):
        raise ValueError("Job JSON must contain an array of records")
    return records


def ingest(
    session: Session,
    records: Iterable[dict[str, Any]],
    models: Models,
    *,
    lexical_only: bool = False,
) -> dict[str, int | float]:
    started = perf_counter()
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(47824412)"))
    else:
        session.execute(text("BEGIN IMMEDIATE"))
    counts: dict[str, int | float] = dict(inserted=0, updated=0, unchanged=0, duplicates=0, embedded=0)
    wanted: dict[str, str] = {}
    for raw in records:
        job = Job.model_validate(raw)
        content = job.model_dump(mode="json")
        clean = " ".join(job.description.casefold().split())
        fingerprint = digest([job.company.casefold(), job.title.casefold(), sorted(
            location.casefold() for location in job.locations
        ), job.employment, clean])
        row = session.get(JobRow, job.id)
        duplicate = session.scalar(select(JobRow.id).where(
            JobRow.fingerprint == fingerprint, JobRow.id != job.id
        ).limit(1))
        if duplicate:
            counts["duplicates"] += 1
            continue
        previous = session.scalar(select(JobVersion).where(
            JobVersion.job_id == job.id, JobVersion.version == row.current_version
        )) if row else None
        content_hash = digest(content)
        document = job_text(job)
        key = digest([EMBED_ID, document])
        if not lexical_only and session.get(JobEmbedding, key) is None:
            wanted[key] = document
        if previous and previous.content_hash == content_hash and previous.embedding_key == key:
            counts["unchanged"] += 1
            continue
        if row:
            row.fingerprint = fingerprint
            row.current_version += 1
            counts["updated"] += 1
        else:
            row = JobRow(id=job.id, fingerprint=fingerprint, current_version=1)
            session.add(row)
            counts["inserted"] += 1
        session.flush()
        session.add(JobVersion(
            job_id=job.id, version=row.current_version, content_hash=content_hash, embedding_key=key,
            data=content, raw=raw,
        ))
        session.flush()

    if wanted:
        embeddings = models.embed(list(wanted.values()))
        for key, vector in zip(wanted, embeddings, strict=True):
            session.add(JobEmbedding(key=key, model=EMBED_ID, vector=vector.tolist()))
        counts["embedded"] = len(wanted)
    counts["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    return counts


def revisions(session: Session, ids: list[int] | None = None) -> list[JobVersion]:
    statement = select(JobVersion).order_by(JobVersion.job_id)
    if ids is None:
        statement = statement.join(JobRow, (JobRow.id == JobVersion.job_id) &
                                   (JobRow.current_version == JobVersion.version))
    else:
        statement = statement.where(JobVersion.id.in_(ids))
    return list(session.scalars(statement))
