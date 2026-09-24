from __future__ import annotations

import csv
import hashlib
import json
import re
import time

import httpx

import config
from llm import call_provider

REGISTER_PAGE_URL = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
CSV_ASSET_RE = re.compile(r'href="(https://assets\.publishing\.service\.gov\.uk/media/[^"]+\.csv)"')

_CACHE_PATH = config.BASE_DIR / "data" / "sponsor_register.csv"

# Suffixes/qualifiers common in NHS/company org names that don't appear
# consistently between how a job posting names an employer and how the
# register lists it — stripped so "X NHS Foundation Trust" and "X" (or "X
# (Some County)") normalize to the same key.
_SUFFIX_RE = re.compile(r"\b(nhs foundation trust|nhs trust|foundation trust|limited|ltd|plc)\b\.?", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

_index: set[str] | None = None


def _normalize_name(name: str) -> str:
    name = _PAREN_RE.sub(" ", name)
    name = _SUFFIX_RE.sub(" ", name)
    name = _PUNCT_RE.sub(" ", name)
    return _WS_RE.sub(" ", name).strip().lower()


def _fetch_current_csv_url() -> str:
    """The register's own CSV asset URL changes with every update (it's
    dated/hashed), so it can't be hardcoded — find it on the publication
    page instead.
    """
    resp = httpx.get(REGISTER_PAGE_URL, headers={"User-Agent": config.USER_AGENT}, timeout=20.0, follow_redirects=True)
    resp.raise_for_status()
    match = CSV_ASSET_RE.search(resp.text)
    if not match:
        raise RuntimeError("Could not find the current sponsor register CSV link on the gov.uk page")
    return match.group(1)


def _download_register() -> None:
    url = _fetch_current_csv_url()
    resp = httpx.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_bytes(resp.content)


def _cache_is_stale() -> bool:
    if not _CACHE_PATH.exists():
        return True
    age_seconds = time.time() - _CACHE_PATH.stat().st_mtime
    return age_seconds > config.SPONSOR_REGISTER_MAX_AGE_DAYS * 86400


def _load_index() -> set[str]:
    global _index
    if _index is not None:
        return _index

    if _cache_is_stale():
        try:
            _download_register()
        except Exception as e:
            print(f"[visa_sponsor] could not refresh sponsor register: {e}")

    if not _CACHE_PATH.exists():
        _index = set()
        return _index

    names: set[str] = set()
    with open(_CACHE_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            org = (row.get("Organisation Name") or "").strip()
            if org:
                names.add(_normalize_name(org))
    _index = names
    return _index


def is_licensed_sponsor(org_name: str) -> bool | None:
    """True if org_name matches the UK Home Office's published register of
    licensed visa sponsors (gov.uk, ~143k orgs, updated multiple times/week
    — cached locally, refreshed after config.SPONSOR_REGISTER_MAX_AGE_DAYS).

    Deliberately never returns False. A non-match can mean the employer
    genuinely isn't a licensed sponsor, OR that they're registered under a
    different legal name the register hasn't caught up with — a real case
    found while building this: "East of England Community Health and Care
    NHS Trust" (a job posting's employer name) is listed in the register as
    "Cambridgeshire Community Services NHS Trust" (its former legal name).
    No fuzzy-matching fixes a genuine rename, so returning None keeps that
    honest — "not found" is not the same claim as "not a sponsor" — instead
    of silently asserting the stronger, unverifiable claim.
    """
    if not org_name.strip():
        return None
    try:
        index = _load_index()
    except Exception as e:
        print(f"[visa_sponsor] lookup failed: {e}")
        return None

    if not index:
        return None

    return True if _normalize_name(org_name) in index else None


# --- Per-role sponsorship status ---------------------------------------
#
# is_licensed_sponsor() above answers "can this employer sponsor at all."
# This answers a different question: "does THIS posting say anything about
# it." The two are independent — an employer can be a general licensed
# sponsor while a specific advertised role is excluded, which is exactly
# why an employer-only badge would be misleading on its own.

NOT_MENTIONED = "not_mentioned"
NO_SPONSORSHIP = "no_sponsorship"
SPONSORSHIP_AVAILABLE = "sponsorship_available"

_ROLE_CACHE_PATH = config.BASE_DIR / "data" / "role_sponsorship_cache.json"
_role_cache: dict[str, str] | None = None

ROLE_SPONSORSHIP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": [NOT_MENTIONED, NO_SPONSORSHIP, SPONSORSHIP_AVAILABLE],
        }
    },
    "required": ["status"],
}

