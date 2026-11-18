from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> str:
    return datetime.now(UTC).isoformat()


def identifier() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password: Mapped[str | None] = mapped_column(String(256))
    demo: Mapped[bool] = mapped_column(default=False)
    session_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)


class ProfileVersion(Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (UniqueConstraint("user_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    version: Mapped[int]
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class EvidenceRow(Base):
    __tablename__ = "candidate_evidence"
    __table_args__ = (UniqueConstraint("profile_id", "evidence_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    evidence_key: Mapped[str]
    skill: Mapped[str]
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)


class PreferenceEvent(Base):
    __tablename__ = "preference_events"
    __table_args__ = (UniqueConstraint("user_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    version: Mapped[int]
    patch: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    supersedes: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str]
    source_text: Mapped[str | None]
    created_at: Mapped[str] = mapped_column(default=now)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    current_version: Mapped[int] = mapped_column(default=1)


class JobVersion(Base):
    __tablename__ = "job_versions"
    __table_args__ = (UniqueConstraint("job_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_key: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class JobEmbedding(Base):
    __tablename__ = "job_embeddings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str]
    vector: Mapped[Any] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"))


class IndexImport(Base):
    __tablename__ = "index_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[str] = mapped_column(default=now)
    counts: Mapped[dict[str, int | float]] = mapped_column(JSON)


class Run(Base):
    __tablename__ = "match_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_version: Mapped[int]
    preference_version: Mapped[int]
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class Decision(Base):
    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("run_id", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("match_runs.id", ondelete="CASCADE"))
    job_id: Mapped[str]
    position: Mapped[int]
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class Feedback(Base):
    __tablename__ = "feedback_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str]
    kind: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    base_version: Mapped[int]
    proposal: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    message: Mapped[str]
    status: Mapped[str]
    provider: Mapped[str]
    usage: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    elapsed_ms: Mapped[float]
    status: Mapped[str]


def engine_for(url: str):
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    connect_args: dict[str, Any] = {}
    # Supabase's transaction pooler is the right fit for short-lived serverless
    # functions. It cannot retain named prepared statements across transactions.
    if url.startswith("postgresql+psycopg://") and ":6543" in url:
        connect_args["prepare_threshold"] = None
    engine = create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
        pool_recycle=300,
    )
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
    return engine


def sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)
