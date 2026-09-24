from __future__ import annotations

import config

Content = str | list[dict]


def call_provider(system_prompt: str, content: Content, schema: dict, tool_name: str) -> dict:
    """Provider-agnostic structured-output call, shared by the CV tailoring
    engine (tailoring/llm_client.py) and natural-language search parsing
    (nl_search.py) — anything that needs the configured LLM to return one
    JSON object matching a schema, rather than freeform text.
    """
    provider = config.LLM_PROVIDER.lower()
    if provider == "anthropic":
        from tailoring.providers import anthropic_provider

        return anthropic_provider.generate(system_prompt, content, schema, tool_name)
    elif provider == "openai":
        from tailoring.providers import openai_provider

        return openai_provider.generate(system_prompt, content, schema, tool_name)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r} (expected 'anthropic' or 'openai')")
