from __future__ import annotations

import anthropic

import config

Content = str | list[dict]


def generate(system_prompt: str, content: Content, schema: dict, tool_name: str, max_tokens: int = 4096) -> dict:
    """Generic structured-output call: force a tool call whose input matches
    `schema`, and return that input dict. `content` is either a plain string
    or a list of Anthropic content blocks — pass blocks with `cache_control`
    on any part that's reused across calls (e.g. tailoring's profile block)
    to benefit from prompt caching; a plain string skips that.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        tools=[
            {
                "name": tool_name,
                "description": f"Submit the structured result for {tool_name}.",
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input

    raise RuntimeError("Anthropic response did not include the expected tool call")
