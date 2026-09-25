from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone

import config
import db
from connectors.adzuna import AdzunaConnector
from connectors.healthjobsuk import HealthJobsUKConnector
from connectors.nhs_jobs import NHSJobsConnector
from connectors.reed import ReedConnector
from models import SearchQuery

CONNECTORS = {
    "nhs_jobs": NHSJobsConnector,
    "healthjobsuk": HealthJobsUKConnector,
    "adzuna": AdzunaConnector,
    "reed": ReedConnector,
}


def _poll_one_source(source_name: str, query: SearchQuery, max_pages: int, seen_at: str) -> tuple[int, list[str]]:
    """Runs entirely inside one thread (see poll_sources) — every connector
    here does synchronous httpx calls, so this is what actually parallelizes
    across sources. A source's own rate_limit.wait_turn() pacing stays
    correct under this model: all of one source's requests happen inside
    this single thread, so there's never concurrent access to that source's
    entry in the rate limiter's timestamp dict from two threads at once.
    """
    errors: list[str] = []

    connector_cls = CONNECTORS.get(source_name)
    if connector_cls is None:
        return 0, [f"unknown source: {source_name}"]

    try:
        connector = connector_cls()
        refs = list(connector.discover(query, max_pages=max_pages))
    except Exception as e:
        return 0, [f"{source_name}: {e}"]

    saved = 0
    for ref in refs:
        try:
            raw = connector.fetch_detail(ref)
            job = connector.normalize(raw)
            # Commit per job, not once for the whole ref list — if
            # poll_sources()'s timeout backstop abandons this thread
            # partway through (e.g. smart-search expansion multiplying a
            # slow, correctly-rate-limited source's work well past the
            # timeout), whatever was already fetched stays saved instead of
            # being silently discarded because the one big commit never
            # happened. Found live: an NL search with 4 expanded terms
            # against NHS Jobs returned 0 results even though real jobs
            # were being fetched the whole time — the single end-of-loop
            # commit simply never got reached before the backstop fired.
            with db.get_session() as session:
                db.upsert_job(session, job, seen_at=seen_at)
            saved += 1
        except Exception as e:
            errors.append(f"{source_name} — {ref.url}: {e}")

    return saved, errors


def poll_sources(sources: list[str], query: SearchQuery, max_pages: int = 1) -> dict:
    """Shared by the CLI (`poll`/`nlsearch`) and the web API. Polls every
    source concurrently (one thread each) rather than one after another —
    measured against the deployed app, a sequential poll across NHS Jobs
    (~35s, by design — rate-limited) and HealthJobsUK (observed to hang for
    40s+ from cloud IPs) compounded into minutes for one click. Concurrency
    makes the total wait roughly the slowest source, not the sum of all of
    them. Each source is additionally bounded by
    config.SOURCE_POLL_TIMEOUT_SECONDS as a backstop: a source that blows
    past it is recorded as a timeout error and abandoned (its thread keeps
    running in the background and any DB writes it manages still land
    harmlessly) rather than holding up the response — one source's problems
    still never block the others or the overall result, same guarantee the
    old sequential try/except gave, just also bounded in time now.
    """
    db.init_db()
    now = datetime.now(timezone.utc).isoformat()

    saved = 0
    counts: dict[str, int] = {}
    errors: list[str] = []

    # Deliberately not a `with ThreadPoolExecutor(...) as executor:` block —
    # that context manager's __exit__ calls shutdown(wait=True), which blocks
    # until every submitted thread finishes regardless of the per-future
    # timeout below, defeating the whole point of bounding a hung source.
    # shutdown(wait=False) here lets an abandoned thread keep running
    # independently in the background instead.
    executor = ThreadPoolExecutor(max_workers=max(len(sources), 1))
    try:
        futures = {
            executor.submit(_poll_one_source, source_name, query, max_pages, now): source_name
            for source_name in sources
        }
        pending = set(futures.keys())

        # as_completed(), not iterating `futures` directly with a per-future
        # .result(timeout=...) — that would wait on each future in
        # *insertion* order regardless of which actually finished first,
        # silently serializing the wait again even though the threads
        # themselves run in parallel. as_completed() yields whichever
        # finishes next, and its own `timeout` bounds the whole thing from
        # here, not per-source — so total wait is genuinely governed by the
        # slowest source up to this one cap, not the sum of every source's
        # own timeout.
        try:
            for future in as_completed(futures, timeout=config.SOURCE_POLL_TIMEOUT_SECONDS):
                pending.discard(future)
                source_name = futures[future]
                try:
                    source_saved, source_errors = future.result()
                except Exception as e:
                    errors.append(f"{source_name}: {e}")
                    continue
                counts[source_name] = source_saved
                saved += source_saved
                errors.extend(source_errors)
        except FutureTimeoutError:
            for future in pending:
                errors.append(f"{futures[future]}: timed out after {config.SOURCE_POLL_TIMEOUT_SECONDS:.0f}s")
    finally:
        executor.shutdown(wait=False)

    return {"saved": saved, "counts": counts, "errors": errors}
