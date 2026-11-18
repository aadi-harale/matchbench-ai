import json
from collections import Counter
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Annotated, Any
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .agent import agent_proposal
from .config import DATA, ROOT, Settings, validated_alpha
from .db import (
    AgentRun,
    Base,
    Decision,
    Feedback,
    IndexImport,
    JobRow,
    PreferenceEvent,
    ProfileVersion,
    Run,
    ToolCall,
    User,
)
from .ingest import ingest, read_records
from .models import Models
from .resume import extract_document, parse_profile
from .schemas import Counterfactual, FeedbackKind, PreferencePatch, Profile, SearchRequest, StrictModel
from .search import counterfactual, execute, replay
from .security import COOKIE, RateLimits, decode, hasher, sign, verify
from .state import (
    VersionConflict,
    event_view,
    preference_at,
    profile_at,
    seed_candidate,
    write_preferences,
    write_profile,
)


class Credentials(StrictModel):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)
    password: str = Field(min_length=10, max_length=128)


class ProfileEdit(StrictModel):
    version: int = Field(ge=0)
    profile: Profile


class Message(StrictModel):
    text: str = Field(min_length=2, max_length=600)


class PreferenceEdit(StrictModel):
    version: int = Field(ge=0)
    changes: list[PreferencePatch] = Field(min_length=1, max_length=14)


