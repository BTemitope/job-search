from __future__ import annotations

import json
from pathlib import Path

import config
from llm import call_provider

_CACHE_PATH = config.BASE_DIR / "data" / "query_expansion_cache.json"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "related_terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Other real job-title variants for the same underlying role/concept.",
        }
    },
    "required": ["related_terms"],
}

SYSTEM_PROMPT = """
You expand a UK job-search keyword into a small set of genuinely related job TITLES — the kind a
recruiter or job board would treat as the same role family. Not loose word-association, not
generic synonyms of the literal word: real job titles a candidate would recognize.

Example: "support" -> ["Support Worker", "Care Assistant", "Healthcare Assistant", "Peer Support Worker"]
Example: "nurse" -> ["Registered Nurse", "Staff Nurse", "Mental Health Nurse", "Nurse Practitioner"]

Return at most {max_terms} terms. If the input is already a specific, narrow job title with no
meaningfully distinct variants, return fewer terms or an empty list rather than padding with
near-duplicates.
""".strip()

TOOL_NAME = "submit_related_terms"


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache))


def expand_keyword(keyword: str, max_terms: int | None = None) -> list[str]:
    """Best-effort: turns "support" into ["Support Worker", "Care Assistant", ...].
    Never raises — on any LLM error (no key set, network failure, bad response)
    this returns [] so callers can just treat expansion as "nothing extra found"
    and fall back to literal-keyword behavior. Cached per lowercased keyword so
    repeat searches don't re-spend LLM cost/latency.
    """
    if not keyword.strip():
        return []

    max_terms = max_terms if max_terms is not None else config.QUERY_EXPANSION_MAX_TERMS
    cache_key = keyword.strip().lower()

    cache = _load_cache()
    if cache_key in cache:
        return cache[cache_key][:max_terms]

    try:
        result = call_provider(
            SYSTEM_PROMPT.format(max_terms=max_terms),
            keyword,
            SCHEMA,
            TOOL_NAME,
        )
    except Exception as e:
        # Don't cache a call failure (no key yet, transient network issue) —
        # only a genuine LLM answer (even an empty one) is worth remembering,
        # so a later retry isn't permanently stuck returning [].
        print(f"[query_expansion] could not expand {keyword!r}: {e}")
        return []

    terms = [t for t in result.get("related_terms", []) if t.strip() and t.strip().lower() != cache_key]
    terms = terms[:max_terms]

    cache[cache_key] = terms
    _save_cache(cache)
    return terms
