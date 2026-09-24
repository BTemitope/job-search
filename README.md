# Job Search Assistant

Searches NHS Jobs, HealthJobsUK (Trac/Civica's own national jobs board — the real route into
Trac-powered postings, found via the user's own Trac dashboard), Adzuna, and Reed for postings
matching a role, stores them locally, and tailors a CV/cover letter against a chosen posting. A
natural-language search box lets you describe what you want in plain English instead of filling
separate fields. A browser extension for autofilling employer application forms is planned but not
yet built.

See `/Users/temitopebakare/.claude/plans/swirling-swinging-newell.md` for the full design/phasing,
and `docs/SOURCE_NOTES.md` for what's actually been verified against each live site.

A minimal web UI (FastAPI) wraps search/poll for browser use — see "Usage (web)" below; it can be
deployed to Render via the included `render.yaml`.

## Status

- **Phase 0 (recon):** done for NHS Jobs and HealthJobsUK (see SOURCE_NOTES.md). Direct
  `trac.jobs`/individual-trust-subdomain recon is still blocked from every sandboxed environment
  tried — but HealthJobsUK (found via the user's own Trac candidate dashboard) turned out to be
  the actual national search frontend for Trac-powered postings, same role NHS Jobs plays for NHS
  postings, so this gap matters much less now.
- **Phase 1 (CLI + web search):** done and verified against the live NHS Jobs site, both via the
  CLI and the FastAPI web UI.
- **Phase 2 (CV tailoring):** built and **live-verified** against a real Anthropic key — still
  needs `data/profile.yaml` filled in with real CV details before `python main.py tailor` can be
  tried end-to-end (see Setup below).
- **Phase 6 (HealthJobsUK connector, Adzuna + Reed connectors, natural-language search):** built
  and **live-verified**. HealthJobsUK: `discover()` confirmed live against 52 real postings;
  `normalize()` confirmed against a real saved detail page (18-criterion Person Specification
  parsed correctly, salary/employer/closing date all correct) — only `fetch_detail()`'s network
  reachability from this specific sandboxed dev environment is unconfirmed (search works, detail
  pages hit a WAF block here specifically; the user's own browser had no trouble with the same
  page, so this should just work for them). The NL parser and tailoring LLM call are both confirmed
  working against a real Anthropic key (locally and on the deployed Render app). Adzuna/Reed still
  need credentials added (both in local `.env` and Render's Environment tab — they're separate)
  before those two sources return anything; NHS Jobs and HealthJobsUK already work fully on both.
- **Phase 7 (smart keyword search):** built and **live-verified** — a keyword search now expands
  to related real job titles via the LLM (e.g. "support" → also searches "Support Worker", "Care
  Assistant", "Healthcare Assistant") before polling and when re-searching locally, cached per
  keyword so repeat searches don't re-spend LLM cost. Confirmed live: a plain "support" search now
  surfaces Care Assistant/Healthcare Assistant/Peer Support Worker postings it previously missed.
  Adzuna deliberately stays literal-only (no expansion) to protect its tight 250/day quota — NHS
  Jobs and Reed both get the full expansion since their limits are far looser. Use `--no-smart`
  (CLI) or `smart=false` (API) to fall back to literal-keyword-only matching.
- **Phase 9 (visa sponsorship signal):** built and **live-verified** — every job, from every
  source, is checked against the UK Home Office's public register of licensed visa sponsors
  (~143k employers, cached locally, refreshed weekly) and flagged with a "✓ registered visa
  sponsor" badge when the employer matches. Confirmed live against real postings (multiple genuine
  NHS Foundation Trusts matched correctly). Deliberately never claims an employer is *not* a
  sponsor — a real rename case was found during testing (an employer registered under its former
  legal name) proving that "no match" isn't reliable evidence either way, so unmatched employers
  just show no badge rather than a false negative. Filter with `--sponsors-only` (CLI) or the
  "Only show employers registered as UK visa sponsors" checkbox (web).
- **Phase 10 (per-role sponsorship status):** built and **live-verified on a real, unprompted
  posting** — searching "overseas nurse"/"visa sponsorship" surfaced a real NHS Jobs ad (Agincare,
  "Bank Care Assistant") stating "we cannot currently offer sponsorship," which was correctly
  classified `no_sponsorship` and shown as "⚠ role states: no sponsorship" — distinct from, and a
  necessary complement to, the employer-level badge above (an employer can be a general sponsor
  while a specific role is excluded). Uses the LLM rather than keyword matching specifically
  because a real ad's generic boilerplate disclaimer text would false-positive a naive regex; a
  free substring pre-filter and a per-posting cache keep LLM calls limited to postings that
  actually mention sponsorship. **Bug fixed along the way**: `connectors/nhs_jobs.py` was silently
  picking an empty HTML element over real content for the description field on ~90% of postings
  (`raw_description_text` was empty) — fixed, which also improves full-text search relevance for
  everything already using that field.
- **Phase 11 (concurrent source polling — fixing real measured slowness):** built and
  **live-verified with real timing, before and after**. Diagnosed against the deployed Render app:
  NHS Jobs took 35s for 10 results (expected — deliberate rate-limiting), HealthJobsUK hung past
  40s with no response from a cloud IP, and the old sequential poll waited out both, one after
  another. Fixed: every source now polls concurrently in its own thread
  (`concurrent.futures.ThreadPoolExecutor` + `as_completed()`), bounded by an overall
  `SOURCE_POLL_TIMEOUT_SECONDS` (default 60s) so one stuck source can't block the response — it's
  recorded as a timeout and abandoned instead. Confirmed: polling all four sources together (one
  genuinely hanging) now returns in exactly 60.0s with NHS Jobs' 10 real results intact, instead of
  90s+/effectively unbounded before.
- **Browser extension autofill:** not started.

## Setup

```bash
./setup.sh
source venv/bin/activate
```

Then, as needed:
1. Add an `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` to `.env` (whichever `LLM_PROVIDER` you set)
   — needed for both CV tailoring and natural-language search. Never commit real keys; `.env` is
   gitignored.
2. Copy `profile.example.yaml` to `data/profile.yaml` and fill in your real CV details (needed for
   tailoring). Only put in facts you can back up — the tailoring engine is instructed never to
   invent anything beyond what's here, so gaps show up as flagged gaps rather than fabrication.
3. Add `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (free signup at developer.adzuna.com) and/or
   `REED_API_KEY` (free signup at reed.co.uk/developers) to search beyond NHS Jobs.

## Usage (CLI)

Fetch postings from a live source into the local database:

```bash
python main.py poll "mental health nurse" --location Manchester --max-pages 2
```

Search what's stored locally:

```bash
python main.py search "support"                    # also matches Care Assistant, Healthcare Assistant, etc.
python main.py search "podiatrist" --min-salary 40000
python main.py search "podiatrist" --no-smart       # literal keyword only, no related-term expansion
python main.py search "podiatrist" --sponsors-only  # only employers found in the UK licensed visa sponsor register
```

Or describe what you want in plain English — this parses your request with the LLM, polls the
sources it identifies, and searches (needs an LLM key in `.env`):

```bash
python main.py nlsearch "senior nurse roles in Manchester paying above £35k"
```

Tailor a CV + cover letter against a stored job, a pasted job description, or a URL:

```bash
python main.py tailor --job-id <id from search output>
python main.py tailor --paste path/to/job_description.txt --title "Staff Nurse" --org "Example NHS Trust"
python main.py tailor --url "https://example.com/job/123"
```

Output lands in `data/output/<job_id>/`: `CV.docx`, `cover_letter.docx`,
`supporting_statement.txt` (for pasting into an online application's free-text box), and
`criteria_responses.txt` (a per-criterion breakdown, including any flagged gaps).

## Usage (web)

```bash
uvicorn api.server:app --reload
```

Open `http://127.0.0.1:8000` — same search/poll flow as the CLI, in a browser. Deployed
separately to Render (see the repo's deploy instructions); note the free tier's disk isn't
persistent across deploys, so `data/jobs.db` resets on redeploy there.

Data lives in `data/jobs.db` (SQLite + FTS5) and `data/profile.yaml` / `data/output/` — all
gitignored since they hold scraped application context and personal CV data.
