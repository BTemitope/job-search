from __future__ import annotations

from datetime import datetime, timezone

import db
from connectors.adzuna import AdzunaConnector
from connectors.nhs_jobs import NHSJobsConnector
from connectors.reed import ReedConnector
from models import SearchQuery

CONNECTORS = {
    "nhs_jobs": NHSJobsConnector,
    "adzuna": AdzunaConnector,
    "reed": ReedConnector,
}


def poll_sources(sources: list[str], query: SearchQuery, max_pages: int = 1) -> dict:
    """Shared by the CLI (`poll`/`nlsearch`) and the web API — one source's
    missing credentials or a connector error never blocks the others; each
    is caught and reported individually rather than aborting the whole run.
    """
    db.init_db()
    now = datetime.now(timezone.utc).isoformat()

    saved = 0
    counts: dict[str, int] = {}
    errors: list[str] = []

    for source_name in sources:
        connector_cls = CONNECTORS.get(source_name)
        if connector_cls is None:
            errors.append(f"unknown source: {source_name}")
            continue

        try:
            connector = connector_cls()
            refs = list(connector.discover(query, max_pages=max_pages))
        except Exception as e:
            errors.append(f"{source_name}: {e}")
            continue

        source_saved = 0
        with db.get_session() as session:
            for ref in refs:
                try:
                    raw = connector.fetch_detail(ref)
                    job = connector.normalize(raw)
                    db.upsert_job(session, job, seen_at=now)
                    source_saved += 1
                except Exception as e:
                    errors.append(f"{source_name} — {ref.url}: {e}")

        counts[source_name] = source_saved
        saved += source_saved

    return {"saved": saved, "counts": counts, "errors": errors}
