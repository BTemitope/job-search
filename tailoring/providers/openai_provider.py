from __future__ import annotations

import json

import openai

import config

Content = str | list[dict]


def _flatten(content: Content) -> str:
    """OpenAI has no explicit cache_control markers — it caches repeated
    prompt prefixes automatically — so a list of Anthropic-style content
    blocks (used for tailoring's cacheable profile block) just gets joined
    back into one string here, in the same order, to preserve that prefix.
    """
    if isinstance(content, str):
        return content
    return "\n\n".join(block["text"] for block in content)


def generate(system_prompt: str, content: Content, schema: dict, tool_name: str) -> dict:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")

    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _flatten(content)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": tool_name, "strict": True, "schema": schema},
        },
    )

    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("OpenAI response had no content")
    return json.loads(result)
