# Source notes

Per-source recon: robots.txt/ToS findings and the captured request shape, following the connector
decision procedure in the project plan. Update this file whenever a source's behaviour is
re-verified or changes.

## UK visa sponsor register (gov.uk) — cross-source enrichment, not a job connector

Not a job source — a separate signal joined onto every job from every connector, keyed on
`org_name`. The Home Office publishes a free, open, no-auth **Register of Licensed Sponsors
(Workers)**: `gov.uk/government/publications/register-of-licensed-sponsors-workers`, a downloadable
CSV of ~143,000 organisations licensed to sponsor Skilled Worker visas. Checked and downloaded live
2026-09-24: columns `Organisation Name, Town/City, County, Type & Rating, Route`, 10.4MB. The CSV's
own asset URL is dated/hashed and changes with every update, so `visa_sponsor.py` scrapes the
current link off the publication page rather than hardcoding it.

**Confirmed via real matching against employers already in this project's data:**
- `"Manchester University NHS Foundation Trust"` and `"Elysium Healthcare"` — direct matches.
- `"East of England Community Health and Care NHS Trust (Cambridgeshire)"` — **no match** under
  that name. Found instead under `"Cambridgeshire Community Services NHS Trust"` — apparently a
  former legal name the register hasn't caught up with after a rebrand. This is the concrete case
  behind `is_licensed_sponsor()`'s core design rule: it returns `bool | None`, **never `False`** —
  a non-match is not proof of "not a sponsor," since a genuine legal rename like this one can't be
  bridged by any reasonable fuzzy-matching. UI/CLI must never render `None` as a negative claim.

**Update — per-role detection was built after all**, once the user asked the natural follow-up
(does a posting saying "no sponsorship" still show the employer's ✓ badge? yes, which is
misleading). `visa_sponsor.classify_role_sponsorship()` uses the LLM, not regex, specifically
*because* of the boilerplate-vs-genuine-statement ambiguity above — tested directly against the
real HealthJobsUK boilerplate text (correctly classified `not_mentioned`) and two constructed
genuine statements (correctly classified `no_sponsorship`/`sponsorship_available`). Two cost
controls precede any LLM call: a free substring pre-filter (skip immediately if the text doesn't
contain "sponsor" at all — the large majority of ads), and a cache keyed by a hash of the exact
description text (`data/role_sponsorship_cache.json`), since polling re-fetches the same
still-open postings repeatedly. **Live-confirmed on a real, unprompted posting**: searching
"overseas nurse"/"visa sponsorship" surfaced a real "Bank Care Assistant" ad at Agincare containing
"we cannot currently offer sponsorship" — correctly classified `no_sponsorship`, with the CLI
showing "⚠ role states: no sponsorship" exactly as intended.

**Bug found and fixed while building this**: `connectors/nhs_jobs.py`'s description extraction was
`soup.find(id="job_description_large") or soup.find(id="job_overview")` — but
`#job_description_large` exists (empty) on essentially every real posting, so the `or` picked an
empty element over `#job_overview`'s real content, silently. Confirmed live: `raw_description_text`
was empty for 9 of 10 real postings polled before the fix. Real NHS Jobs detail pages actually have
a *third*, differently-named element — `#job_description` (singular, "Main duties of the job") —
plus `#about_organisation` ("About us"). Fixed to join whichever of `job_overview` /
`job_description` / `job_description_large` / `about_organisation` actually have text, checking
content rather than element presence — this also improves full-text search relevance for every
NHS Jobs posting going forward, not just the sponsorship feature that surfaced it.

**Licensing**: gov.uk publications are conventionally Open Government Licence v3.0, though this
specific page didn't state it explicitly when checked — the register is clearly intended for
public reuse (that's its entire purpose), and this project only reads/caches it locally for a
personal tool, never republishes or resells it.

## Poll performance — concurrent sources, not a job connector

The user reported the deployed app "taking too long to load." Diagnosed with real timing against
the live Render deployment (2026-09-24), not guessed:

- Page load itself: 1.3–1.6s. Not the problem.
- `POST /api/jobs/poll?source=nhs_jobs`: **35s for 10 results** — expected and by design, since
  each result's detail page needs its own rate-limited request (3s pacing, a deliberate
  conservative-scraping choice, not weakened here).
- `POST /api/jobs/poll?source=healthjobsuk`: **hung past 40s with no response at all** (curl gave
  up). Same root cause as this file's HealthJobsUK section below — Trac/Civica's infrastructure
  appears to block/badly-rate-limit datacenter IPs, and Render is also a cloud host.
- `source=adzuna` / `source=reed`: under 2s each (fail fast on missing credentials).

