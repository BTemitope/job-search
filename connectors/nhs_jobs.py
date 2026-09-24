from __future__ import annotations

import re
from collections.abc import Iterable

import httpx
from bs4 import BeautifulSoup

import config
from connectors import rate_limit
from connectors.base import BaseConnector
from models import Criterion, JobRef, NormalizedJob, RawPosting, SearchQuery

BASE_URL = "https://www.jobs.nhs.uk"


class NHSJobsConnector(BaseConnector):
    """NHS Jobs (the national NHS vacancy aggregator).

    Per docs/SOURCE_NOTES.md: search results and job detail pages are plain
    server-rendered HTML (no JSON API, no JS rendering), so this connector is
    httpx + BeautifulSoup only — no Playwright needed. The "Apply" flow
    requires login and can redirect off-site to a third-party ATS (often
    Trac) whose true URL isn't resolvable unauthenticated, so normalize()
    stores the NHS Jobs advert page itself as the canonical url — it's
    always a valid link for the user to click Apply from.
    """

    source_name = "nhs_jobs"

    def __init__(self) -> None:
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": config.USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )

    def discover(self, query: SearchQuery, max_pages: int = 1) -> Iterable[JobRef]:
        # Query the literal keyword plus any LLM-expanded related terms (e.g.
        # "support" -> also "Care Assistant", "Healthcare Assistant") — no
        # daily cap on this source, so it's cheap to union several searches.
        terms = [query.keyword, *query.related_keywords]

        refs_by_id: dict[str, JobRef] = {}
        for term in terms:
            for page in range(1, max_pages + 1):
                rate_limit.wait_turn(self.source_name, config.NHS_JOBS_MIN_INTERVAL_SECONDS)
                params = {"keyword": term, "page": page}
                if query.location:
                    params["location"] = query.location
                resp = self.client.get("/candidate/search/results", params=params)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                links = soup.select('a[data-test="search-result-job-title"]')
                if not links:
                    break
                for a in links:
                    href = a.get("href", "")
                    match = re.search(r"/candidate/jobadvert/([^/?]+)", href)
                    if not match:
                        continue
                    source_id = match.group(1)
                    if source_id in refs_by_id:
                        continue
                    refs_by_id[source_id] = JobRef(
                        source=self.source_name,
                        source_id=source_id,
                        url=f"{BASE_URL}/candidate/jobadvert/{source_id}",
                        title=a.get_text(strip=True),
                    )
        return list(refs_by_id.values())

    def fetch_detail(self, job_ref: JobRef) -> RawPosting:
        rate_limit.wait_turn(self.source_name, config.NHS_JOBS_MIN_INTERVAL_SECONDS)
        resp = self.client.get(job_ref.url)
        resp.raise_for_status()
        return RawPosting(source=self.source_name, source_id=job_ref.source_id, url=job_ref.url, html=resp.text)

    def normalize(self, raw: RawPosting) -> NormalizedJob:
        soup = BeautifulSoup(raw.html or "", "lxml")

        def text_of(element_id: str) -> str:
            el = soup.find(id=element_id)
            return el.get_text(strip=True) if el else ""

        def value_after_heading(heading_id: str | None = None, heading_text: str | None = None) -> str:
            heading = soup.find(id=heading_id) if heading_id else None
            if heading is None and heading_text:
                heading = soup.find(lambda tag: tag.name in ("h3", "h4") and tag.get_text(strip=True) == heading_text)
            if heading is None:
                return ""
            sib = heading.find_next_sibling("p")
            return sib.get_text(strip=True) if sib else ""

        title = text_of("heading")
        org_name = text_of("employer_name")
        closing_date = text_of("closing_date").replace("The closing date is", "").strip()
        posted_date = text_of("date_posted")
        salary = text_of("negotiable_salary") or value_after_heading(heading_text="Salary")
        contract_type = text_of("contract_type")
        working_pattern = value_after_heading(heading_id="working_pattern_heading")
        reference_number = text_of("trac-job-reference") or raw.source_id

        location_parts = [text_of("employer_town"), text_of("employer_county"), text_of("employer_postcode")]
        location = ", ".join(p for p in location_parts if p)

        description_el = soup.find(id="job_description_large") or soup.find(id="job_overview")
        raw_description_text = description_el.get_text(" ", strip=True) if description_el else ""

        criteria = self._parse_person_spec(soup)

        return NormalizedJob(
            source=self.source_name,
            source_id=raw.source_id,
            title=title,
            org_name=org_name,
            location=location,
            salary_range=salary,
            contract_type=contract_type,
            working_pattern=working_pattern,
            posted_date=posted_date,
            closing_date=closing_date,
            url=raw.url,
            reference_number=reference_number,
            raw_description_text=raw_description_text,
            person_spec_criteria=criteria,
        )

    @staticmethod
    def _parse_person_spec(soup: BeautifulSoup) -> list[Criterion]:
        """Person Specification is rendered as h3 (category) / h4 (Essential
        or Desirable) / ul>li (criteria), all as siblings inside one
        container div. Degrades to one raw-text criterion if that structure
        isn't found (e.g. the org authored the section unusually) — never
        raises, per the connector's normalize() contract.
        """
        criteria: list[Criterion] = []
        heading = soup.find(lambda tag: tag.name == "h2" and tag.get_text(strip=True).lower() == "person specification")
        if heading is None or heading.parent is None:
            return criteria

        try:
            container = heading.parent
            current_category = "General"
            current_level = "Essential"
            for el in container.find_all(["h3", "h4", "ul"]):
                if el.name == "h3":
                    current_category = el.get_text(strip=True) or "General"
                elif el.name == "h4":
                    current_level = el.get_text(strip=True) or "Essential"
                elif el.name == "ul":
                    essential = "essential" in current_level.lower()
                    for li in el.find_all("li"):
                        text = li.get_text(strip=True)
                        if text:
                            criteria.append(Criterion(category=current_category, text=text, essential=essential))
        except Exception:
            criteria = []

        if not criteria:
            raw_text = heading.parent.get_text(" ", strip=True)
            if raw_text:
                criteria.append(Criterion(category="General", text=raw_text, essential=True))

        return criteria

    def health_check(self) -> bool:
        try:
            resp = self.client.get("/candidate/search/results", params={"keyword": "nurse", "page": 1})
            return resp.status_code == 200 and 'data-test="search-result-job-title"' in resp.text
        except Exception:
            return False
