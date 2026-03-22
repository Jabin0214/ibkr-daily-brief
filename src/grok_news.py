"""Portfolio-aware market sentiment retrieval via xAI Grok API."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.networking import get_openai_compatible_client

GROK_FALLBACK = "市场情绪暂时不可用：请重点关注科技股风险偏好、利率敏感资产与港股情绪。"


def get_market_news(research_plan: dict[str, Any] | None = None) -> str:
    """Fetch today's X sentiment focused on the current portfolio."""
    print("[Grok] Starting X sentiment request...")

    api_key = os.getenv("GROK_API_KEY")
    if not api_key:
        print("[Grok] Missing GROK_API_KEY.")
        return GROK_FALLBACK

    today = datetime.now().strftime("%Y-%m-%d")
    focus_symbols = ", ".join(research_plan.get("focus_symbols", [])) if research_plan else ""
    focus_themes = ", ".join(research_plan.get("focus_themes", [])) if research_plan else ""

    prompt = f"""今天是{today}。请你总结 X 平台上和这份组合最相关的市场情绪。

重点代码：{focus_symbols or "AAPL, SGOV, 港股互联网/高股息, options"}。
重点主题：{focus_themes or "科技股风险偏好、利率、港股情绪、油价与避险"}。

只输出 4 到 5 条项目符号，每条格式固定为：
- 主题 | 情绪方向 | 为什么会影响这份组合

硬性要求：
- 只总结情绪和讨论方向，不要输出未经核实的新闻事实
- 不要编号
- 不要长段落
- 如果某条情绪和组合关系弱，就不要写"""

    try:
        client = get_openai_compatible_client(api_key, "https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-3",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是市场情绪助手。只总结 X 平台上的情绪、热度和讨论方向，"
                        "不要新闻事实，不要编号，不要长段落。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        print("[Grok] X sentiment request completed.")
        return content.strip() or GROK_FALLBACK
    except Exception as exc:
        print(f"[Grok] Request failed: {exc}")
        return GROK_FALLBACK
