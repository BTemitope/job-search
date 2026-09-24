# Source notes

Per-source recon: robots.txt/ToS findings and the captured request shape, following the connector
decision procedure in the project plan. Update this file whenever a source's behaviour is
re-verified or changes.

## NHS Jobs (www.jobs.nhs.uk)

**Checked:** 2026-09-24, from a sandboxed cloud dev environment (see caveat at the bottom).

1. **robots.txt** — `https://www.jobs.nhs.uk/robots.txt` and the `beta.jobs.nhs.uk` alias both
   return the app's own "Service Domain Information / this page is no longer active" fallback
   page, not a machine-readable robots policy. Treated as "no answer," not permission.
2. **Terms & Conditions** — `https://www.jobs.nhs.uk/candidate/acceptable-use` ("Candidate Terms
   and Conditions for NHS Jobs", last updated 22 July 2025). Full text fetched and searched for
   `automat`, `scrap`, `crawl`, `bot`, `robot`, `spider`, `harvest` — **no anti-automation/anti-scraping
   clause found**. The terms are about application conduct (truthful info, password security,
   being redirected to third-party ATS systems), not site access. Conclusion: no explicit
   prohibition, but no explicit permission either — stay conservative anyway (real User-Agent,
   heavy rate limiting, read-only, no login).
3. **Search results are server-rendered HTML**, no JSON API, no JS/Playwright required:
   ```
   GET https://www.jobs.nhs.uk/candidate/search/results?keyword=<kw>&page=<n>
   ```
   Returns real job listings inline (`search-result-*` CSS classes), each linking to
   `/candidate/jobadvert/<reference>` (e.g. `E0132-26-1927`).
4. **Job detail pages** (`/candidate/jobadvert/<reference>`) are also plain server-rendered HTML
   containing the org name, title, closing date, "Job summary" / "Main duties" free text, and a
   **"Person Specification"** section (present as a text heading — structure of the criteria
   underneath still needs a real detail-page parse to nail down, since Phase 0 only confirmed the
   heading exists, not its exact markup).
5. **Apply flow requires login, and hides the true external URL until then.** Each detail page has
   an "Apply for this job" button pointing to `/candidate/jobadvert/<reference>/ats-direct-apply`.
   Fetched unauthenticated: this returns a 200 "You are leaving NHS Jobs" interstitial saying the
   job is on a third-party website and you must register/login *there* — but the actual outbound
   URL is not present in the page HTML (no plain `<a href>`; the "Continue" control is a form POST,
   and the real redirect target is presumably only resolved after that POST, likely gated behind an
   authenticated session). **Design decision: store the NHS Jobs advert URL
   (`https://www.jobs.nhs.uk/candidate/jobadvert/<reference>`) as `NormalizedJob.url`, not the
   unresolved third-party target.** This is always a valid, working link for the user to click
   "Apply" from themselves; chasing the authenticated redirect is out of scope and would require
   simulating a login.
6. This also means: **many Trac-hosted trust vacancies are already discoverable through the NHS
   Jobs connector itself** (as postings that redirect off-site on Apply), so `NHS_JOBS` connector
   coverage overlaps with what a `TracConnector` would find directly on a trust's own site. The
   dedicated `TracConnector` is still worth building (per the approved plan) for trusts/postings
   that never surface on the national site, and to eventually support live in-page form autofill,
   which requires being on the trust's own site anyway.

**Verdict: proceed with an `httpx`-only connector (no Playwright) for NHS Jobs.** Confirmed working
end-to-end on 2026-09-24 (Phase 1 implementation): search, detail fetch, and Person Specification
parsing all verified against live postings, including a full essential/desirable criteria breakdown
on a real "Specialist Podiatrist" posting.

**Field id map** (detail page, `/candidate/jobadvert/<reference>`), for reference:

| Field | Selector |
|---|---|
| Title | `#heading` |
| Employer/org name | `#employer_name` |
| Closing date | `#closing_date` (strip the "The closing date is " prefix) |
| Date posted | `#date_posted` |
| Salary | `#negotiable_salary`, else the `<p>` after the `<h3>` reading "Salary" |
| Contract type | `#contract_type` |
| Working pattern | the `<p>` after `#working_pattern_heading` |
| Reference number | `#trac-job-reference` when present (confirms the posting originates from Trac) |
| Location | `#employer_town` / `#employer_county` / `#employer_postcode` |
| Description | `#job_description_large` (fuller) or `#job_overview` (fallback) |
| Person Specification | `<h2>Person Specification</h2>` then sibling `<h3>` (category) / `<h4>` (Essential or Desirable) / `<ul><li>` (criteria text), repeating per category. Rendered twice on the page (a `hide-mobile` div and a duplicate `show-mobile` `<details>`) — only the first (`<h2>`-based) occurrence should be parsed. |

**Search result item map** (`/candidate/search/results?keyword=<kw>&location=<loc>&page=<n>`):
job link + title at `a[data-test="search-result-job-title"]` (href contains
`/candidate/jobadvert/<reference>`), org name + location inside the sibling
`[data-test="search-result-location"]` block, pagination via `.nhsuk-pagination` with a
"Page X of Y" label.

**Caveat on combined keyword+location searches:** NHS Jobs' own "Best Match" relevance sorting is
loose once both a keyword and a location are supplied — a live test for `keyword=mental health
nurse&location=Manchester` returned "105 jobs found" but the top results were broadly
healthcare-adjacent roles (GP, Data Analyst, Consultant) rather than literal nursing posts. This is
the site's own ranking behavior, not a connector bug — `discover()` faithfully returns whatever the
site ranks first. If tighter relevance is needed later, consider keyword-only queries plus
client-side re-ranking rather than relying on the site's combined-filter "Best Match".

## Trac (trac.jobs and individual trust subdomains, e.g. jobs.uhnm.nhs.uk)

**Checked twice** (2026-09-24), from Claude's sandboxed cloud dev environment, using two
independent fetch mechanisms (raw `curl` with realistic browser headers, and a separate fetch tool
with its own network path). **Both attempts agree — this environment genuinely cannot complete
Trac recon; it must be done from a normal residential/office network.**

- `https://trac.jobs/`, `https://www.trac.jobs/`, `https://apps.trac.jobs/` consistently return
  **HTTP 403** — the connection succeeds but is blocked at a WAF/bot-protection layer, even with a
  realistic Chrome user-agent and standard Accept/Accept-Language headers. Consistent with the
  plan's anticipation of anti-bot measures on Trac.
- Individual trust subdomains — `jobs.uhnm.nhs.uk` (University Hospitals of North Midlands, the
  plan's placeholder trust) and `jobs.nhsbsa.nhs.uk` — consistently **fail to connect at all**
  (TCP-level timeout / connection refused), while `www.jobs.nhs.uk` (a similarly-suffixed
  `*.nhs.uk` domain) works fine. This looks like infra/geo-blocking specific to individual trust
  hosting or its CDN, not a blanket `*.nhs.uk` block, and not something worth routing around (e.g.
  via a proxy) — doing so would cross from "conservative scraping" into anti-bot evasion, which the
  plan explicitly rules out.

**Action required (Phase 0, human, real machine) — not yet done:** open
`https://jobs.uhnm.nhs.uk/` (or whichever trust is actually the target) in a real browser on your
own network, confirm it loads, read its robots.txt/Terms/Acceptable-Use, and use DevTools →
Network while performing a normal search to see whether results come back as a JSON XHR call or
plain HTML — then update this section and proceed with `trac_generic.py` per the connector
decision procedure in the plan.

## Caveat on all of the above

These checks were run from Claude's sandboxed execution environment, not the user's own machine —
its network path, IP reputation, and geographic location may differ from the user's normal browsing
context in ways that matter for this kind of site (see the Trac findings above, where the same
suffix behaved differently for different hosts). Treat the NHS Jobs findings as solid (multiple
successful real HTML fetches with expected structure) but the Trac findings remain unverified —
Phase 0 for Trac is still outstanding and blocking `trac_generic.py`.
