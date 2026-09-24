from __future__ import annotations

import json

import openai

import config
from models import NormalizedJob
from tailoring.profile import Profile
from tailoring.prompts import SYSTEM_PROMPT, TAILORED_APPLICATION_SCHEMA, build_user_prompt


def generate(profile: Profile, job: NormalizedJob) -> dict:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")

    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    # OpenAI caches repeated prompt prefixes automatically (no explicit
    # cache_control needed) — build_user_prompt puts the unchanging profile
    # block first and the job-specific block second so that prefix stays
    # stable across tailoring calls in a session.
    user_prompt = build_user_prompt(profile.to_prompt_dict(), job)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "tailored_application",
                "strict": True,
                "schema": TAILORED_APPLICATION_SCHEMA,
            },
        },
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI response had no content")
    return json.loads(content)
