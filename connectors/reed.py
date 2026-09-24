from __future__ import annotations

from collections.abc import Iterable

import httpx
from bs4 import BeautifulSoup

import config
from connectors import rate_limit
from connectors.base import BaseConnector
from connectors.manual_paste import extract_criteria_from_text
from models import JobRef, NormalizedJob, RawPosting, SearchQuery

SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
DETAIL_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"

RESULTS_PER_PAGE = 100  # Reed's documented max for resultsToTake


class ReedConnector(BaseConnector):
    """Reed's official job search API. Its free-tier limits are far looser
    than Adzuna's (no documented daily cap, ~2000 req/hour elsewhere on
    their platform) but Reed explicitly asks integrators to avoid
    unnecessary polling — the shared rate_limit.wait_turn() pacing still
    applies, just with a shorter default interval than Adzuna's.

    Field names below are taken from Reed's documentation, not a live test
    call (no API key was available while building this) — the first real
    poll is the actual verification step; normalize() degrades to empty
    strings/None on any unexpected shape rather than raising.
    """

    source_name = "reed"

    def __init__(self) -> None:
        if not config.REED_API_KEY:
            raise RuntimeError("REED_API_KEY not set in .env")
        # Reed uses HTTP Basic auth: API key as username, empty password.
        self.client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            auth=(config.REED_API_KEY, ""),
            timeout=20.0,
        )

    def discover(self, query: SearchQuery, max_pages: int = 1) -> Iterable[JobRef]:
        # Reed's limit is loose enough (~2000/hour) to afford querying the
        # literal keyword plus any LLM-expanded related terms and union the
        # results — unlike Adzuna, which deliberately stays literal-only.
        terms = [query.keyword, *query.related_keywords]

        refs_by_id: dict[str, JobRef] = {}
        for term in terms:
            for page in range(max_pages):
                rate_limit.wait_turn(self.source_name, config.REED_MIN_INTERVAL_SECONDS)
                params = {
                    "keywords": term,
                    "resultsToTake": RESULTS_PER_PAGE,
                    "resultsToSkip": page * RESULTS_PER_PAGE,
                }
                if query.location:
                    params["locationName"] = query.location
                if query.min_salary:
                    params["minimumSalary"] = int(query.min_salary)

                resp = self.client.get(SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    job_id = str(item.get("jobId", ""))
                    if not job_id or job_id in refs_by_id:
                        continue
                    refs_by_id[job_id] = JobRef(
                        source=self.source_name,
                        source_id=job_id,
                        url=item.get("jobUrl", ""),
                        title=item.get("jobTitle", ""),
                    )
        return list(refs_by_id.values())

    def fetch_detail(self, job_ref: JobRef) -> RawPosting:
        rate_limit.wait_turn(self.source_name, config.REED_MIN_INTERVAL_SECONDS)
        resp = self.client.get(DETAIL_URL.format(job_id=job_ref.source_id))
        resp.raise_for_status()
        return RawPosting(source=self.source_name, source_id=job_ref.source_id, url=job_ref.url, json_data=resp.json())

    def normalize(self, raw: RawPosting) -> NormalizedJob:
        item = raw.json_data or {}

        def safe(getter, default=""):
            try:
                value = getter()
                return value if value is not None else default
            except Exception:
                return default

        title = safe(lambda: item.get("jobTitle", ""))
        org_name = safe(lambda: item.get("employerName", ""))
        location = safe(lambda: item.get("locationName", ""))
        contract_type = safe(lambda: item.get("contractType", ""))
        working_pattern = safe(lambda: "Full-time" if item.get("fullTime") else ("Part-time" if item.get("partTime") else ""))
        posted_date = safe(lambda: item.get("date", ""))
        closing_date = safe(lambda: item.get("expirationDate", ""))

        description_html = safe(lambda: item.get("jobDescription", ""))
        description_text = BeautifulSoup(description_html, "lxml").get_text("\n", strip=True) if description_html else ""

        salary_min = item.get("minimumSalary")
        salary_max = item.get("maximumSalary")
        if salary_min and salary_max:
            salary_range = f"£{salary_min:,.0f} to £{salary_max:,.0f} a year"
        elif salary_min:
            salary_range = f"£{salary_min:,.0f}+ a year"
        else:
            salary_range = ""

        criteria, _ = extract_criteria_from_text(description_text)

        return NormalizedJob(
            source=self.source_name,
            source_id=raw.source_id,
            title=title,
            org_name=org_name,
            location=location,
            salary_range=salary_range,
            salary_min_numeric=float(salary_min) if salary_min else None,
            contract_type=contract_type,
            working_pattern=working_pattern,
            posted_date=posted_date,
            closing_date=closing_date,
            url=raw.url or item.get("jobUrl", ""),
            reference_number=raw.source_id,
            raw_description_text=description_text,
            person_spec_criteria=criteria,
            raw_json=item,
        )

    def health_check(self) -> bool:
        if not config.REED_API_KEY:
            return False
        try:
            resp = self.client.get(SEARCH_URL, params={"keywords": "developer", "resultsToTake": 1})
            return resp.status_code == 200 and "results" in resp.json()
        except Exception:
            return False
