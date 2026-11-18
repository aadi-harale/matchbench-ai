import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import IndexImport, JobEmbedding, JobRow, JobVersion
from .models import EMBED_ID, Models
from .schemas import Job


def digest(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def job_text(job: Job) -> str:
    return f"{job.title}. {job.role}. {', '.join(job.skills)}. {job.description}"


def source_fingerprint(job: Job) -> str:
    return digest([
        job.company.casefold(), job.title.casefold(), sorted(location.casefold() for location in job.locations),
        job.employment, " ".join(job.description.casefold().split()),
    ])


def batches(values: Iterable[str], size: int = 400) -> Iterable[list[str]]:
    values = list(values)
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


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
    prepared = [(Job.model_validate(raw), raw) for raw in records]
    inputs = [(job, raw, source_fingerprint(job)) for job, raw in prepared]
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(47824412)"))
    else:
        session.execute(text("BEGIN IMMEDIATE"))
    counts: dict[str, int | float] = dict(inserted=0, updated=0, unchanged=0, duplicates=0, embedded=0)
    existing: dict[str, JobRow] = {}
    fingerprints: dict[str, set[str]] = {}
    latest: dict[str, tuple[str, str]] = {}
    for fingerprints_batch in batches({item[2] for item in inputs}):
        for uid, key in session.execute(select(JobRow.id, JobRow.fingerprint).where(
            JobRow.fingerprint.in_(fingerprints_batch)
        )):
            fingerprints.setdefault(key, set()).add(uid)
    for id_batch in batches({item[0].id for item in inputs}):
        rows = session.execute(select(JobRow, JobVersion.content_hash, JobVersion.embedding_key).join(
            JobVersion, (JobVersion.job_id == JobRow.id) & (JobVersion.version == JobRow.current_version)
        ).where(JobRow.id.in_(id_batch)))
        for row, content_hash, embedding_key in rows:
            existing[row.id] = row
            latest[row.id] = (content_hash, embedding_key)
            fingerprints.setdefault(row.fingerprint, set()).add(row.id)

    wanted: dict[str, str] = {}
    versions = []
    for job, raw, fingerprint in inputs:
        content = job.model_dump(mode="json")
        row = existing.get(job.id)
        if fingerprints.get(fingerprint, set()) - {job.id}:
            counts["duplicates"] += 1
            continue
        content_hash = digest(content)
        document = job_text(job)
        key = digest([EMBED_ID, document])
        if not lexical_only:
            wanted[key] = document
        if latest.get(job.id) == (content_hash, key):
            counts["unchanged"] += 1
            continue
        if row:
            fingerprints[row.fingerprint].discard(job.id)
            row.fingerprint = fingerprint
            row.current_version += 1
            counts["updated"] += 1
        else:
            row = JobRow(id=job.id, fingerprint=fingerprint, current_version=1)
            session.add(row)
            existing[job.id] = row
            counts["inserted"] += 1
        latest[job.id] = (content_hash, key)
        fingerprints.setdefault(fingerprint, set()).add(job.id)
        versions.append(JobVersion(
            job_id=job.id, version=row.current_version, content_hash=content_hash, embedding_key=key,
            data=content, raw=raw,
        ))

    session.flush()
    session.add_all(versions)
    for key_batch in batches(wanted):
        for cached in session.scalars(select(JobEmbedding.key).where(JobEmbedding.key.in_(key_batch))):
            del wanted[cached]
    if wanted:
        embeddings = models.embed(list(wanted.values()))
        for key, vector in zip(wanted, embeddings, strict=True):
            session.add(JobEmbedding(key=key, model=EMBED_ID, vector=vector.tolist()))
        counts["embedded"] = len(wanted)
    counts["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    session.add(IndexImport(counts=counts))
    return counts


def revisions(session: Session, ids: list[int] | None = None) -> list[JobVersion]:
    statement = select(JobVersion).order_by(JobVersion.job_id)
    if ids is None:
        statement = statement.join(JobRow, (JobRow.id == JobVersion.job_id) &
                                   (JobRow.current_version == JobVersion.version))
    else:
        statement = statement.where(JobVersion.id.in_(ids))
    return list(session.scalars(statement))