class FeedbackRequest(StrictModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    job_id: str = Field(max_length=80)
    kind: FeedbackKind


def create_app(settings: Settings | None = None, *, database=None) -> FastAPI:
    from .db import engine_for, sessions

    settings = settings or Settings()
    engine = database or engine_for(settings.database_url)
    factory = sessions(engine)
    models = Models(settings.model_dir)
    alpha = validated_alpha()
    limits = RateLimits()
    metrics: Counter[str] = Counter()
    durations: dict[str, float] = {}
    metrics_lock = Lock()

    @asynccontextmanager
    async def lifespan(_):
        if settings.create_schema:
            if engine.dialect.name == "postgresql":
                with engine.begin() as connection:
                    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(engine)
        if settings.seed_demo:
            with factory() as session:
                empty = session.scalar(select(JobRow.id).limit(1)) is None
            if empty:
                with factory.begin() as session:
                    ingest(session, read_records(DATA / "jobs.json"), models,
                           lexical_only=not models.available("embed"))
        yield

    app = FastAPI(title="MatchBench AI", version="0.1.0", lifespan=lifespan,
                  description="Evidence-linked job ranking, preference memory and evaluation.")
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def observe(request: Request, call_next):
        started = perf_counter()
        if request.url.path.startswith("/api/"):
            client = request.client.host if request.client else "local"
            restricted = {"/api/auth/login": 8, "/api/auth/register": 8, "/api/auth/demo": 30}
            path = request.url.path
            cost = restricted.get(path, 90)
            if not limits.permit(client, path if path in restricted else "api", cost):
                return JSONResponse({"detail": "Request limit reached. Try again in a minute."},
                                    status_code=429, headers={"Retry-After": "60"})
            origin = request.headers.get("origin")
            if request.method in {"POST", "PUT", "DELETE"} and origin:
                if urlsplit(origin).netloc != request.headers.get("host") and origin not in settings.cors_origins:
                    return JSONResponse({"detail": "Use the MatchBench interface to make this change."}, status_code=403)
            size = request.headers.get("content-length")
            if size and size.isdigit() and int(size) > settings.max_upload_bytes + 65536:
                return JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        name = getattr(route, "path", "unknown")
        with metrics_lock:
            metrics[f"{name} {response.status_code} count"] += 1
            durations[name] = durations.get(name, 0.0) + (perf_counter() - started) * 1000
        return response

    @app.exception_handler(VersionConflict)
    def version_error(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(IntegrityError)
    def db_conflict(_, exc):
        return JSONResponse({"detail": "This change conflicts with a recent update. Reload and retry."}, status_code=409)

    @app.exception_handler(OperationalError)
    def db_down(_, exc):
        return JSONResponse({"detail": "Database is temporarily unavailable. Retry in a moment."}, status_code=503)

    def db_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    def get_user(request: Request, session: Session = Depends(db_session)) -> User:
        try:
            claims = decode(request.cookies.get(COOKIE, ""), settings)
        except jwt.InvalidTokenError as error:
            raise HTTPException(401, "Start the demo or sign in.") from error
        user = session.get(User, claims["sub"])
        if user is None or user.session_version != claims["sv"]:
            raise HTTPException(401, "Session expired. Sign in again.")
        return user

    def cookie(response: Response, user: User) -> dict[str, Any]:
        response.set_cookie(COOKIE, sign(user, settings), httponly=True, secure=settings.secure_cookies,
                            samesite="lax", max_age=86400 * 7)
        return {"demo": user.demo, "email": user.email}

    def run_search(session: Session, user: User, body: SearchRequest) -> dict[str, Any]:
        result = execute(session, user, body, models, settings.rerank_timeout_seconds, alpha=alpha)
        latest = session.scalar(select(IndexImport.created_at).order_by(IndexImport.id.desc()).limit(1))
        if latest and datetime.fromisoformat(latest) < datetime.now(UTC) - timedelta(hours=settings.index_stale_hours):
            result["warnings"].append("The job index has not been refreshed recently. Check the original posting.")
        with metrics_lock:
            for stage, value in result["timing"].items():
                key = f"search/{result['algorithm']}/{stage}"
                durations[key] = durations.get(key, 0.0) + value
        return result

    def owned_run(session: Session, user: User, run_id: str) -> Run:
        run = session.scalar(select(Run).where(Run.id == run_id, Run.user_id == user.id))
        if not run:
            raise HTTPException(404, "Match run not found.")
        return run

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(session: Session = Depends(db_session)):
        total = session.scalar(select(func.count()).select_from(JobRow))
        latest = session.scalar(select(IndexImport).order_by(IndexImport.id.desc()).limit(1))
        return {"status": "ready", "jobs": total, "database": engine.dialect.name,
                "embeddings": models.available("embed"), "reranker": models.available("rank"),
                "llm_configured": settings.llm_enabled,
                "last_ingestion": latest.created_at if latest else None,
                "ingestion": latest.counts if latest else None}

    @app.get("/api/observability")
    def telemetry():
        with metrics_lock:
            return {"api": dict(metrics), "duration_ms": durations.copy(),
                    "query_embedding_cache": models.query_vector.cache_info()._asdict()}

    @app.post("/api/auth/demo")
    def demo(response: Response, session: Session = Depends(db_session)):
        user = User(demo=True)
        session.add(user)
        session.flush()
        seed_candidate(session, user)
        session.commit()
        return cookie(response, user)

    @app.post("/api/bootstrap")
    def bootstrap(
        body: SearchRequest, request: Request, response: Response, session: Session = Depends(db_session),
    ):
        user = None
        try:
            claims = decode(request.cookies.get(COOKIE, ""), settings)
            candidate = session.get(User, claims["sub"])
            if candidate and candidate.session_version == claims["sv"]:
                user = candidate
        except (jwt.InvalidTokenError, KeyError):
            pass
        created = user is None
        if created:
            user = User(demo=True)
            session.add(user)
            session.flush()
            seed_candidate(session, user)
        assert user is not None
        profile_version, current_profile = profile_at(session, user)
        preference_version, current_preferences = preference_at(session, user)
        history = list(session.scalars(select(PreferenceEvent).where(
            PreferenceEvent.user_id == user.id
        ).order_by(PreferenceEvent.version.desc()).limit(30)))
        result = run_search(session, user, body)
        session.commit()
        if created:
            cookie(response, user)
        return {
            "identity": {"demo": user.demo, "email": user.email},
            "profile": {"version": profile_version, "profile": current_profile},
            "memory": {"version": preference_version, "preferences": current_preferences,
                       "history": [event_view(row) for row in history]},
            "run": result,
        }

    @app.post("/api/auth/register", status_code=201)
    def register(body: Credentials, response: Response, session: Session = Depends(db_session)):
        user = User(email=body.email.casefold(), password=hasher.hash(body.password))
        session.add(user)
        session.commit()
        return cookie(response, user)

    @app.post("/api/auth/login")
    def login(body: Credentials, response: Response, session: Session = Depends(db_session)):
        user = session.scalar(select(User).where(User.email == body.email.casefold()))
        if not verify(body.password, user.password if user else None) or not user:
            raise HTTPException(401, "Check your email and password.")
        return cookie(response, user)

    @app.get("/api/auth/session")
    def identity(request: Request, session: Session = Depends(db_session)):
        if not request.cookies.get(COOKIE):
            return {"active": False}
        try:
            user = get_user(request, session)
        except HTTPException:
            return {"active": False}
        return {"active": True, "demo": user.demo, "email": user.email}

    @app.post("/api/auth/logout")
    def logout(response: Response, session: Session = Depends(db_session), user: User = Depends(get_user)):
        user.session_version += 1
        session.commit()
        response.delete_cookie(COOKIE, secure=settings.secure_cookies)
        return {"status": "signed out"}

    @app.get("/api/profile")
    def profile(session: Session = Depends(db_session), user: User = Depends(get_user)):
        version, current = profile_at(session, user)
        return {"version": version, "profile": current}

    @app.put("/api/profile")
    def edit_profile(body: ProfileEdit, session: Session = Depends(db_session), user: User = Depends(get_user)):
        version = write_profile(session, user, body.profile, body.version)
        session.commit()
        return {"version": version, "profile": body.profile}

    @app.post("/api/profile/extract")
    def upload(
        file: Annotated[UploadFile, File()], session: Session = Depends(db_session), user: User = Depends(get_user),
    ):
        if not limits.permit(user.id, "upload", 8):
            raise HTTPException(429, "Upload limit reached. Try again in a minute.")
        try:
            data = file.file.read(settings.max_upload_bytes + 1)
            sections = extract_document(file.filename or "", data, settings.max_upload_bytes)
            version, current = profile_at(session, user)
            extracted = parse_profile(sections)
            extracted.name = current.name
            return {"version": version, "profile": extracted}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/preferences")
    def preferences(session: Session = Depends(db_session), user: User = Depends(get_user)):
        version, current = preference_at(session, user)
        history = session.scalars(select(PreferenceEvent).where(
            PreferenceEvent.user_id == user.id
        ).order_by(PreferenceEvent.version.desc()).limit(30))
        return {"version": version, "preferences": current, "history": [event_view(row) for row in history]}

    @app.put("/api/preferences")
    def edit_preferences(body: PreferenceEdit, session: Session = Depends(db_session), user: User = Depends(get_user)):
        try:
            version, updated = write_preferences(session, user, body.changes, body.version, source="direct edit")
        except VersionConflict:
            raise
        except ValueError as error:
            raise HTTPException(422, "Check for conflicting or invalid preference values.") from error
        session.commit()
        return {"version": version, "preferences": updated}

    @app.post("/api/agent")
    def interpret(body: Message, session: Session = Depends(db_session), user: User = Depends(get_user)):
        if not limits.permit(user.id, "agent", 8):
            raise HTTPException(429, "Agent limit reached. Try again in a minute.")
        version, current = preference_at(session, user)
        proposal, provider, usage, calls = agent_proposal(settings, current, body.text, demo=user.demo)
        draft = AgentRun(user_id=user.id, base_version=version, message=body.text, provider=provider,
                         proposal=[patch.model_dump(mode="json") for patch in proposal.changes],
                         status="pending" if proposal.changes else "clarification", usage=usage)
        session.add(draft)
        session.flush()
        session.add_all([ToolCall(run_id=draft.id, **call) for call in calls])
        session.commit()
        return {"id": draft.id, "proposal": proposal, "provider": provider, "tool_calls": calls, "usage": usage}

    @app.post("/api/agent/{draft_id}/confirm")
    def confirm(draft_id: str, session: Session = Depends(db_session), user: User = Depends(get_user)):
        draft = session.scalar(select(AgentRun).where(
            AgentRun.id == draft_id, AgentRun.user_id == user.id
        ).with_for_update())
        if not draft or draft.status != "pending":
            raise HTTPException(409, "This proposal is no longer pending.")
        version, updated = write_preferences(
            session, user, [PreferencePatch.model_validate(patch) for patch in draft.proposal],
            draft.base_version, source=draft.provider, source_text=draft.message,
        )
        draft.status = "confirmed"
        session.add(ToolCall(run_id=draft.id, name="update_preferences", elapsed_ms=0, status="confirmed"))
        session.commit()
        return {"version": version, "preferences": updated}

    @app.post("/api/search")
    def search(body: SearchRequest, session: Session = Depends(db_session), user: User = Depends(get_user)):
        result = run_search(session, user, body)
        session.commit()
        return result

    @app.get("/api/runs/{run_id}")
    def historical_run(run_id: str, session: Session = Depends(db_session), user: User = Depends(get_user)):
        return replay(session, owned_run(session, user, run_id))

    @app.post("/api/runs/{run_id}/counterfactual")
    def simulate(run_id: str, body: Counterfactual, session: Session = Depends(db_session), user: User = Depends(get_user)):
        try:
            return counterfactual(session, user, owned_run(session, user, run_id), body, models,
                                  settings.rerank_timeout_seconds)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @app.post("/api/feedback")
    def feedback(body: FeedbackRequest, session: Session = Depends(db_session), user: User = Depends(get_user)):
        run = owned_run(session, user, body.run_id)
        row = session.scalar(select(Decision).where(Decision.run_id == run.id, Decision.job_id == body.job_id))
        if not row:
            raise HTTPException(404, "Job not found in this run.")
        job = row.result["job"]
        session.add(Feedback(user_id=user.id, job_id=body.job_id, kind=body.kind.value,
                             details={"run_id": run.id, "role": job["role"], "company": job["company"]}))
        session.flush()
        suggestion = None
        version, memory = preference_at(session, user)
        if body.kind in {FeedbackKind.not_relevant, FeedbackKind.less}:
            recent = session.scalars(select(Feedback).where(
                Feedback.user_id == user.id, Feedback.kind.in_([FeedbackKind.not_relevant, FeedbackKind.less]),
            ).order_by(Feedback.created_at.desc()).limit(40))
            distinct = {item.job_id for item in recent if item.details["role"] == job["role"]}
            if len(distinct) >= 3 and job["role"] not in memory.less_roles + memory.preferred_roles + memory.denied_roles:
                suggestion = PreferencePatch(field="less_roles", operation="add", value=job["role"])
        elif body.kind == FeedbackKind.not_company:
            suggestion = PreferencePatch(field="denied_companies", operation="add", value=job["company"])
        elif body.kind == FeedbackKind.more and job["role"] not in memory.less_roles + memory.denied_roles:
            suggestion = PreferencePatch(field="preferred_roles", operation="add", value=job["role"])
        session.commit()
        return {"recorded": body.kind.value, "suggestion": suggestion, "version": version}

    @app.get("/api/evaluation")
    def evaluation():
        path = DATA / "benchmark.json"
        if not path.is_file():
            raise HTTPException(404, "Run the benchmark to publish measured results.")
        report = json.loads(path.read_text(encoding="utf-8"))
        for name, key in [("agent_benchmark.json", "contracts"), ("load_benchmark.json", "index_load")]:
            artifact = DATA / name
            if artifact.is_file():
                report[key] = json.loads(artifact.read_text(encoding="utf-8"))
        return report

    @app.get("/api/account/export")
    def export(session: Session = Depends(db_session), user: User = Depends(get_user)):
        versions = session.scalars(select(ProfileVersion.version).where(ProfileVersion.user_id == user.id)).all()
        events = session.scalars(select(PreferenceEvent).where(PreferenceEvent.user_id == user.id)).all()
        runs = session.scalars(select(Run).where(Run.user_id == user.id)).all()
        actions = session.scalars(select(Feedback).where(Feedback.user_id == user.id)).all()
        agent_runs = session.scalars(select(AgentRun).where(AgentRun.user_id == user.id)).all()
        return {
            "email": user.email, "created_at": user.created_at,
            "profiles": [{"version": ver, "profile": profile_at(session, user, ver)[1]} for ver in versions],
            "preference_events": [event_view(row) for row in events],
            "match_runs": [replay(session, run) for run in runs],
            "feedback": [{"job_id": row.job_id, "kind": row.kind, "details": row.details,
                          "created_at": row.created_at} for row in actions],
            "agent_runs": [{"message": row.message, "proposal": row.proposal, "status": row.status,
                            "provider": row.provider, "usage": row.usage} for row in agent_runs],
        }

    @app.delete("/api/account")
    def delete(response: Response, session: Session = Depends(db_session), user: User = Depends(get_user)):
        session.delete(user)
        session.commit()
        response.delete_cookie(COOKIE, secure=settings.secure_cookies)
        return {"status": "deleted"}

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        page = Path(dist / "index.html")
        if page.is_file():
            return FileResponse(page)
        return {"name": "MatchBench AI", "api": "/docs", "status": "Frontend build pending"}

    return app


app = create_app()
