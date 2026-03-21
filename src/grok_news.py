"""Market sentiment retrieval via xAI Grok API."""

from __future__ import annotations

import os
from datetime import datetime

from src.networking import get_openai_compatible_client


def get_market_news() -> str:
    """Fetch today's X sentiment and market mood from Grok API."""
    print("[Grok] Starting X sentiment request...")

    api_key = os.getenv("GROK_API_KEY")
    if not api_key:
        print("[Grok] Missing GROK_API_KEY.")
        return "新闻获取失败，请检查Grok API"

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""今天是{today}。请你总结 X 平台上关于全球市场和美股的情绪，不要总结新闻事实。

只输出 4 到 5 条项目符号，每条格式固定为：
- 主题 | 情绪方向 | 一句话解释

必须尽量覆盖：
- 整体风险偏好
- 科技股讨论热度
- 利率/通胀/美联储相关讨论
- 是否出现明显恐慌、FOMO、逼空或避险

硬性要求：
- 不要编号
- 不要写长段落
- 不要输出未经核实的价格或新闻
- 语气像交易员会前摘要，短、硬、直接"""

    try:
        client = get_openai_compatible_client(api_key, "https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-3",
            messages=[
                {
                    "role": "system",
                    "content": "你是市场情绪助手。只总结情绪和讨论方向，不要新闻事实，不要编号，不要长段落。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        print("[Grok] X sentiment request completed.")
        return content.strip() or "新闻获取失败，请检查Grok API"
    except Exception as exc:
        print(f"[Grok] Request failed: {exc}")
        return "新闻获取失败，请检查Grok API"
