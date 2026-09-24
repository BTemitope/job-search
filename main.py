from __future__ import annotations

import argparse
from datetime import datetime, timezone

import config
import db
from connectors.nhs_jobs import NHSJobsConnector
from models import SearchQuery
from search import search_jobs

CONNECTORS = {
    "nhs_jobs": NHSJobsConnector,
}


def cmd_search(args: argparse.Namespace) -> None:
    db.init_db()
    results = search_jobs(keyword=args.keyword, location=args.location, source=args.source, limit=args.limit)
    if not results:
        print("No matches in the local database yet. Run `python main.py poll` first to fetch postings.")
        return
    for job in results:
        print(f"[{job.source}] {job.title} — {job.org_name}")
        if job.location:
            print(f"    {job.location}")
        if job.closing_date:
            print(f"    Closes: {job.closing_date}")
        print(f"    {job.url}")
        print()


def cmd_poll(args: argparse.Namespace) -> None:
    db.init_db()
    now = datetime.now(timezone.utc).isoformat()

    sources = [args.source] if args.source else list(CONNECTORS.keys())
    query = SearchQuery(keyword=args.keyword, location=args.location)

    for source_name in sources:
        connector_cls = CONNECTORS.get(source_name)
        if connector_cls is None:
            print(f"[poll] Unknown source: {source_name}")
            continue

        connector = connector_cls()
        print(f"[poll] {source_name}: searching for '{args.keyword}'...")
        refs = list(connector.discover(query, max_pages=args.max_pages))
        print(f"[poll] {source_name}: found {len(refs)} result(s) on page(s) 1-{args.max_pages}")

        with db.get_session() as session:
            for ref in refs:
                try:
                    raw = connector.fetch_detail(ref)
                    job = connector.normalize(raw)
                    db.upsert_job(session, job, seen_at=now)
                    print(f"[poll]   saved: {job.title} — {job.org_name}")
                except Exception as e:
                    print(f"[poll]   failed on {ref.url}: {e}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("api.server:app", host=config.API_HOST, port=config.API_PORT, reload=args.reload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Job Search Assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search jobs already stored in the local database")
    p_search.add_argument("keyword")
    p_search.add_argument("--location", default="")
    p_search.add_argument("--source", default="")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.set_defaults(func=cmd_search)

    p_poll = sub.add_parser("poll", help="Fetch postings from connectors into the local database")
    p_poll.add_argument("keyword")
    p_poll.add_argument("--location", default="")
    p_poll.add_argument("--source", default="", help="Limit to one connector (default: all)")
    p_poll.add_argument("--max-pages", type=int, default=1)
    p_poll.set_defaults(func=cmd_poll)

    p_serve = sub.add_parser("serve", help="Run the local FastAPI backend (Phase 3+)")
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
