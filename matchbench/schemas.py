from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Job(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    source: str = Field(default="manual", min_length=1, max_length=100)
    source_url: HttpUrl | None = None
    company: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=30000)
    locations: list[str] = Field(default_factory=list, max_length=25)
    work_mode: Literal["remote", "hybrid", "on-site", "unknown"] = "unknown"
    employment: Literal["internship", "full-time", "contract", "unknown"] = "unknown"
    role: str = "software engineering"
    skills: list[str] = Field(default_factory=list, max_length=80)
    experience_min: float | None = Field(default=None, ge=0, le=70)
    experience_max: float | None = Field(default=None, ge=0, le=70)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_period: Literal["month", "year", "hour", "unknown"] = "unknown"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    education: str | None = None
    graduation_years: list[int] = Field(default_factory=list, max_length=20)
    authorization: str | None = None
    starts_by: datetime | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    illustrative: bool = False

    @model_validator(mode="after")
    def ordered_ranges(self):
        for low, high in [(self.salary_min, self.salary_max), (self.experience_min, self.experience_max)]:
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum cannot exceed maximum")
        for value in (self.starts_by, self.posted_at, self.expires_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Job timestamps require a timezone")
        return self


class Evidence(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    skill: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=600)
    source: str = Field(min_length=1, max_length=180)
    source_url: HttpUrl | None = None
    method: Literal["parser", "candidate", "public source", "llm"] = "parser"
    review: Literal["pending", "accepted", "rejected"] = "pending"
    confidence: float | None = Field(default=None, ge=0, le=1)


class Profile(StrictModel):
    name: str = Field(default="", max_length=120)
    education: list[str] = Field(default_factory=list, max_length=30)
    experience: list[str] = Field(default_factory=list, max_length=50)
    projects: list[str] = Field(default_factory=list, max_length=50)
    years: float | None = Field(default=None, ge=0, le=70)
    graduation_year: int | None = Field(default=None, ge=1900, le=2150)
    available_from: datetime | None = None
    authorization: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_evidence(self):
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique")
        if self.available_from and self.available_from.tzinfo is None:
            raise ValueError("Availability requires a timezone")
        for entry in self.education + self.experience + self.projects + self.authorization:
            if not entry or len(entry) > 1000:
                raise ValueError("Profile entries must contain 1 to 1000 characters")
        return self

    @property
    def supported_skills(self) -> set[str]:
        return {entry.skill.casefold() for entry in self.evidence if entry.review == "accepted"}


class Preferences(StrictModel):
    employment: Literal["internship", "full-time", "contract"] | None = None
    locations: list[str] = Field(default_factory=list, max_length=25)
    excluded_locations: list[str] = Field(default_factory=list, max_length=25)
    allow_relocation: bool = True
    paid_only: bool = False
    minimum_stipend: int | None = Field(default=None, ge=0, le=10000000)
    denied_roles: list[str] = Field(default_factory=list, max_length=30)
    denied_companies: list[str] = Field(default_factory=list, max_length=50)
    preferred_roles: list[str] = Field(default_factory=list, max_length=30)
    less_roles: list[str] = Field(default_factory=list, max_length=30)
    preferred_skills: list[str] = Field(default_factory=list, max_length=50)
    preferred_work_modes: list[Literal["remote", "hybrid", "on-site"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        for positive, negative in [
            (self.locations, self.excluded_locations),
            (self.preferred_roles, self.denied_roles),
            (self.preferred_roles, self.less_roles),
        ]:
            if {v.casefold() for v in positive} & {v.casefold() for v in negative}:
                raise ValueError("The same preference appears in conflicting lists")
        for values in self.model_dump().values():
            if isinstance(values, list) and any(not v or len(v) > 120 for v in values):
                raise ValueError("Preference items must contain 1 to 120 characters")
        return self


class PreferencePatch(StrictModel):
    field: Literal[
        "employment", "locations", "excluded_locations", "allow_relocation", "paid_only", "minimum_stipend",
        "denied_roles", "denied_companies", "preferred_roles", "less_roles", "preferred_skills",
        "preferred_work_modes",
    ]
    operation: Literal["set", "add", "remove", "clear"]
    value: str | int | bool | list[str] | None = None


class FeedbackKind(StrEnum):
    interested = "Interested"
    not_relevant = "Not relevant"
    wrong_location = "Wrong location"
    too_senior = "Too senior"
    too_junior = "Too junior"
    wrong_technology = "Wrong technology"
    not_company = "Not this company"
    more = "More like this"
    less = "Less like this"


class Algorithm(StrEnum):
    keyword = "keyword"
    bm25 = "bm25"
    embedding = "embedding"
    hybrid = "hybrid"
    rerank = "hybrid_rerank"
    personalized = "personalized"


class SearchRequest(StrictModel):
    query: str = Field(min_length=2, max_length=480)
    algorithm: Algorithm = Algorithm.personalized
    limit: int = Field(default=12, ge=1, le=30)
    location: str | None = Field(default=None, max_length=120)
    employment: Literal["internship", "full-time", "contract"] | None = None
    work_mode: Literal["remote", "hybrid", "on-site"] | None = None
    strong_only: bool = False


class Counterfactual(StrictModel):
    job_id: str = Field(max_length=80)
    change: Literal["allow_location", "add_skill", "remove_role_exclusion", "remove_pay_constraint"]
    value: str | None = Field(default=None, max_length=120)
