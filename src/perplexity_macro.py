"""Macro data and verified market news retrieval via Perplexity API."""

from __future__ import annotations

import os

from openai import OpenAI

MACRO_FALLBACK = "宏观数据暂时不可用：请关注美股期货、VIX、美债收益率、DXY、黄金和原油的最新变化。"
NEWS_FALLBACK = "主新闻快讯暂时不可用：请稍后重试 Perplexity 搜索。"


def get_macro_data() -> str:
    """Fetch key macro indicators from Perplexity."""
    print("[Perplexity] Starting macro data request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY.")
        return MACRO_FALLBACK

    prompt = """请整理今日最新宏观市场数据，并尽量附上来源引用：
- 今日美股期货或隔夜主要指数表现
- VIX恐慌指数水平
- 10年期美债收益率
- 美元指数DXY
- 黄金、原油最新价格

请按下面格式输出，每项一行：
- 指标名：最新值，方向变化。来源：https://...

要求：
- 用简洁中文
- 强调数值和方向变化
- 优先使用以下类型的链接：官方机构和数据页，或 Reuters、Bloomberg、CNBC、WSJ、FT、AP、MarketWatch、Yahoo Finance、Trading Economics、CME
- 尽量不要使用中文转载媒体链接，例如 sina、eastmoney、cls、wallstreetcn、stcn、10jqka；如果当天确实没有更好来源，可以退而求其次，但要优先保证有用
- 能给链接就给一个最直接的原始报道或数据页链接
- 如果某项搜不到，就明确写“暂无可靠最新数据”，不要自行猜测。"""

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": "你是宏观市场数据助手，输出带关键数值和直接来源链接的简洁摘要；优先英文一手来源和官方数据页，但要先保证结果可用；没有可靠来源的数据必须明确写暂无可靠最新数据。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        print("[Perplexity] Macro data request completed.")
        return content.strip() or MACRO_FALLBACK
    except Exception as exc:
        print(f"[Perplexity] Request failed: {exc}")
        return MACRO_FALLBACK


def get_market_brief() -> str:
    """Fetch the main verified market news brief from Perplexity."""
    print("[Perplexity] Starting verified market brief request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY for market brief.")
        return NEWS_FALLBACK

    prompt = """请基于实时搜索生成一版今日全球市场和美股的主新闻快讯，准备直接发送到 Telegram。

输出要求：
- 用中文输出
- 文风要像晨报消息，短句、有节奏、不空话
- 分成 3 个部分：市场主线、科技与个股、今晚关注
- 聚焦最近24小时内最重要、可核实的市场事实
- 每条最多两句话，先说事实，再说市场影响
- 每条后面单独补一行“链接：https://...”
- 总长度控制在 9 条以内
- 链接优先来自以下来源：
  1. 官方机构和数据页
  2. Reuters / Bloomberg / CNBC / WSJ / FT / AP / MarketWatch / Yahoo Finance / Trading Economics / CME
- 尽量不要使用中文转载媒体链接，例如 sina、eastmoney、cls、wallstreetcn、stcn、10jqka
- 如果当天拿不到理想信源，也要继续输出可用晨报，但要避免输出“无法生成”“无法完成”等系统拒答语气
- 必须覆盖以下内容：
  1. 美联储或主要央行动态
  2. 美股主要指数或期货表现
  3. 科技股重点新闻
  4. 地缘政治或大宗商品风险
  5. 未来一个交易日最值得关注的事件
- 如果某个关键点没有可靠数据，就不要硬写"""

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": "你是金融新闻编辑，负责输出可信、简洁、适合 Telegram 阅读的市场晨报；优先官方站点和英文一手媒体链接，但不要因为信源不完美就拒答；禁止编造未核实事实。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        print("[Perplexity] Verified market brief completed.")
        return content.strip() or NEWS_FALLBACK
    except Exception as exc:
        print(f"[Perplexity] Market brief failed: {exc}")
        return NEWS_FALLBACK


def _build_client(api_key: str) -> OpenAI:
    """Build a Perplexity OpenAI-compatible client."""
    return OpenAI(
        api_key=api_key,
        base_url="https://api.perplexity.ai",
        timeout=30,
    )
