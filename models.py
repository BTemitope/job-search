from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobRef:
    """Lightweight reference to a posting, returned by a connector's discover()."""

    source: str
    source_id: str
    url: str
    title: str = ""


@dataclass
class RawPosting:
    """Unparsed detail-page payload for one posting, returned by fetch_detail()."""

    source: str
    source_id: str
    url: str
    html: str | None = None
    json_data: dict | None = None


@dataclass
class Criterion:
    category: str  # e.g. "Qualifications", "Experience", "Values"
    text: str
    essential: bool = True


@dataclass
class NormalizedJob:
    source: str  # "nhs_jobs" | "trac:<trust_slug>" | "manual"
    source_id: str
    title: str
    org_name: str
    location: str = ""
    salary_range: str = ""
    salary_min_numeric: float | None = None
    contract_type: str = ""
    working_pattern: str = ""
    posted_date: str = ""
    closing_date: str = ""
    url: str = ""
    reference_number: str = ""
    raw_description_text: str = ""
    person_spec_criteria: list[Criterion] = field(default_factory=list)
    raw_json: dict | None = None
    is_active: bool = True

    @property
    def id(self) -> str:
        digest = hashlib.sha256(f"{self.source}:{self.source_id}".encode()).hexdigest()
        return digest[:24]


@dataclass
class SearchQuery:
    keyword: str
    location: str = ""
    source: str = ""
    page: int = 1
    min_salary: float | None = None
    contract_type: str = ""


@dataclass
class CriterionResponse:
    criterion: str
    essential: bool
    evidence: str
    source_bullet_ref: str = ""


@dataclass
class TailoredApplication:
    job_id: str
    personal_statement: str
    tailored_work_history: list[dict]
    criteria_responses: list[CriterionResponse]
    cover_letter_or_supporting_statement: str
    flagged_gaps: list[str] = field(default_factory=list)
