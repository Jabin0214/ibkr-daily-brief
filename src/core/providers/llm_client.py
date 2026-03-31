"""Unified model access layer for analysis and agent workloads."""

from __future__ import annotations

import os
from typing import Any

import httpx
from anthropic import Anthropic
from openai import OpenAI

from src.core.providers.networking import get_openai_compatible_client

PERPLEXITY_AGENT_BASE_URL = "https://api.perplexity.ai/v1"
PERPLEXITY_CLAUDE_MODEL = "anthropic/claude-sonnet-4-6"
PERPLEXITY_FALLBACK_MODEL = "sonar-pro"
ANTHROPIC_MODEL = "claude-sonnet-4-6"


def run_analysis_model(system_prompt: str, user_prompt: str, max_output_tokens: int = 1800) -> str:
    """Run the preferred model stack: Perplexity Claude -> direct Claude -> Perplexity Sonar.

    Falls through the chain until one succeeds. Returns a fallback string if all fail.
    """
    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if perplexity_key:
        try:
            result = _run_with_perplexity_responses(
                api_key=perplexity_key,
                model=PERPLEXITY_CLAUDE_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
            )
            print("[LLMClient] Perplexity Claude completed.")
            return result
        except Exception as exc:
            print(f"[LLMClient] Perplexity Claude failed: {exc}")

    if anthropic_key:
        try:
            result = _run_with_anthropic(
                api_key=anthropic_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
            )
            print("[LLMClient] Direct Claude completed.")
            return result
        except Exception as exc:
            print(f"[LLMClient] Direct Claude failed: {exc}")

    if perplexity_key:
        try:
            result = _run_with_perplexity_chat(
                api_key=perplexity_key,
                model=PERPLEXITY_FALLBACK_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            print("[LLMClient] Perplexity Sonar fallback completed.")
            return result
        except Exception as exc:
            print(f"[LLMClient] Perplexity Sonar fallback failed: {exc}")

    return "分析生成失败：请检查 Perplexity 或 Claude API 配置。"


def _run_with_perplexity_responses(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> str:
    """Call Perplexity Agent API with a third-party model."""
    http_client = httpx.Client(
        base_url=PERPLEXITY_AGENT_BASE_URL,
        timeout=90.0,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    client = OpenAI(
        api_key=api_key,
        base_url=PERPLEXITY_AGENT_BASE_URL,
        timeout=90.0,
        http_client=http_client,
    )
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=max_output_tokens,
    )
    text = _extract_response_text(response)
    if not text:
        raise ValueError("Empty text returned from Perplexity responses API")
    return text


def _run_with_anthropic(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> str:
    """Call Anthropic directly as a secondary fallback."""
    client = Anthropic(api_key=api_key, timeout=40)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_output_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    result = "\n".join(text_blocks).strip()
    if not result:
        raise ValueError("Empty text returned from Anthropic")
    return result


def _run_with_perplexity_chat(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Call Perplexity chat completions as a final fallback."""
    client = get_openai_compatible_client(api_key, "https://api.perplexity.ai")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("Empty text returned from Perplexity chat completions")
    return content.strip()


def _extract_response_text(response: Any) -> str:
    """Read text safely from an OpenAI-style responses API object."""
    output_text = getattr(response, "output_text", "")
    if output_text:
        return str(output_text).strip()

    fragments: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                fragments.append(str(text))
    return "\n".join(fragment.strip() for fragment in fragments if fragment.strip()).strip()
