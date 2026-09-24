# Job Search Assistant

Searches NHS Jobs and Trac-powered NHS trust career sites for postings matching a role, stores
them locally, and (from Phase 2 onward) tailors a CV/cover letter against a chosen posting and can
autofill the employer's application form via a browser extension.

See `/Users/temitopebakare/.claude/plans/swirling-swinging-newell.md` for the full design/phasing,
and `docs/SOURCE_NOTES.md` for what's actually been verified against each live site.

## Status

- **Phase 0 (recon):** done for NHS Jobs (see SOURCE_NOTES.md); Trac recon blocked on this
  machine's network and needs to be finished by hand on a normal browser.
- **Phase 1 (CLI search):** done and verified against the live NHS Jobs site.
- **Phase 2 (CV tailoring):** not started — needs your master profile data and an LLM API key.
- **Phase 3+ (API, connector-DB wiring, browser extension):** not started.

## Setup

```bash
./setup.sh
source venv/bin/activate
```

Fill in `.env` (copied from `.env.example`) before using tailoring — `LLM_PROVIDER` selects
`anthropic` or `openai`, and the matching `*_API_KEY` must be set.

## Usage (Phase 1)

Fetch postings from a live source into the local database:

```bash
python main.py poll "mental health nurse" --location Manchester --max-pages 2
```

Search what's stored locally:

```bash
python main.py search "podiatrist"
```

Data lives in `data/jobs.db` (SQLite + FTS5), gitignored since it may contain scraped personal
application context. `data/profile.yaml` (your master CV/profile, for Phase 2) is also gitignored.
