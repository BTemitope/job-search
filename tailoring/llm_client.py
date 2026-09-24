from __future__ import annotations

from llm import call_provider
from models import CriterionResponse, NormalizedJob, TailoredApplication
from tailoring.profile import Profile
from tailoring.prompts import SYSTEM_PROMPT, TAILORED_APPLICATION_SCHEMA, build_job_block, build_profile_block

TOOL_NAME = "submit_tailored_application"


def tailor(profile: Profile, job: NormalizedJob) -> TailoredApplication:
    # Split so the profile block can carry cache_control — it's identical
    # across every tailoring call in a session, unlike the job block.
    content = [
        {"type": "text", "text": build_profile_block(profile.to_prompt_dict()), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": build_job_block(job)},
    ]

    result = call_provider(SYSTEM_PROMPT, content, TAILORED_APPLICATION_SCHEMA, TOOL_NAME)

    return TailoredApplication(
        job_id=job.id,
        personal_statement=result["personal_statement"],
        tailored_work_history=result["tailored_work_history"],
        criteria_responses=[CriterionResponse(**c) for c in result["criteria_responses"]],
        cover_letter_or_supporting_statement=result["cover_letter_or_supporting_statement"],
        flagged_gaps=result.get("flagged_gaps", []),
    )
