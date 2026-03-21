"""Macro data and verified market news retrieval via Perplexity API."""

from __future__ import annotations

import os

from openai import OpenAI

from src.networking import get_openai_compatible_client

MACRO_FALLBACK = "宏观数据暂时不可用：请关注美股期货、VIX、美债收益率、DXY、黄金和原油的最新变化。"
NEWS_FALLBACK = "主新闻快讯暂时不可用：请稍后重试 Perplexity 搜索。"


def get_macro_data() -> str:
    """Fetch key macro indicators from Perplexity."""
    print("[Perplexity] Starting macro data request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY.")
        return MACRO_FALLBACK

    prompt = """请整理一版面向“美股 + 港股持仓用户”的宏观看板。

只输出 5 到 6 行项目符号，每行格式固定为：
- 指标名 | 最新值 | 方向/变化 | 一句话含义

必须尽量覆盖：
- 美股主要指数或期货
- VIX
- 10年期美债收益率
- 美元指数 DXY
- 黄金
- 原油

硬性要求：
- 用简洁中文
- 优先写美国市场和全球风险因子，其次才是会直接影响港股的中国/HK 因子
- 除非当日真的对港股或美元/人民币有直接冲击，否则不要写中国国内政策类泛新闻
- 只保留事实，不要写“根据搜索结果”“说明”“我能提供的最新”
- 不要输出链接、引用编号、括号来源
- 没拿到可靠数字就跳过该项，不要编造
- 最后不要补总结段落"""

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": "你是宏观市场数据助手。只输出简洁事实行，不要链接，不要引用编号，不要免责声明，不要总结段落。",
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

    prompt = """请基于实时搜索生成一版面向“美股 + 港股持仓用户”的市场主线摘要。

输出要求：
- 用中文
- 只输出 6 条以内项目符号
- 每条格式固定为：- 事实。市场含义。
- 先写可核实事实，再写一句市场影响
- 只保留最近 24 小时最重要的内容
- 尽量覆盖：央行/利率、指数或期货、科技股、地缘/大宗、下一交易日关注点

硬性要求：
- 优先级必须是：美联储/美国利率 > 美股指数与美股科技 > 地缘与油价 > 与港股直接相关的中国/HK 因子
- 除非会直接影响港股、汇率或你的持仓，否则不要写泛中国政策新闻
- 不要输出标题、编号、链接、引用编号、来源说明
- 不要写“市场主线/科技与个股/今晚关注”这类小标题
- 不要写拒答语、免责声明、套话
- 没有可靠事实就跳过，不要硬凑"""

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": "你是金融新闻编辑。只输出经过搜索确认的简洁事实行，不要链接，不要引用编号，不要小标题，不要空话。",
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
    return get_openai_compatible_client(api_key, "https://api.perplexity.ai")
