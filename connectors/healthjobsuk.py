from __future__ import annotations

import re
from collections.abc import Iterable

import httpx
from bs4 import BeautifulSoup

import config
from connectors import rate_limit
from connectors.base import BaseConnector
from models import Criterion, JobRef, NormalizedJob, RawPosting, SearchQuery

BASE_URL = "https://www.healthjobsuk.com"

# Matches a job detail link regardless of the surrounding list-page markup,
# e.g. /job/UK/Cambridgeshire/Wisbech/.../Some_Title-v8305755 — robust to
# list-page layout changes since it keys on the URL shape, not CSS classes.
JOB_LINK_RE = re.compile(r"(/job/[^\"'?\s]*-v(\d+))")


class HealthJobsUKConnector(BaseConnector):
    """HealthJobsUK — Trac/Civica's own national health-jobs aggregator
    (the same platform behind individual trust career sites), surfaced via
    the user's own Trac candidate dashboard: "You can use our national jobs
    board HealthJobsUK to begin your job search." Same architecture as NHS
    Jobs: plain server-rendered HTML, no login needed to search/browse.

    Unlike NHS Jobs, the detail page exposes a real, working direct Trac
    apply link without requiring login — confirmed from real fetched HTML
    (docs/SOURCE_NOTES.md), not documentation.

    discover() is pattern-based (regex on job detail URLs) rather than
    built from inspected list-page markup — this environment could never
    load healthjobsuk.com directly (WAF-blocked, like all Trac/Civica
    properties), so the list page structure is inferred from a screenshot,
    not raw HTML. normalize(), by contrast, is built from a real saved
    detail page and should be reliable. First live poll is still the real
    verification step for discover() specifically.
    """

    source_name = "healthjobsuk"

    def __init__(self) -> None:
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": config.USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )

    def discover(self, query: SearchQuery, max_pages: int = 1) -> Iterable[JobRef]:
        # No daily cap on this source, so — like NHS Jobs/Reed — query the
        # literal keyword plus any LLM-expanded related terms and union.
        terms = [query.keyword, *query.related_keywords]

        refs_by_id: dict[str, JobRef] = {}
        for term in terms:
            for page in range(1, max_pages + 1):
                rate_limit.wait_turn(self.source_name, config.NHS_JOBS_MIN_INTERVAL_SECONDS)
                params = {"JobSearch_q": term}
                if page > 1:
                    params["_pg"] = page
                resp = self.client.get("/job_list", params=params)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                # Each listing is `<li class="hj-job ..."><a href="/job/...-vNNN"
                # title="<clean job title>">` — the anchor's title attribute is
                # the clean title (its text content is the whole card, title+
                # employer+salary etc. all concatenated).
                page_links = soup.find_all("a", href=JOB_LINK_RE)
                if not page_links:
                    break
                for a in page_links:
                    match = JOB_LINK_RE.search(a["href"])
                    if not match:
                        continue
                    path, source_id = match.group(1), match.group(2)
                    if source_id in refs_by_id:
                        continue
                    refs_by_id[source_id] = JobRef(
                        source=self.source_name,
                        source_id=source_id,
                        url=f"{BASE_URL}{path}",
                        title=a.get("title") or a.get_text(strip=True),
                    )
        return list(refs_by_id.values())

    def fetch_detail(self, job_ref: JobRef) -> RawPosting:
        rate_limit.wait_turn(self.source_name, config.NHS_JOBS_MIN_INTERVAL_SECONDS)
        resp = self.client.get(job_ref.url)
        resp.raise_for_status()
        return RawPosting(source=self.source_name, source_id=job_ref.source_id, url=job_ref.url, html=resp.text)

    def normalize(self, raw: RawPosting) -> NormalizedJob:
        soup = BeautifulSoup(raw.html or "", "lxml")

        summary: dict[str, str] = {}
        for dl in soup.select("#hj-job-summary dl.hj-dl-float"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                summary[dt.get_text(strip=True)] = dd.get_text(" ", strip=True).replace("Â£", "£")

        title_el = soup.select_one(".hj-job-title > h2")
        title = title_el.get_text(strip=True) if title_el else raw.source_id

        description_parts = []
        for section_id in ("hj-job-advert-overview", "hj-job-advert-description", "hj-job-description"):
            el = soup.select_one(f"#{section_id}")
            if el:
                description_parts.append(el.get_text(" ", strip=True))
        raw_description_text = "\n\n".join(description_parts)

        criteria = self._parse_person_spec(soup)

        return NormalizedJob(
            source=self.source_name,
            source_id=raw.source_id,
            title=title,
            org_name=summary.get("Employer", ""),
            location=summary.get("Town", "") or summary.get("Site", ""),
            salary_range=summary.get("Salary", ""),
            contract_type=summary.get("Contract", ""),
            working_pattern=summary.get("Hours", ""),
            closing_date=summary.get("Closing", ""),
            url=raw.url,
            reference_number=summary.get("Job ref", raw.source_id),
            raw_description_text=raw_description_text,
            person_spec_criteria=criteria,
        )

    @staticmethod
    def _parse_person_spec(soup: BeautifulSoup) -> list[Criterion]:
        """#hj-job-role-requirement nests h4 (category) / h5 ("Essential
        criteria" or "Desirable criteria") / ul>li per category. Walked the
        same way nhs_jobs.py walks its h3/h4/ul structure — degrades to a
        single raw-text criterion if that shape isn't found.
        """
        criteria: list[Criterion] = []
        container = soup.select_one("#hj-job-role-requirement")
        if container is None:
            return criteria

        try:
            current_category = "General"
            current_level = "Essential"
            for el in container.find_all(["h4", "h5", "li"]):
                if el.name == "h4":
                    current_category = el.get_text(strip=True) or "General"
                elif el.name == "h5":
                    current_level = el.get_text(strip=True) or "Essential"
                elif el.name == "li":
                    text = el.get_text(strip=True)
                    if text:
                        essential = "essential" in current_level.lower()
                        criteria.append(Criterion(category=current_category, text=text, essential=essential))
        except Exception:
            criteria = []

        if not criteria:
            raw_text = container.get_text(" ", strip=True)
            if raw_text:
                criteria.append(Criterion(category="General", text=raw_text, essential=True))

        return criteria

    def health_check(self) -> bool:
        try:
            resp = self.client.get("/job_list", params={"JobSearch_q": "nurse", "JobSearch_Submit": "Search"})
            return resp.status_code == 200 and bool(JOB_LINK_RE.search(resp.text))
        except Exception:
            return False
