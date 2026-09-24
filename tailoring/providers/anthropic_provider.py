from __future__ import annotations

import anthropic

import config
from models import NormalizedJob
from tailoring.profile import Profile
from tailoring.prompts import SYSTEM_PROMPT, TAILORED_APPLICATION_SCHEMA, build_job_block, build_profile_block

TOOL_NAME = "submit_tailored_application"


def generate(profile: Profile, job: NormalizedJob) -> dict:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    profile_block = build_profile_block(profile.to_prompt_dict())
    job_block = build_job_block(job)

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    # Cached separately from the job block: the profile is
                    # identical across every tailoring call in a session,
                    # the job block is not.
                    {"type": "text", "text": profile_block, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": job_block},
                ],
            }
        ],
        tools=[
            {
                "name": TOOL_NAME,
                "description": "Submit the structured tailored application.",
                "input_schema": TAILORED_APPLICATION_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block.input

    raise RuntimeError("Anthropic response did not include the expected tool call")
