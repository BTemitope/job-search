from __future__ import annotations

from dataclasses import dataclass, field

from llm import call_provider

PARSE_QUERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "keyword": {"type": "string", "description": "The core job role/title to search for."},
        "location": {"type": "string", "description": "A place name, or empty string if none was mentioned."},
        "min_salary": {
            "type": ["number", "null"],
            "description": "Minimum annual salary in GBP if mentioned (e.g. '35k' -> 35000), else null.",
        },
        "remote": {
            "type": ["boolean", "null"],
            "description": "true if remote/hybrid work was explicitly requested, false if explicitly on-site, else null.",
        },
        "contract_type": {
            "type": "string",
            "description": "e.g. 'Permanent', 'Contract', 'Temporary', or empty string if not mentioned.",
        },
        "sources": {
            "type": "array",
            "items": {"type": "string", "enum": ["nhs_jobs", "adzuna", "reed"]},
            "description": "Which sources to search, if the text names a preference (e.g. 'NHS jobs only'). Empty array means all.",
        },
    },
    "required": ["keyword", "location", "min_salary", "remote", "contract_type", "sources"],
}

SYSTEM_PROMPT = """
You turn a free-text job search request into structured search filters. Extract only what the
text actually states — never guess a location, salary, or contract type that wasn't mentioned;
leave those fields empty/null instead. `keyword` should be the core role/title, stripped of the
filter language (location, salary, remote-ness) that belongs in the other fields.
""".strip()

TOOL_NAME = "submit_parsed_query"


@dataclass
class ParsedSearchQuery:
    keyword: str
    location: str = ""
    min_salary: float | None = None
    remote: bool | None = None
    contract_type: str = ""
    sources: list[str] = field(default_factory=list)


def parse_query(text: str) -> ParsedSearchQuery:
    result = call_provider(SYSTEM_PROMPT, text, PARSE_QUERY_SCHEMA, TOOL_NAME)
    return ParsedSearchQuery(
        keyword=result["keyword"],
        location=result.get("location") or "",
        min_salary=result.get("min_salary"),
        remote=result.get("remote"),
        contract_type=result.get("contract_type") or "",
        sources=result.get("sources") or [],
    )
