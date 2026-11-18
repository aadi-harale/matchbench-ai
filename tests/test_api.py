import os

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from matchbench.api import create_app
from matchbench.config import Settings
from matchbench.db import JobEmbedding, JobRow, JobVersion, User, engine_for, sessions
from matchbench.ingest import ingest, revisions
from matchbench.models import Models
from matchbench.search import cosine_resolver
from tests.test_core import job


@pytest.fixture
def client(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", model_dir=tmp_path, create_schema=True)
    with TestClient(create_app(config)) as api:
        yield api


def search(client, query):
    response = client.post("/api/search", json={"query": query, "algorithm": "bm25"})
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_flow_replay_and_counterfactual(client):
    assert client.post("/api/auth/demo").status_code == 200
    start = search(client, "AI/backend internships working on agents and search")
    assert start["counts"]["indexed"] == 42
    senior = next(row for row in start["excluded"] if row["job"]["id"] == "agent-senior")
    assert senior["checks"][0]["key"] == "experience"
    assert senior["status"] == "fail" and senior["rank"] is None
    assert all(row["job"]["id"] != "retired-role" for row in start["matches"])
    assert client.get(f"/api/runs/{start['run_id']}").json()["matches"] == start["matches"]
    replay = client.post(f"/api/runs/{start['run_id']}/counterfactual",
                         json={"job_id": "agent-hyd", "change": "allow_location", "value": "Hyderabad"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["before"]["status"] == "fail"
    assert replay.json()["after"]["rank"] > 0
    assert search(client, "AI/backend internships working on agents and search")["preference_version"] == 1


def test_persistent_preference_and_removal(client):
    credentials = {"email": "case@example.dev", "password": "test-account-key"}
    assert client.post("/api/auth/register", json=credentials).status_code == 201
    original = search(client, "React frontend accessibility")
    assert original["matches"]
    proposal = client.post("/api/agent", json={"text": "No frontend-heavy roles"}).json()
    assert client.get("/api/preferences").json()["version"] == 0
    accepted = client.post(f"/api/agent/{proposal['id']}/confirm")
    assert accepted.status_code == 200, accepted.text
    assert client.post(f"/api/agent/{proposal['id']}/confirm").status_code == 409
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    assert client.get("/api/preferences").json()["preferences"]["denied_roles"] == ["frontend"]
    filtered = search(client, "React frontend accessibility")
    assert not any(row["job"]["role"] == "frontend" for row in filtered["matches"])
    assert client.put("/api/preferences", json={"version": 1, "changes": [
        {"field": "denied_roles", "operation": "remove", "value": "frontend"},
    ]}).status_code == 200
    restored = search(client, "React frontend accessibility")
    assert [row["job"]["id"] for row in original["matches"]] == [row["job"]["id"] for row in restored["matches"]]
    export = client.get("/api/account/export").json()
    assert len(export["preference_events"]) == 2 and export["preference_events"][1]["supersedes"]
    assert client.delete("/api/account").status_code == 200
    assert client.post("/api/auth/login", json=credentials).status_code == 401


def test_ownership_and_review(client):
    client.post("/api/auth/demo")
    older = search(client, "Python")
    result = client.post("/api/profile/extract", files={"file": ("resume.txt", b"Projects\nBuilt Python APIs.")})
    assert result.status_code == 200
    extracted = result.json()
    assert extracted["profile"]["evidence"][0]["review"] == "pending"
    assert client.put("/api/profile", json=extracted).status_code == 200
    assert client.put("/api/profile", json=extracted).status_code == 409
    assert client.post("/api/profile/extract", files={"file": ("bad.docx", b"garbage")}).status_code == 422
    client.post("/api/auth/demo")
    assert client.get(f"/api/runs/{older['run_id']}").status_code == 404


def test_repeated_feedback_creates_reviewable_suggestion(client):
    client.post("/api/auth/demo")
    result = search(client, "React frontend accessibility design")
    items = [row for row in result["matches"] if row["job"]["role"] == "frontend"]
    assert len(items) >= 3
    for row in items[:3]:
        feedback = client.post("/api/feedback", json={
            "run_id": result["run_id"], "job_id": row["job"]["id"], "kind": "Not relevant",
        })
        assert feedback.status_code == 200
    assert feedback.json()["suggestion"]["value"] == "frontend"
    assert client.get("/api/preferences").json()["preferences"]["less_roles"] == []


class FakeEmbeddings(Models):
    def embed(self, inputs):
        result = np.zeros((len(inputs), 384), dtype=np.float32)
        result[:, 0] = 1
        return result


def test_ingest_idempotence_and_versioning(client, tmp_path):
    database = engine_for(f"sqlite:///{tmp_path / 'ingest.db'}")
    from matchbench.db import Base

    Base.metadata.create_all(database)
    factory = sessions(database)
    record = job().model_dump(mode="json")
    with factory.begin() as session:
        first = ingest(session, [record, record | {"id": "duplicate"}], FakeEmbeddings(tmp_path))
    assert first["inserted"] == first["duplicates"] == first["embedded"] == 1
    with factory.begin() as session:
        updated = ingest(session, [record | {"salary_min": 28000}], FakeEmbeddings(tmp_path))
    assert updated["updated"] == 1 and updated["embedded"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobRow)) == 1
        assert session.scalar(select(func.count()).select_from(JobVersion)) == 2
        assert session.scalar(select(func.count()).select_from(JobEmbedding)) == 1


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="postgres service available in CI")
def test_pgvector_and_postgres_transactions(tmp_path):
    database = engine_for(os.environ["TEST_DATABASE_URL"])
    from matchbench.db import Base

    Base.metadata.create_all(database)
    factory = sessions(database)
    record = job("ci-test-vector").model_dump(mode="json")
    with factory() as session:
        ingest(session, [record], FakeEmbeddings(tmp_path))
        session.flush()
        score = cosine_resolver(session, revisions(session))([1.0] + [0.0] * 383)
        assert score["ci-test-vector"] == pytest.approx(1.0)
        user = User(demo=True)
        session.add(user)
        session.flush()
        assert session.get(User, user.id) is not None
        session.rollback()