TOOL_NAME = "submit_role_sponsorship_status"

# Grounded in real ambiguity found while building this: a real HealthJobsUK
# posting contains organization-wide boilerplate ("we are unable to offer
# sponsorship for some job roles... this will be identified through
# filtering questions") that reads like a "no" at a glance but is generic
# policy text, not a decision about this specific vacancy.
SYSTEM_PROMPT = """
You read a UK job advert's text and decide whether IT specifically states anything about visa
sponsorship for THIS role — not general policy, not organizational boilerplate.

Classify as exactly one of:
- "no_sponsorship": the advert explicitly states THIS role/vacancy is not eligible for sponsorship,
  or that sponsorship cannot be provided for THIS post.
- "sponsorship_available": the advert explicitly states THIS role is eligible for sponsorship, or
  that a Certificate of Sponsorship / visa sponsorship is available for THIS post.
- "not_mentioned": anything else — including generic organizational disclaimers that don't commit
  either way about this specific role.

Example of generic boilerplate that must be classified "not_mentioned", NOT "no_sponsorship":
"Although we are a registered sponsor organisation, we are unable to offer sponsorship for some
job roles, and this will be identified through filtering questions at the start of any job
application." — This is organization-wide policy explaining a process, not a statement that THIS
role is excluded.

Example of a genuine "no_sponsorship": "This post does not meet the criteria to be sponsored under
the Skilled Worker visa route."

Example of a genuine "sponsorship_available": "This role is eligible for a Certificate of
Sponsorship under the Skilled Worker visa route."

If in doubt, prefer "not_mentioned" — never guess.
""".strip()


def _load_role_cache() -> dict[str, str]:
    global _role_cache
    if _role_cache is not None:
        return _role_cache
    if not _ROLE_CACHE_PATH.exists():
        _role_cache = {}
        return _role_cache
    try:
        _role_cache = json.loads(_ROLE_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        _role_cache = {}
    return _role_cache


def _save_role_cache(cache: dict[str, str]) -> None:
    _ROLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ROLE_CACHE_PATH.write_text(json.dumps(cache))


def classify_role_sponsorship(description_text: str) -> str:
    """Best-effort, cost-controlled classification of what a specific
    posting's own text says about sponsorship for that role (distinct from
    is_licensed_sponsor()'s employer-level check). Two cost controls before
    ever touching the LLM: (1) a free substring pre-filter — most job ads
    never mention sponsorship at all, so those return "not_mentioned"
    immediately; (2) a cache keyed by a hash of the exact text, since
    polling re-fetches the same still-open postings repeatedly and their
    description text doesn't change between polls. Never raises — any LLM
    or network failure degrades to "not_mentioned", the safe non-committal
    default, same as every other LLM-touching path in this codebase.
    """
    if not description_text or "sponsor" not in description_text.lower():
        return NOT_MENTIONED

    cache_key = hashlib.sha256(description_text.encode()).hexdigest()[:24]
    cache = _load_role_cache()
    if cache_key in cache:
        return cache[cache_key]

    try:
        result = call_provider(SYSTEM_PROMPT, description_text, ROLE_SPONSORSHIP_SCHEMA, TOOL_NAME)
        status = result.get("status", NOT_MENTIONED)
        if status not in (NOT_MENTIONED, NO_SPONSORSHIP, SPONSORSHIP_AVAILABLE):
            status = NOT_MENTIONED
    except Exception as e:
        print(f"[visa_sponsor] role classification failed: {e}")
        return NOT_MENTIONED

    cache[cache_key] = status
    _save_role_cache(cache)
    return status
