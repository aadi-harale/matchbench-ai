from datetime import UTC, datetime
from io import BytesIO

import numpy as np
import pytest
from docx import Document
from pydantic import ValidationError

from matchbench.agent import Proposal, local_proposal
from matchbench.benchmark import quality
from matchbench.large_benchmark import generated_records
from matchbench.ranking import Corpus, eligibility, explain, normalized, rank
from matchbench.resume import extract_document, parse_profile
from matchbench.schemas import Algorithm, Evidence, Job, PreferencePatch, Preferences, Profile, SearchRequest
from matchbench.state import apply_changes

AT = datetime(2026, 11, 18, tzinfo=UTC)


def job(job_id="one", **changes):
    sample = {"id": job_id, "company": "Fixture", "title": "Backend internship",
              "description": "Build Python FastAPI services", "skills": ["FastAPI", "Kubernetes"],
              "employment": "internship", "role": "backend", "locations": ["Bengaluru"], "work_mode": "hybrid",
              "experience_min": 0, "salary_min": 30000, "salary_max": 30000, "currency": "INR",
              "salary_period": "month"}
    return Job.model_validate(sample | changes)


@pytest.mark.parametrize(("changes", "expected", "key"), [
    ({"experience_min": 5}, "fail", "experience"),
    ({"locations": ["Hyderabad"]}, "fail", "location"),
    ({"salary_min": 0, "salary_max": 0}, "fail", "pay"),
    ({"salary_min": 10000, "salary_max": 10000}, "fail", "pay"),
    ({"salary_min": None, "salary_max": None}, "review", "pay"),
    ({"expires_at": "2025-01-01T00:00Z"}, "fail", "expiry"),
    ({"employment": "full-time"}, "fail", "employment"),
    ({"graduation_years": [2027]}, "review", "graduation"),
    ({"authorization": "GB"}, "review", "authorization"),
    ({"starts_by": "2025-01-01T00:00Z"}, "review", "availability"),
])
def test_eligibility(changes, expected, key):
    prefs = Preferences(employment="internship", locations=["Bangalore"], allow_relocation=False,
                        paid_only=True, minimum_stipend=20000)
    status, checks = eligibility(job(**changes), Profile(years=0), prefs, SearchRequest(query="Python"), AT)
    assert status == expected
    assert any(item["key"] == key and item["state"] == expected for item in checks)


def test_exact_terms_and_protected_name_invariance():
    corpus = Corpus([job("exact", title="FastAPI Python Intern"),
                     job("generic", title="AI internship", description="Explore similar backend ideas", skills=[]),
                     job("senior", title="FastAPI Python engineer", experience_min=5)])
    query = SearchRequest(query="FastAPI Python", algorithm=Algorithm.bm25)
    one = rank(corpus, query, Profile(name="Asha", years=0), Preferences(), AT, None, lambda _: {})
    two = rank(corpus, query, Profile(name="Arjun", years=0), Preferences(), AT, None, lambda _: {})
    assert one["matches"] == two["matches"]
    assert one["matches"][0]["job"]["id"] == "exact"
    assert one["excluded"][0]["job"]["id"] == "senior"
    assert one["excluded"][0]["rank"] is None
    with pytest.raises(ValidationError):
        Profile.model_validate({"gender": "female"})


def test_evidence_and_hypotheses():
    evidence = Evidence(id="f", skill="FastAPI", excerpt="Built APIs with FastAPI", source="Résumé line 4",
                        review="accepted")
    profile = Profile(evidence=[evidence])
    details = explain(job(), profile, [])
    assert [row["id"] for row in details["evidence"]] == ["f"]
    assert details["missing"] == ["Kubernetes"]
    profile.evidence.append(Evidence(id="k", skill="Kubernetes", excerpt="Kubernetes", source="Skills list"))
    assert explain(job(), profile, [])["unknowns"] == ["Kubernetes evidence awaits review"]


def test_pdf_docx_text_and_invalid_uploads():
    document = Document()
    document.add_paragraph("Projects")
    document.add_paragraph("Built FastAPI and PostgreSQL services.")
    document.add_paragraph("Interested in Kubernetes")
    buffer = BytesIO()
    document.save(buffer)
    parsed = parse_profile(extract_document("resume.docx", buffer.getvalue(), 1_000_000))
    assert {item.skill for item in parsed.evidence} == {"FastAPI", "PostgreSQL"}
    assert parsed.supported_skills == set()
    text = parse_profile(extract_document("resume.txt", b"Education\nExpected graduation 2027", 1_000_000))
    assert text.graduation_year == 2027
    for filename, data in [("bad.pdf", b"%PDF- broken"), ("x.exe", b"MZ"), ("bad.docx", b"PK corrupt")]:
        with pytest.raises(ValueError):
            extract_document(filename, data, 1_000_000)


