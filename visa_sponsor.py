from __future__ import annotations

import csv
import re
import time

import httpx

import config

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