The default "poll all sources" button ran these **sequentially** — so a real click waited out NHS
Jobs' ~35s *and then* HealthJobsUK's hang stacked on top, compounding into minutes. Fixed in
`polling.py`: each source now runs in its own thread (`ThreadPoolExecutor`), collected via
`concurrent.futures.as_completed()` with an overall `config.SOURCE_POLL_TIMEOUT_SECONDS` (default
60s) bound — total wait becomes roughly the slowest source, not the sum of all of them, and a
source that exceeds the bound is recorded as a timeout error and abandoned (its thread finishes
independently in the background; any rows it manages to write still land harmlessly) rather than
blocking the response. `connectors/healthjobsuk.py`'s own `httpx.Client` timeout was also lowered
(`config.HEALTHJOBSUK_TIMEOUT_SECONDS`, default 10s, from a hardcoded 20s) so a blocked request
fails on its own well before the poll-level backstop would even need to fire.

**A subtlety caught during implementation, not before**: the first version of this fix iterated
`futures.items()` (insertion order) and called `future.result(timeout=...)` on each one — which
still waits on each future *in that order* regardless of which thread actually finishes first,
silently re-serializing the wait even though the underlying work runs in parallel. Fixed to use
`concurrent.futures.as_completed()`, which yields whichever future finishes next. Caught by
re-testing after the first version still hung past 90s in exactly the pattern it was meant to fix.

**Also required**: `db.py`'s SQLite engine needed `connect_args={"check_same_thread": False}` —
each source's thread opens its own session via the existing `get_session()` pattern (never shares
one across threads), so this only lifts sqlite3's overly strict default rejection of that; SQLite
still serializes actual writes at the file level, no corruption risk.

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
| Description | Join of `#job_overview`, `#job_description` ("Main duties of the job"), `#about_organisation` ("About us"), and `#job_description_large` if any has content — `#job_description_large` exists in the DOM but is *empty* on most real postings (found the hard way, see the bug-fix note further down); filter by actual text, not element presence |
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

## HealthJobsUK (www.healthjobsuk.com) — a Trac/Civica-native connector

**Checked 2026-09-24, via the user's own browser** (this environment is WAF-blocked from every
Trac/Civica property, same as `trac.jobs`/`apps.trac.jobs` — see the Trac section below). This is
the closest thing to a real "Trac connector" that exists: Trac's own candidate dashboard says
*"You can use our national jobs board HealthJobsUK to begin your job search"* — HealthJobsUK is
Trac/Civica's own public search frontend, structurally the same role NHS Jobs plays for NHS Jobs
postings, just covering the wider Trac/Civica customer base (not NHS-exclusive).

1. **`robots.txt` → 404** ("The page you requested was not found on this site") — no
   machine-readable policy, same non-answer as NHS Jobs.
2. **Terms & Conditions** — the footer links to Civica's general corporate terms
   (`civica.com/en-gb/policies-and-statements/terms--conditions`), not a HealthJobsUK-specific
   acceptable-use page. That page *was* reachable from this sandbox (unlike the Trac product
   domains) — fetched and searched for `automat`, `scrap`, `crawl`, `bot`, `robot`, `spider`,
   `harvest`, `aggregat`: **no anti-automation clause found**. Same conclusion as NHS Jobs: no
   explicit prohibition, still worth staying conservative (real UA, rate limits).
3. **Search**: `GET /job_list` with `JobSearch_q=<keyword>` (plus boilerplate
   `JobSearch_d`/`JobSearch_g`/`JobSearch_re*` params observed from a real browser search with no
   location filter applied — replicated as-is for v1; per-location filtering on this source is a
   later refinement). Plain server-rendered HTML, no JSON API, no login required.
4. **Detail pages** were captured as real saved HTML from the user's browser (not just inspected
   via screenshot) and the connector's `normalize()` was tested directly against that real file —
   every field extracted correctly on the first pass: title, employer, town, salary (including a
   `Â£`→`£` mojibake cleanup the saved-HTML encoding needed), contract type, hours, closing date,
   job ref, and a full 18-criterion Person Specification split correctly across 3 categories
   (Qualifications & Training / Experience / Knowledge & Skills) with correct Essential/Desirable
   flags. This is the strongest verification any connector has had besides NHS Jobs itself — built
   from real ground-truth HTML, not documentation or a screenshot.
5. **Bonus over NHS Jobs**: the detail page exposes a real, working, unauthenticated
   **direct Trac apply link** — `https://apps.trac.jobs/job-advert/<id>?ShowJobAdvert=&feedid=<n>`
   — confirmed present in real HTML. NHS Jobs, by contrast, hides this behind a login wall (see
   above). `NormalizedJob.url` still points at the HealthJobsUK detail page itself (consistent with
   every other connector's "always-valid canonical link" pattern, and that page has its own working
   Apply button), not directly at the Trac URL.
