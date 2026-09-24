from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

import db
from models import SearchQuery
from polling import CONNECTORS, poll_sources
from search import search_jobs

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Job Search Assistant")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/jobs/search")
def api_search(
    keyword: str = "",
    location: str = "",
    source: str = "",
    limit: int = 30,
    min_salary: float | None = None,
    contract_type: str = "",
) -> list[dict]:
    jobs = search_jobs(
        keyword=keyword,
        location=location,
        source=source,
        limit=limit,
        min_salary=min_salary,
        contract_type=contract_type,
    )
    return [asdict(j) for j in jobs]


@app.post("/api/jobs/poll")
def api_poll(keyword: str, location: str = "", source: str = "", max_pages: int = 1) -> dict:
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="keyword is required")

    sources = [source] if source else list(CONNECTORS.keys())
    query = SearchQuery(keyword=keyword, location=location)
    return poll_sources(sources, query, max_pages=max_pages)


@app.post("/api/jobs/nlsearch")
def api_nlsearch(text: str, max_pages: int = 1, limit: int = 30) -> dict:
    import nl_search

    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    try:
        parsed = nl_search.parse_query(text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not parse query: {e}")

    sources = parsed.sources or list(CONNECTORS.keys())
    query = SearchQuery(keyword=parsed.keyword, location=parsed.location, min_salary=parsed.min_salary)
    poll_result = poll_sources(sources, query, max_pages=max_pages)

    jobs = search_jobs(
        keyword=parsed.keyword,
        location=parsed.location,
        min_salary=parsed.min_salary,
        contract_type=parsed.contract_type,
        limit=limit,
    )

    return {
        "parsed": {
            "keyword": parsed.keyword,
            "location": parsed.location,
            "min_salary": parsed.min_salary,
            "remote": parsed.remote,
            "contract_type": parsed.contract_type,
            "sources": parsed.sources,
        },
        "poll": poll_result,
        "jobs": [asdict(j) for j in jobs],
    }
