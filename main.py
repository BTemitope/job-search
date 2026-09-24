from __future__ import annotations

import argparse
from pathlib import Path

import config
import db
from connectors import manual_paste
from models import SearchQuery
from polling import CONNECTORS, poll_sources
from search import search_jobs
from tailoring import docx_export, llm_client
from tailoring.profile import ProfileError, load_profile


def _role_sponsorship_note(job) -> str:
    if job.role_sponsorship_status == "no_sponsorship":
        return "  ⚠ role states: no sponsorship"
    if job.role_sponsorship_status == "sponsorship_available":
        return "  ✓ role states: sponsorship available"
    return ""


def cmd_search(args: argparse.Namespace) -> None:
    db.init_db()
    results = search_jobs(
        keyword=args.keyword,
        location=args.location,
        source=args.source,
        limit=args.limit,
        min_salary=args.min_salary,
        smart=not args.no_smart,
        sponsors_only=args.sponsors_only,
    )
    if not results:
        print("No matches in the local database yet. Run `python main.py poll` first to fetch postings.")
        return
    for job in results:
        sponsor_note = "  ✓ registered visa sponsor" if job.visa_sponsor_likely else ""
        print(f"[{job.source}] {job.title} — {job.org_name}{sponsor_note}{_role_sponsorship_note(job)}")
        if job.location:
            print(f"    {job.location}")
        if job.salary_range:
            print(f"    {job.salary_range}")
        if job.closing_date:
            print(f"    Closes: {job.closing_date}")
        print(f"    {job.url}")
        print()


def cmd_poll(args: argparse.Namespace) -> None:
    sources = [args.source] if args.source else list(CONNECTORS.keys())

    related = []
    if not args.no_smart:
        from query_expansion import expand_keyword

        related = expand_keyword(args.keyword)
        if related:
            print(f"[poll] also searching related terms: {', '.join(related)}")

    query = SearchQuery(keyword=args.keyword, location=args.location, related_keywords=related)
    result = poll_sources(sources, query, max_pages=args.max_pages)

    for source_name, count in result["counts"].items():
        print(f"[poll] {source_name}: saved {count} posting(s)")
    for err in result["errors"]:
        print(f"[poll] error: {err}")
    print(f"[poll] total saved: {result['saved']}")


def cmd_nlsearch(args: argparse.Namespace) -> None:
    import nl_search

    try:
        parsed = nl_search.parse_query(args.text)
    except Exception as e:
        print(f"[nlsearch] Could not parse query: {e}")
        return

    print(
        f"[nlsearch] parsed: keyword={parsed.keyword!r} location={parsed.location!r} "
        f"min_salary={parsed.min_salary} remote={parsed.remote} contract_type={parsed.contract_type!r} "
        f"sources={parsed.sources or 'all'}"
    )

    from query_expansion import expand_keyword

    related = expand_keyword(parsed.keyword)
    if related:
        print(f"[nlsearch] also searching related terms: {', '.join(related)}")

    sources = parsed.sources or list(CONNECTORS.keys())
    query = SearchQuery(
        keyword=parsed.keyword, location=parsed.location, min_salary=parsed.min_salary, related_keywords=related
    )
    poll_result = poll_sources(sources, query, max_pages=args.max_pages)
    for err in poll_result["errors"]:
        print(f"[nlsearch] poll error: {err}")

    results = search_jobs(
        keyword=parsed.keyword,
        location=parsed.location,
        min_salary=parsed.min_salary,
        contract_type=parsed.contract_type,
        limit=args.limit,
        sponsors_only=args.sponsors_only,
    )
    if not results:
        print("[nlsearch] No matches.")
        return
    for job in results:
        sponsor_note = "  ✓ registered visa sponsor" if job.visa_sponsor_likely else ""
        print(f"[{job.source}] {job.title} — {job.org_name}{sponsor_note}{_role_sponsorship_note(job)}")
        if job.location:
            print(f"    {job.location}")
        if job.salary_range:
            print(f"    {job.salary_range}")
        print(f"    {job.url}")
        print()


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
    p_search.add_argument("--min-salary", type=float, default=None, dest="min_salary")
    p_search.add_argument(
        "--no-smart", action="store_true", help="Match the literal keyword only, no related-term expansion"
    )
    p_search.add_argument(
        "--sponsors-only", action="store_true", help="Only show employers found in the UK licensed visa sponsor register"
    )
    p_search.set_defaults(func=cmd_search)

    p_poll = sub.add_parser("poll", help="Fetch postings from connectors into the local database")
    p_poll.add_argument("keyword")
    p_poll.add_argument("--location", default="")
    p_poll.add_argument("--source", default="", help="Limit to one connector (default: all)")
    p_poll.add_argument("--max-pages", type=int, default=1)
    p_poll.add_argument(
        "--no-smart", action="store_true", help="Poll the literal keyword only, no related-term expansion"
    )
    p_poll.set_defaults(func=cmd_poll)

    p_nlsearch = sub.add_parser("nlsearch", help="Describe what you want in plain English; polls matching sources and searches")
    p_nlsearch.add_argument("text")
    p_nlsearch.add_argument("--max-pages", type=int, default=1)
    p_nlsearch.add_argument("--limit", type=int, default=20)
    p_nlsearch.add_argument(
        "--sponsors-only", action="store_true", help="Only show employers found in the UK licensed visa sponsor register"
    )
    p_nlsearch.set_defaults(func=cmd_nlsearch)

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
