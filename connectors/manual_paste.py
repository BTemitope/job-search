from __future__ import annotations

import hashlib
import re

import httpx
from bs4 import BeautifulSoup

import config
from models import Criterion, NormalizedJob

CRITERIA_SECTION_RE = re.compile(
    r"^\s*(person specification|essential criteria|desirable criteria|essential|desirable)\s*:?\s*$",
    re.IGNORECASE,
)

BULLET_PREFIX_RE = re.compile(r"^\s*[-•*•]\s*")


def extract_criteria_from_text(raw_text: str) -> tuple[list[Criterion], list[str]]:
    """Best-effort line-based heuristic: catches "Person Specification" /
    "Essential"/"Desirable" style sections in plain, unstructured text.
    Shared by from_text() below (which also needs the leftover
    non-criteria lines as the description) and by any connector whose
    source gives back a free-text description that might informally list
    requirements (e.g. Adzuna/Reed job ads), which only need the criteria
    half of the return value. Degrades to (empty list, all lines) if
    nothing resembling a criteria section is found.
    """
    lines = raw_text.splitlines()
    criteria: list[Criterion] = []
    other_lines: list[str] = []
    current_level: str | None = None
    in_criteria_block = False

    for line in lines:
        stripped = line.strip()
        section_match = CRITERIA_SECTION_RE.match(stripped)
        if section_match:
            label = section_match.group(1).lower()
            in_criteria_block = True
            if "desirable" in label:
                current_level = "Desirable"
            elif "essential" in label:
                current_level = "Essential"
            continue

        if not in_criteria_block:
            other_lines.append(line)
            continue

        if not stripped:
            continue

        text = BULLET_PREFIX_RE.sub("", stripped)
        if text:
            essential = (current_level or "Essential") == "Essential"
            criteria.append(Criterion(category="General", text=text, essential=essential))

    return criteria, other_lines


def from_text(raw_text: str, title: str = "", org_name: str = "", url: str = "") -> NormalizedJob:
    """Fallback connector for anything not (yet) supported by a dedicated
    connector: the user pastes a job description directly. No HTML
    structure to rely on, so criteria extraction is a best-effort heuristic
    (extract_criteria_from_text) — it degrades to storing the whole text as
    raw_description_text if nothing resembling a criteria section is found,
    per the normalize() contract every connector follows.
    """
    criteria, description_lines = extract_criteria_from_text(raw_text)
    source_id = hashlib.sha256((url or raw_text[:200]).encode()).hexdigest()[:16]

    return NormalizedJob(
        source="manual",
        source_id=source_id,
        title=title or "Pasted job description",
        org_name=org_name,
        url=url,
        raw_description_text="\n".join(description_lines).strip(),
        person_spec_criteria=criteria,
    )


def from_url(url: str, title: str = "", org_name: str = "") -> NormalizedJob:
    """Best-effort fetch of an arbitrary job posting URL not covered by a
    dedicated connector. Structure is unknown, so this just strips all HTML
    and hands the plain text to from_text() — no site-specific parsing.
    """
    client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=20.0, follow_redirects=True)
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    return from_text(text, title=title, org_name=org_name, url=url)