class BrokenCross:
    def query_vector(self, query):
        return np.ones(384, dtype=np.float32)

    def rerank(self, *args):
        raise TimeoutError()


def test_fallback_and_empty():
    corpus = Corpus([job()])
    request = SearchRequest(query="FastAPI")
    result = rank(corpus, request, Profile(), Preferences(), AT, BrokenCross(), lambda _: {"one": 0.9})
    assert result["algorithm"] == "hybrid" and result["matches"] and result["warnings"]
    no_vectors = rank(corpus, request, Profile(), Preferences(), AT, BrokenCross(), lambda _: {})
    assert no_vectors["algorithm"] == "bm25" and no_vectors["matches"]
    empty = rank(Corpus([]), request, Profile(), Preferences(), AT, BrokenCross(), lambda _: {})
    assert empty["matches"] == []
    strong = rank(corpus, request.model_copy(update={"strong_only": True}),
                  Profile(), Preferences(), AT, BrokenCross(), lambda _: {})
    assert strong["matches"] == []


def test_schema_conflicts_and_metrics():
    assert not local_proposal("Only if the work is remote").changes
    assert local_proposal("No frontend-heavy roles").changes[0].operation == "add"
    with pytest.raises(ValidationError):
        Proposal.model_validate_json('{"changes":[{"field":"gender","operation":"set","value":"female"}]}')
    with pytest.raises(ValueError):
        apply_changes(Preferences(locations=["Bangalore"]), [
            PreferencePatch(field="excluded_locations", operation="add", value="Bengaluru")
        ])
    assert normalized({"a": 3, "b": 5}) == {"a": 0, "b": 1}
    assert quality(["a", "b"], {"a": 3, "b": 2}) == {
        "precision_at_5": .4, "recall_at_10": 1, "recall_at_20": 1, "mrr": 1, "ndcg_at_10": 1,
    }


def test_pdf_extracts_actual_text():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 160 Td (Built FastAPI services) Tj ET")
    page[NameObject("/Contents")] = content
    output = BytesIO()
    writer.write(output)
    parsed = parse_profile(extract_document("resume.pdf", output.getvalue(), 1_000_000))
    assert parsed.evidence[0].skill == "FastAPI"


def test_agent_rejects_malformed_provider_output(monkeypatch):
    import httpx
    from pydantic import SecretStr

    from matchbench import agent
    from matchbench.config import Settings

    def response(request: httpx.Request):
        return httpx.Response(200, request=request, json={
            "choices": [{"message": {"tool_calls": [{"id": "1", "function": {
                "name": "propose_preference_change", "arguments": '{"changes":[{"field":"age"}]}'}}]}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        })

    class Client:
        def __init__(self, **kwargs):
            self.client = httpx.Client(transport=httpx.MockTransport(response))

        def __enter__(self):
            return self.client

        def __exit__(self, *args):
            self.client.close()

    monkeypatch.setattr(agent, "httpx", type("MockHttp", (), {"Client": Client, "HTTPError": httpx.HTTPError}))
    proposal, provider, usage, traces = agent.agent_proposal(
        Settings(openai_api_key=SecretStr("test-key")), Preferences(), "No frontend roles", demo=False
    )
    assert provider.endswith("local rules")
    assert usage["attempts"] == 3
    assert proposal.changes[0].field == "denied_roles"
    assert [trace["status"] for trace in traces] == ["rejected", "rejected", "rejected", "validated"]


def test_large_evaluation_fixture_has_frozen_splits_and_labels():
    jobs, queries, judgments = generated_records()
    assert len(jobs) == 300
    assert len(queries) == len(judgments) == 120
    assert sum(query["split"] == "development" for query in queries) == 20
    assert sum(query["split"] == "heldout" for query in queries) == 100
    assert len({job["id"] for job in jobs}) == 300
    assert all(job["illustrative"] and job["source"] == "synthetic evaluation fixture" for job in jobs)
    assert all(set(row["grades"].values()) <= {1, 2, 3} for row in judgments)
