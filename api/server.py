from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

import db
from connectors.nhs_jobs import NHSJobsConnector
from models import SearchQuery
from search import search_jobs

CONNECTORS = {
    "nhs_jobs": NHSJobsConnector,
}

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Job Search Assistant")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/jobs/search")
def api_search(keyword: str = "", location: str = "", source: str = "", limit: int = 30) -> list[dict]:
    jobs = search_jobs(keyword=keyword, location=location, source=source, limit=limit)
    return [asdict(j) for j in jobs]


@app.post("/api/jobs/poll")
def api_poll(keyword: str, location: str = "", source: str = "", max_pages: int = 1) -> dict:
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="keyword is required")

    sources = [source] if source else list(CONNECTORS.keys())
    now = datetime.now(timezone.utc).isoformat()
    query = SearchQuery(keyword=keyword, location=location)

    saved = 0
    errors: list[str] = []

    for source_name in sources:
        connector_cls = CONNECTORS.get(source_name)
        if connector_cls is None:
            errors.append(f"unknown source: {source_name}")
            continue

        connector = connector_cls()
        try:
            refs = list(connector.discover(query, max_pages=max_pages))
        except Exception as e:
            errors.append(f"{source_name} discover failed: {e}")
            continue

        with db.get_session() as session:
            for ref in refs:
                try:
                    raw = connector.fetch_detail(ref)
                    job = connector.normalize(raw)
                    db.upsert_job(session, job, seen_at=now)
                    saved += 1
                except Exception as e:
                    errors.append(f"{ref.url}: {e}")

    return {"saved": saved, "errors": errors}
