# Job Search Assistant

Searches NHS Jobs and Trac-powered NHS trust career sites for postings matching a role, stores
them locally, and (from Phase 2 onward) tailors a CV/cover letter against a chosen posting and can
autofill the employer's application form via a browser extension.

See `/Users/temitopebakare/.claude/plans/swirling-swinging-newell.md` for the full design/phasing,
and `docs/SOURCE_NOTES.md` for what's actually been verified against each live site.

A minimal web UI (FastAPI) wraps search/poll for browser use — see "Usage (web)" below; it can be
deployed to Render via the included `render.yaml`.

## Status

- **Phase 0 (recon):** done for NHS Jobs (see SOURCE_NOTES.md); Trac recon blocked on every
  network this has been tried from (sandboxed dev environments) and needs to be finished by hand
  on a normal residential/office network with a real browser.
- **Phase 1 (CLI + web search):** done and verified against the live NHS Jobs site, both via the
  CLI and the FastAPI web UI.
- **Phase 2 (CV tailoring):** built and verified end-to-end (profile loading, manual-paste
  criteria extraction, prompt building, ATS-compliant docx export all tested and working) —
  **except the actual LLM call**, which needs a real API key in `.env` (not yet supplied). Once a
  key is added, `python main.py tailor` should work as-is.
- **Phase 3+ (connector-DB↔tailoring API wiring, browser extension):** not started.

## Setup

```bash
./setup.sh
source venv/bin/activate
```

Then:
1. Add an `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` to `.env` (whichever `LLM_PROVIDER` you set)
   — never commit real keys; `.env` is gitignored.
2. Copy `profile.example.yaml` to `data/profile.yaml` and fill in your real CV details. Only put
   in facts you can back up — the tailoring engine is instructed never to invent anything beyond
   what's here, so gaps show up as flagged gaps rather than fabrication.

## Usage (CLI)

Fetch postings from a live source into the local database:

```bash
python main.py poll "mental health nurse" --location Manchester --max-pages 2
```

Search what's stored locally:

```bash
python main.py search "podiatrist"
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
