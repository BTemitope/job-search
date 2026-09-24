from __future__ import annotations

import json

from models import NormalizedJob
from tailoring.ats_rules import FORMATTING_RULES_PROMPT

TAILORED_APPLICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "personal_statement": {
            "type": "string",
            "description": "3-5 paragraph personal statement / professional summary tailored to this specific job.",
        },
        "tailored_work_history": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "employer": {"type": "string"},
                    "title": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "location": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Achievement bullets reworded/reordered for relevance to this job. Facts must come only from the source profile.",
                    },
                },
                "required": ["employer", "title", "start_date", "end_date", "location", "bullets"],
            },
        },
        "criteria_responses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "criterion": {"type": "string"},
                    "essential": {"type": "boolean"},
                    "evidence": {
                        "type": "string",
                        "description": "Genuine evidence from the profile addressing this criterion, or an empty string if none exists.",
                    },
                    "source_bullet_ref": {
                        "type": "string",
                        "description": "Which profile entry this evidence came from (e.g. employer name), for traceability.",
                    },
                },
                "required": ["criterion", "essential", "evidence", "source_bullet_ref"],
            },
        },
        "cover_letter_or_supporting_statement": {
            "type": "string",
            "description": "A full cover letter / supporting statement ready to paste into an application form.",
        },
        "flagged_gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Criteria or requirements the profile has no genuine evidence for. Never fabricate to fill these — list them instead.",
        },
    },
    "required": [
        "personal_statement",
        "tailored_work_history",
        "criteria_responses",
        "cover_letter_or_supporting_statement",
        "flagged_gaps",
    ],
}


SYSTEM_PROMPT = f"""
You are a careful, honest CV and application writer helping a real person apply for a real job.

Non-negotiable rules:
1. NEVER fabricate. Only use facts, dates, employers, qualifications, and figures that appear in
   the supplied profile. If the profile has no genuine evidence for a criterion, put that criterion
   in `flagged_gaps` with an empty `evidence` string — do not invent evidence to fill the gap.
2. This may be an NHS or other public-sector posting evaluated against explicit person-specification
   criteria, sometimes including Values-Based Recruitment criteria (e.g. compassion, dignity,
   respect, teamwork). Address each supplied criterion individually and specifically, using real
   behavioural evidence (situation → action → outcome) from the profile's `values_evidence` and
   `achievements` fields wherever it exists.
3. Select and reorder the person's real work history/achievements for relevance to this specific
   job — do not invent new roles or duties.
4. {FORMATTING_RULES_PROMPT}

Respond only by calling the provided function/tool with the structured output — do not add any
other commentary.
""".strip()


def build_profile_block(profile_dict: dict) -> str:
    """Kept as its own function (rather than inlined in one big prompt) so
    providers can mark it cacheable — it's the same for every tailoring call
    in a session, unlike the job block below.
    """
    return (
        "CANDIDATE PROFILE (structured facts — the only source of truth for this candidate):\n"
        f"{json.dumps(profile_dict, indent=2)}"
    )


def build_job_block(job: NormalizedJob) -> str:
    criteria = [
        {"category": c.category, "text": c.text, "essential": c.essential} for c in job.person_spec_criteria
    ]
    job_dict = {
        "title": job.title,
        "org_name": job.org_name,
        "location": job.location,
        "raw_description": job.raw_description_text,
        "person_specification_criteria": criteria,
    }
    return (
        "TARGET JOB POSTING:\n"
        f"{json.dumps(job_dict, indent=2)}\n\n"
        "Produce a tailored personal statement, reordered/reworded work history, a response to "
        "each person-specification criterion, and a full cover letter / supporting statement, "
        "following the system instructions exactly."
    )


def build_user_prompt(profile_dict: dict, job: NormalizedJob) -> str:
    """Convenience for providers/tests that don't need separate cache_control
    blocks — just the two parts joined.
    """
    return f"{build_profile_block(profile_dict)}\n\n{build_job_block(job)}"
