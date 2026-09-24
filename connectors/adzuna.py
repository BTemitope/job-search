from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

import config
from connectors import rate_limit
from connectors.base import BaseConnector
from connectors.manual_paste import extract_criteria_from_text
from models import JobRef, NormalizedJob, RawPosting, SearchQuery

BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search"


class AdzunaConnector(BaseConnector):
    """Adzuna's official job search API — chosen over scraping general job
    boards (Indeed/LinkedIn-style ToS actively prohibit that). Free tier is
    tightly capped (25 req/min, 250 req/day — see docs/SOURCE_NOTES.md), so
    this connector enforces both the per-request pacing every connector uses
    and an explicit daily-cap guard that stops early rather than risking the
    key getting throttled.

    Adzuna's search response already contains everything a listing needs
    (no per-job detail endpoint on the free tier), so fetch_detail() is a
    cache lookup against what discover() already fetched, not a second
    network call.
    """

    source_name = "adzuna"

    def __init__(self) -> None:
        self.client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=20.0)
        self._cache: dict[str, dict] = {}

    def discover(self, query: SearchQuery, max_pages: int = 1) -> Iterable[JobRef]:
        if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
            raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env")

        refs: list[JobRef] = []
        for page in range(1, max_pages + 1):
            if not rate_limit.check_daily_cap(self.source_name, config.ADZUNA_DAILY_CAP):
                print(f"[{self.source_name}] daily cap ({config.ADZUNA_DAILY_CAP}) reached — resuming after UTC midnight")
                break

            rate_limit.wait_turn(self.source_name, config.ADZUNA_MIN_INTERVAL_SECONDS)
            params = {
                "app_id": config.ADZUNA_APP_ID,
                "app_key": config.ADZUNA_APP_KEY,
                "what": query.keyword,
                "results_per_page": 20,
                "content-type": "application/json",
            }
            if query.location:
                params["where"] = query.location
            if query.min_salary:
                params["salary_min"] = int(query.min_salary)

            resp = self.client.get(f"{BASE_URL}/{page}", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for item in results:
                source_id = str(item.get("id", ""))
                if not source_id:
                    continue
                self._cache[source_id] = item
                refs.append(
                    JobRef(
                        source=self.source_name,
                        source_id=source_id,
                        url=item.get("redirect_url", ""),
                        title=item.get("title", ""),
                    )
                )
        return refs

    def fetch_detail(self, job_ref: JobRef) -> RawPosting:
        item = self._cache.get(job_ref.source_id)
        if item is None:
            raise RuntimeError(
                f"No cached Adzuna data for {job_ref.source_id} — fetch_detail() must be called "
                "after discover() in the same connector instance (no free-tier detail endpoint)."
            )
        return RawPosting(source=self.source_name, source_id=job_ref.source_id, url=job_ref.url, json_data=item)

    def normalize(self, raw: RawPosting) -> NormalizedJob:
        item = raw.json_data or {}

        def safe(getter, default=""):
            try:
                value = getter()
                return value if value is not None else default
            except Exception:
                return default

        title = safe(lambda: item.get("title", ""))
        org_name = safe(lambda: item.get("company", {}).get("display_name", ""))
        location = safe(lambda: item.get("location", {}).get("display_name", ""))
        contract_type = safe(lambda: item.get("contract_type", ""))
        working_pattern = safe(lambda: item.get("contract_time", ""))
        description = safe(lambda: item.get("description", ""))

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        if salary_min and salary_max:
            predicted = " (estimated)" if item.get("salary_is_predicted") == "1" else ""
            salary_range = f"£{salary_min:,.0f} to £{salary_max:,.0f} a year{predicted}"
        else:
            salary_range = ""

        posted_date = ""
        created = item.get("created")
        if created:
            try:
                posted_date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%d %B %Y")
            except ValueError:
                posted_date = created

        criteria, _ = extract_criteria_from_text(description)

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
            url=raw.url,
            reference_number=raw.source_id,
            raw_description_text=description,  # Adzuna gives a snippet, not full text — see SOURCE_NOTES.md
            person_spec_criteria=criteria,
            raw_json=item,
        )

    def health_check(self) -> bool:
        if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
            return False
        try:
            resp = self.client.get(
                f"{BASE_URL}/1",
                params={
                    "app_id": config.ADZUNA_APP_ID,
                    "app_key": config.ADZUNA_APP_KEY,
                    "what": "developer",
                    "results_per_page": 1,
                    "content-type": "application/json",
                },
            )
            return resp.status_code == 200 and "results" in resp.json()
        except Exception:
            return False
