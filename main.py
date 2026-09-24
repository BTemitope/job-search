from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import config
import db
from connectors import manual_paste
from connectors.nhs_jobs import NHSJobsConnector
from models import SearchQuery
from search import search_jobs
from tailoring import docx_export, llm_client
from tailoring.profile import ProfileError, load_profile

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


def cmd_tailor(args: argparse.Namespace) -> None:
    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"[tailor] {e}")
        return

    if args.job_id:
        db.init_db()
        with db.get_session() as session:
            record = session.get(db.JobRecord, args.job_id)
            if record is None:
                print(f"[tailor] No job with id {args.job_id} in the local database.")
                return
            job = record.to_normalized()
    elif args.paste:
        raw_text = Path(args.paste).read_text(encoding="utf-8")
        job = manual_paste.from_text(raw_text, title=args.title, org_name=args.org)
    elif args.url:
        job = manual_paste.from_url(args.url, title=args.title, org_name=args.org)
    else:
        print("[tailor] Provide one of --job-id, --paste <file>, or --url")
        return

    print(f"[tailor] Tailoring application for: {job.title} at {job.org_name or '(org unknown)'}...")
    try:
        tailored = llm_client.tailor(profile, job)
    except Exception as e:
        print(f"[tailor] Failed: {e}")
        return

    out_dir = Path(args.out) if args.out else config.BASE_DIR / "data" / "output" / job.id
    paths = docx_export.export_all(profile, tailored, out_dir)
    for name, path in paths.items():
        print(f"[tailor] wrote {path}")

    if tailored.flagged_gaps:
        print("\n[tailor] Flagged gaps — no genuine evidence found in your profile for:")
        for gap in tailored.flagged_gaps:
            print(f"  - {gap}")


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

    p_tailor = sub.add_parser("tailor", help="Generate a tailored CV/cover letter for one job")
    source_group = p_tailor.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--job-id", help="Job id from the local database (see `search`)")
    source_group.add_argument("--paste", help="Path to a text file containing a pasted job description")
    source_group.add_argument("--url", help="URL of a job posting to fetch and tailor against")
    p_tailor.add_argument("--title", default="", help="Job title, if using --paste/--url")
    p_tailor.add_argument("--org", default="", help="Employer/org name, if using --paste/--url")
    p_tailor.add_argument("--profile", default=str(config.PROFILE_PATH))
    p_tailor.add_argument("--out", default="", help="Output directory (default: data/output/<job_id>)")
    p_tailor.set_defaults(func=cmd_tailor)

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