6. **`discover()` is now fully live-verified**, not just pattern-inferred. Mid-session, `/job_list`
   (the search endpoint) unexpectedly became reachable from this sandbox — a real live call for
   `JobSearch_q=nurse` returned **52 real, current postings** (list markup: `<li class="hj-job">`
   wraps `<a href="/job/...-vNNN" title="<clean job title>">` — the anchor's `title` attribute is
   the clean title; its text content is the whole card concatenated, so `discover()` uses the
   attribute, not `get_text()`). Also discovered and fixed live: pagination uses `?_pg=<n>`, and
   the `JobSearch_d`/`JobSearch_g`/`JobSearch_re*` boilerplate params turned out to be unnecessary —
   `JobSearch_q` alone returns full results, so the connector was simplified to drop them.
7. **`fetch_detail()` (the `/job/...` detail path specifically) still hits the same "Site
   unavailable" WAF block from this sandbox**, even in the same session where `/job_list` succeeded
   — a path-specific rule, not an environment-wide block. Since the user browsed this exact detail
   page fine in their own browser with no issue, this is almost certainly still just this sandbox's
   datacenter IP being treated differently — `normalize()` itself is already fully verified against
   the real saved HTML the user provided (see point 4), so the only realistic remaining risk is
   network reachability, not parsing correctness. **The user's own first real poll is expected to
   just work**, and is the natural final confirmation.

**Verdict: `connectors/healthjobsuk.py` is httpx-only (no Playwright). `discover()` is live-verified
against real search results; `normalize()` is verified against a real saved detail page; only
`fetch_detail()`'s network reachability from this specific sandboxed environment remains unconfirmed
— registered in `polling.py` alongside the other three sources.**

## Adzuna (api.adzuna.com)

**Official free API** — no scraping-decision procedure needed, but its terms still shape the
implementation (checked via its developer docs, 2026-09-24):

- **Rate limits**: 25 req/min, **250 req/day**, 1000/week, 2500/month. `connectors/adzuna.py`
  enforces the per-minute pacing via the shared `rate_limit.wait_turn()` and additionally guards
  the daily cap explicitly (`rate_limit.check_daily_cap()`, persisted in
  `data/rate_limit_counters.json`) — worth being deliberate about since 250/day is easy to exceed
  with a couple of broad, multi-page polls, and exceeding it risks the key being throttled.
- **Attribution required**: "Jobs by Adzuna" (linked) wherever listings are displayed — implemented
  in `api/static/index.html` as a text link per Adzuna-sourced result. The exact logo asset
  Adzuna's terms describe (116×23px minimum) hasn't been confirmed against the developer portal in
  this session — worth a quick check there once the account exists, though a clear text link is a
  reasonable placeholder for personal use meanwhile.
- **No detail endpoint on the free tier** — search results already contain everything (title,
  company, location, salary_min/max, a description *snippet*, redirect_url, id, contract_type,
  contract_time, created). `AdzunaConnector.fetch_detail()` is therefore a cache lookup against
  what `discover()` already fetched, not a second network call.
- **Field names are from Adzuna's documentation, not a live test call** (no API key was available
  while building this) — the first real poll is the actual verification step.

## Reed (www.reed.co.uk/api)

**Official free API.** Auth is HTTP Basic: API key as the username, password left empty.

- **Rate limits**: no daily cap found in Reed's public docs (unlike Adzuna); ~2000 req/hour is
  documented elsewhere on Reed's platform as a general default. Reed explicitly asks integrators
  to "avoid polling unnecessarily / avoid run-away usage" — `connectors/reed.py` still goes through
  the shared per-request pacing, just with a much shorter default interval than Adzuna's.
- **Search results carry only a short description** — full text needs a second call to
  `/api/1.0/jobs/{jobId}`, so `ReedConnector.fetch_detail()` is a real network call (unlike
  Adzuna's cache-lookup approach above).
- **Field names** (`jobTitle`, `employerName`, `locationName`, `minimumSalary`/`maximumSalary`,
  `contractType`, `jobDescription` as HTML, `jobUrl`, `jobId`, `date`, `expirationDate`) are from
  documentation/general knowledge of this well-established API, **not a live test call** — same
  caveat as Adzuna above; `normalize()` degrades to empty strings/None on any field that turns out
  to be named differently in practice, rather than raising.

## Caveat on all of the above

These checks were run from Claude's sandboxed execution environment, not the user's own machine —
its network path, IP reputation, and geographic location may differ from the user's normal browsing
context in ways that matter for this kind of site (see the Trac findings above, where the same
suffix behaved differently for different hosts). Treat the NHS Jobs findings as solid (multiple
successful real HTML fetches with expected structure) but the Trac findings remain unverified —
Phase 0 for Trac is still outstanding and blocking `trac_generic.py`.
