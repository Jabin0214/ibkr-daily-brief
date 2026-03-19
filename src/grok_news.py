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
    prompt = f"""今天是{today}，请你总结 X 平台上关于全球金融市场和美股的情绪与讨论热点：
1. 市场整体风险偏好是偏多、偏空还是分歧
2. 大家最关注的 3 个主题
3. 科技股讨论热度和情绪
4. 对美联储、利率、通胀的讨论方向
5. 是否出现明显的恐慌、逼空、FOMO 或避险情绪

要求：
- 只总结情绪和讨论方向，不要输出未经核实的新闻事实
- 每条不超过2句话
- 共5到7条
- 语气简洁，像交易员晨会摘要"""

    try:
        client = get_openai_compatible_client(api_key, "https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-3",
            messages=[
                {
                    "role": "system",
                    "content": "你是市场情绪助手，只总结 X 平台上的投资者情绪、热度和讨论方向；不要编造具体新闻或价格。",
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
