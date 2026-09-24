from __future__ import annotations

import config
from models import CriterionResponse, NormalizedJob, TailoredApplication
from tailoring.profile import Profile


def tailor(profile: Profile, job: NormalizedJob) -> TailoredApplication:
    provider = config.LLM_PROVIDER.lower()

    if provider == "anthropic":
        from tailoring.providers import anthropic_provider

        result = anthropic_provider.generate(profile, job)
    elif provider == "openai":
        from tailoring.providers import openai_provider

        result = openai_provider.generate(profile, job)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r} (expected 'anthropic' or 'openai')")

    return TailoredApplication(
        job_id=job.id,
        personal_statement=result["personal_statement"],
        tailored_work_history=result["tailored_work_history"],
        criteria_responses=[CriterionResponse(**c) for c in result["criteria_responses"]],
        cover_letter_or_supporting_statement=result["cover_letter_or_supporting_statement"],
        flagged_gaps=result.get("flagged_gaps", []),
    )
