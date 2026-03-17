"""Portfolio analysis generation via Anthropic Claude or Perplexity fallback."""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from openai import OpenAI


SYSTEM_PROMPT = """你是一个专业的个人投资顾问，风格直接、简洁，像给朋友发消息。
你了解用户的投资规则：
- 止损线：单仓浮亏超过15%需要警告，超过20%强烈建议止损
- 仓位限制：单一持仓不超过总资产30%
- 风格：中长线持有为主，不追短线热点
- 市场：主要持有美股，部分港股

输出要求：
- 适合 Telegram 阅读，短句、分段清晰
- 不要使用 markdown 表格
- 一定结合用户持仓，不要只写宏观
- 优先指出最重要的 2-3 个风险和最可执行的 2-3 个动作
- 建议语气要克制，像投顾晨报，不要用命令口吻替用户直接下单
- 如果某个仓位触发止损线或仓位过高，要明确点名"""


def generate_analysis(news: str, macro: str, positions: dict[str, Any]) -> str:
    """Generate a concise daily portfolio brief with Claude."""
    print("[Analysis] Starting portfolio analysis...")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    user_prompt = f"""【今日市场新闻】
{news}

【宏观数据】
{macro}

【我的持仓】
{_format_positions(positions)}

请输出一版清晰、适合每天早上阅读的投资简报，固定按下面结构：

市场判断
- 用 2 到 3 句话总结市场最重要的变化

组合解读
- 先点评整体仓位和现金水平
- 再逐个点评持仓，优先说风险和仓位是否过重

风险提醒
- 单独列出最需要盯的风险点

今日动作
- 给出 2 到 4 条具体动作建议
- 动作要明确、可执行，但语气保持建议性质，例如“倾向继续持有”“更适合减仓观察”“等待财报后再动”“若跌破某条件应复盘/考虑止损”
- 不要替用户直接做最终交易决定，不要写成命令句"""

    if api_key:
        return _generate_with_claude(api_key, user_prompt)

    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    if perplexity_key:
        print("[Analysis] ANTHROPIC_API_KEY missing, using Perplexity fallback.")
        return _generate_with_perplexity(perplexity_key, user_prompt)

    print("[Analysis] Missing ANTHROPIC_API_KEY and PERPLEXITY_API_KEY.")
    return "分析生成失败：请检查分析模型的 API 配置。"


def _generate_with_claude(api_key: str, user_prompt: str) -> str:
    """Generate the final brief with Anthropic Claude."""
    try:
        client = Anthropic(api_key=api_key, timeout=30)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        result = "\n".join(text_blocks).strip()
        print("[Analysis] Claude analysis completed.")
        return result or "分析生成失败：Claude 未返回有效内容。"
    except Exception as exc:
        print(f"[Analysis] Claude analysis failed: {exc}")
        return "分析生成失败：请稍后重试或检查 Claude API。"


def _generate_with_perplexity(api_key: str, user_prompt: str) -> str:
    """Generate the final brief with Perplexity when Anthropic is unavailable."""
    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
            timeout=30,
        )
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": f"{SYSTEM_PROMPT}\n输出要适合 Telegram 阅读，尽量短句、分段清晰、可执行。",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        print("[Analysis] Perplexity fallback analysis completed.")
        return content.strip() or "分析生成失败：Perplexity 未返回有效内容。"
    except Exception as exc:
        print(f"[Analysis] Perplexity fallback analysis failed: {exc}")
        return "分析生成失败：请稍后重试或检查 Perplexity API。"


def _format_positions(positions: dict[str, Any]) -> str:
    """Format portfolio data for prompt readability."""
    try:
        return json.dumps(positions, ensure_ascii=False, indent=2)
    except Exception:
        return str(positions)
