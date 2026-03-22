"""Mobile-first HTML report generation for daily briefs."""

from __future__ import annotations

import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


def write_daily_report(
    analysis: str,
    market: dict[str, str],
    positions: dict[str, Any],
    research: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write a styled HTML daily report and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d")
    report_path = output_dir / f"daily-brief-{report_date}.html"
    html = _build_html(analysis, market, positions, research, report_date)
    report_path.write_text(html, encoding="utf-8")
    return report_path


def _build_html(
    analysis: str,
    market: dict[str, str],
    positions: dict[str, Any],
    research: dict[str, Any],
    report_date: str,
) -> str:
    total_value = float(positions.get("total_value", 0.0))
    cash = float(positions.get("cash", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    base_currency = str(positions.get("base_currency", "BASE"))
    holdings = positions.get("positions", [])
    top_holding = holdings[0].get("symbol", "暂无") if holdings else "暂无"

    quick_cards = "".join(
        _build_stat_card(title, value, subtitle, tone)
        for title, value, subtitle, tone in _build_quick_cards(
            total_value, cash, cash_pct, daily_pnl, base_currency, top_holding
        )
    )
    risk_chips = _build_risk_chips(holdings)
    research_chips = _build_research_chips(research)
    holding_rows = "".join(_build_holding_row(position) for position in holdings[:8])
    if not holding_rows:
        holding_rows = '<div class="empty-state">暂无持仓数据</div>'

    analysis_sections = _split_analysis_sections(analysis)
    market_sections = [
        ("市场主线", market.get("brief", "")),
        ("宏观看板", market.get("macro", "")),
        ("组合相关资讯", market.get("portfolio_news", "")),
        ("市场情绪", market.get("sentiment", "")),
    ]
    rendered_market = "".join(_build_text_section(title, content) for title, content in market_sections)
    rendered_analysis = "".join(
        _build_text_section(title, content) for title, content in analysis_sections.items()
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Daily Brief {escape(report_date)}</title>
  <style>
    :root {{
      --page: #f4efe8;
      --panel: #fffaf4;
      --panel-strong: #fffdf9;
      --ink: #1c252b;
      --muted: #687680;
      --line: #ded2c5;
      --accent: #0f5c5b;
      --accent-soft: #ddf0eb;
      --gold: #996515;
      --gold-soft: #f8ead1;
      --danger: #af2e24;
      --danger-soft: #f8dfdc;
      --shadow: 0 14px 36px rgba(53, 35, 22, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top, #f7dcc7 0, transparent 28%),
        linear-gradient(180deg, #f6f1ea 0%, #efe7dc 100%);
      color: var(--ink);
      font-family: "Charter", "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      line-height: 1.5;
    }}
    .page {{
      width: 100%;
      max-width: 720px;
      margin: 0 auto;
      padding: 14px 14px 28px;
    }}
    .hero {{
      background: linear-gradient(160deg, #11353d 0%, #1d5960 55%, #27666c 100%);
      color: #fff8ef;
      border-radius: 28px;
      padding: 22px 18px 18px;
      box-shadow: 0 18px 44px rgba(17, 53, 61, 0.22);
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255, 248, 239, 0.12);
      color: #dbeeed;
      font-size: 12px;
      letter-spacing: 0.02em;
    }}
    .hero h1 {{
      margin: 12px 0 8px;
      font-size: 30px;
      line-height: 1.08;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 0;
      color: #dcebea;
      font-size: 15px;
    }}
    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }}
    .stat-card {{
      background: rgba(255, 248, 239, 0.10);
      border: 1px solid rgba(255, 248, 239, 0.12);
      border-radius: 18px;
      padding: 14px 12px;
      min-height: 92px;
    }}
    .stat-card.good {{ background: rgba(221, 240, 235, 0.16); }}
    .stat-card.warn {{ background: rgba(248, 234, 209, 0.18); }}
    .stat-card.danger {{ background: rgba(248, 223, 220, 0.18); }}
    .stat-label {{
      display: block;
      color: #dcebea;
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .stat-value {{
      display: block;
      font-size: 20px;
      line-height: 1.15;
      font-weight: 700;
    }}
    .stat-note {{
      display: block;
      margin-top: 5px;
      font-size: 12px;
      color: #dcebea;
    }}
    .block {{
      margin-top: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 18px 16px;
      box-shadow: var(--shadow);
    }}
    .block h2 {{
      margin: 0 0 10px;
      font-size: 22px;
      line-height: 1.15;
      letter-spacing: -0.02em;
    }}
    .subcopy {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 14px;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      line-height: 1.2;
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .chip.warn {{ background: var(--gold-soft); color: var(--gold); }}
    .chip.danger {{ background: var(--danger-soft); color: var(--danger); }}
    .holding-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .holding {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
    }}
    .holding-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .holding-title {{
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .holding-tone {{
      font-size: 12px;
      border-radius: 999px;
      padding: 5px 9px;
      background: var(--accent-soft);
      color: var(--accent);
      flex-shrink: 0;
    }}
    .holding-tone.warn {{ background: var(--gold-soft); color: var(--gold); }}
    .holding-tone.danger {{ background: var(--danger-soft); color: var(--danger); }}
    .holding-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 12px;
    }}
    .label {{
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 3px;
    }}
    .value {{
      display: block;
      font-size: 16px;
      font-weight: 700;
    }}
    .section {{
      padding-top: 14px;
      margin-top: 14px;
      border-top: 1px solid var(--line);
    }}
    .section:first-of-type {{
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }}
    .section h3 {{
      margin: 0 0 10px;
      font-size: 18px;
      line-height: 1.2;
    }}
    .bullets {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .bullets li {{
      padding-left: 14px;
      position: relative;
      font-size: 15px;
    }}
    .bullets li::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0.62em;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
    }}
    .empty-state {{
      border: 1px dashed var(--line);
      border-radius: 16px;
      padding: 16px;
      color: var(--muted);
      background: #fffdfa;
    }}
    @media (min-width: 721px) {{
      .page {{
        padding-top: 22px;
      }}
      .hero {{
        padding: 26px 24px 22px;
      }}
      .stat-strip {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
    }}
    @media (max-width: 420px) {{
      .hero h1 {{ font-size: 26px; }}
      .stat-value {{ font-size: 18px; }}
      .holding-grid {{ grid-template-columns: 1fr 1fr; gap: 10px; }}
      .value {{ font-size: 15px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <span class="eyebrow">NZ 晚间报告 · {escape(report_date)}</span>
      <h1>今晚先看账户重点</h1>
      <p>为手机阅读优化。先看状态，再看风险，最后补市场和 AI 解释。</p>
      <div class="stat-strip">{quick_cards}</div>
    </section>

    <section class="block">
      <h2>今晚最该盯的点</h2>
      <p class="subcopy">这部分是给你快速扫一眼的，不需要先读完整报告。</p>
      <div class="chips">{risk_chips}</div>
    </section>

    <section class="block">
      <h2>研究重点</h2>
      <p class="subcopy">先基于你的持仓做组合画像，再围着这些点去抓资讯。</p>
      <div class="chips">{research_chips}</div>
    </section>

    <section class="block">
      <h2>核心持仓</h2>
      <p class="subcopy">按仓位从大到小排列，先看最影响账户波动的几笔。</p>
      <div class="holding-list">{holding_rows}</div>
    </section>

    <section class="block">
      <h2>市场信息</h2>
      <p class="subcopy">把新闻拆成短句，尽量避免看起来像长篇资讯流。</p>
      {rendered_market}
    </section>

    <section class="block">
      <h2>AI 解释</h2>
      <p class="subcopy">先给结论，再补原因和动作建议。</p>
      {rendered_analysis}
    </section>
  </main>
</body>
</html>
"""


def _build_quick_cards(
    total_value: float,
    cash: float,
    cash_pct: float,
    daily_pnl: float,
    base_currency: str,
    top_holding: str,
) -> list[tuple[str, str, str, str]]:
    pnl_tone = "good" if daily_pnl > 0 else "danger" if daily_pnl < 0 else ""
    cash_tone = "warn" if cash_pct < 10 else ""
    return [
        ("总资产", f"{total_value:,.0f} {base_currency}", "账户整体规模", ""),
        ("当日盈亏", f"{daily_pnl:+,.0f} {base_currency}", "今天账户体感", pnl_tone),
        ("现金", f"{cash:,.0f} ({cash_pct:.1f}%)", _describe_cash(cash_pct), cash_tone),
        ("第一大持仓", str(top_holding), "今晚波动先看它", "warn"),
    ]


def _build_stat_card(title: str, value: str, subtitle: str, tone: str) -> str:
    tone_class = f" {tone}" if tone else ""
    return (
        f'<article class="stat-card{tone_class}">'
        f'<span class="stat-label">{escape(title)}</span>'
        f'<span class="stat-value">{escape(value)}</span>'
        f'<span class="stat-note">{escape(subtitle)}</span>'
        "</article>"
    )


def _build_risk_chips(holdings: list[dict[str, Any]]) -> str:
    chips: list[str] = []
    for position in holdings[:6]:
        symbol = str(position.get("symbol", "UNKNOWN"))
        pnl_pct = float(position.get("pnl_pct", 0.0))
        weight_pct = float(position.get("weight_pct", 0.0))
        if pnl_pct <= -20:
            chips.append(_chip_html(f"{symbol} 回撤很深 {pnl_pct:+.1f}%", "danger"))
        elif pnl_pct <= -15:
            chips.append(_chip_html(f"{symbol} 接近止损线 {pnl_pct:+.1f}%", "warn"))
        elif weight_pct >= 30 and not _is_cash_equivalent_position(position):
            chips.append(_chip_html(f"{symbol} 仓位偏重 {weight_pct:.1f}%", "warn"))
        elif pnl_pct > 10:
            chips.append(_chip_html(f"{symbol} 目前盈利领先 {pnl_pct:+.1f}%", ""))

    if not chips:
        chips.append(_chip_html("今晚没有特别刺眼的风险位", ""))
    return "".join(chips[:6])


def _build_research_chips(research: dict[str, Any]) -> str:
    """Render holdings-driven research priorities."""
    chips: list[str] = []

    portfolio_view = str(research.get("portfolio_view", "")).strip()
    if portfolio_view:
        chips.append(_chip_html(portfolio_view, ""))

    for symbol in research.get("focus_symbols", [])[:4]:
        chips.append(_chip_html(f"重点代码：{symbol}", "warn"))

    for theme in research.get("focus_themes", [])[:3]:
        chips.append(_chip_html(f"重点主题：{theme}", ""))

    if not chips:
        chips.append(_chip_html("今晚没有额外的组合研究重点", ""))
    return "".join(chips[:8])


def _chip_html(text: str, tone: str) -> str:
    tone_class = f" {tone}" if tone else ""
    return f'<span class="chip{tone_class}">{escape(text)}</span>'


def _build_holding_row(position: dict[str, Any]) -> str:
    symbol = str(position.get("symbol", "UNKNOWN"))
    currency = str(position.get("currency", ""))
    side = str(position.get("side", "Long"))
    asset_category = str(position.get("asset_category", ""))
    weight_pct = float(position.get("weight_pct", 0.0))
    net_weight_pct = float(position.get("net_weight_pct", 0.0))
    pnl_pct = float(position.get("pnl_pct", 0.0))
    market_value = float(position.get("market_value", 0.0))
    market_value_base = float(position.get("market_value_base", market_value))
    avg_cost = float(position.get("avg_cost", 0.0))
    current_price = float(position.get("current_price", 0.0))
    tone_label, tone_class = _holding_tone(pnl_pct, weight_pct)
    description = _holding_description(side, asset_category, currency, market_value, market_value_base, position)

    return f"""
    <article class="holding">
      <div class="holding-head">
        <span class="holding-title">{escape(symbol)}</span>
        <span class="holding-tone{tone_class}">{escape(tone_label)}</span>
      </div>
      <div class="holding-grid">
        <div><span class="label">绝对仓位</span><span class="value">{weight_pct:.1f}%</span></div>
        <div><span class="label">净敞口</span><span class="value">{net_weight_pct:+.1f}%</span></div>
        <div><span class="label">浮动盈亏</span><span class="value">{pnl_pct:+.1f}%</span></div>
        <div><span class="label">成本价</span><span class="value">{avg_cost:.2f}</span></div>
        <div><span class="label">现价</span><span class="value">{current_price:.2f}</span></div>
        <div><span class="label">基币市值</span><span class="value">{market_value_base:,.0f}</span></div>
        <div><span class="label">本币市值</span><span class="value">{market_value:,.0f} {escape(currency)}</span></div>
        <div><span class="label">仓位属性</span><span class="value">{escape(description)}</span></div>
        <div><span class="label">一句话状态</span><span class="value">{escape(_holding_summary(pnl_pct, weight_pct, side))}</span></div>
      </div>
    </article>
    """


def _holding_tone(pnl_pct: float, weight_pct: float) -> tuple[str, str]:
    if pnl_pct <= -20:
        return "高风险", " danger"
    if pnl_pct <= -10 or weight_pct >= 30:
        return "要留意", " warn"
    return "可观察", ""


def _holding_summary(pnl_pct: float, weight_pct: float, side: str) -> str:
    if pnl_pct <= -20:
        return "回撤已经很深"
    if pnl_pct <= -10:
        return "走势偏弱"
    if weight_pct >= 30:
        return "仓位太重"
    if side.strip().lower() == "short":
        return "这是空头/卖方仓位"
    if pnl_pct >= 15:
        return "表现很强"
    if pnl_pct > 0:
        return "小幅盈利"
    return "接近平盘"


def _holding_description(
    side: str,
    asset_category: str,
    currency: str,
    market_value: float,
    market_value_base: float,
    position: dict[str, Any],
) -> str:
    """Describe how this holding sits in the portfolio."""
    asset_label = asset_category or "Position"
    side_label = "Short" if side.strip().lower() == "short" else "Long"
    fx_rate = float(position.get("fx_rate_to_base", 0.0))
    if currency and fx_rate and fx_rate != 1:
        return f"{side_label} {asset_label} | {currency} -> base @ {fx_rate:.4f}"
    if market_value_base != market_value and currency:
        return f"{side_label} {asset_label} | {currency}"
    return f"{side_label} {asset_label}"


def _is_cash_equivalent_position(position: dict[str, Any]) -> bool:
    """Avoid flagging treasury ETFs as if they were concentrated single-stock bets."""
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description


def _build_text_section(title: str, text: str) -> str:
    lines = [_strip_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        lines = ["暂无内容"]
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    return f'<section class="section"><h3>{escape(title)}</h3><ul class="bullets">{items}</ul></section>'


def _strip_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    cleaned = stripped.lstrip("-• ")
    blocked_fragments = (
        "市场主线",
        "科技与个股",
        "今晚关注",
        "根据搜索结果",
        "说明：",
        "暂无可靠最新数据",
    )
    if any(fragment in cleaned for fragment in blocked_fragments):
        return ""
    return cleaned


def _split_analysis_sections(analysis: str) -> dict[str, str]:
    headings = ("市场判断", "相关资讯", "组合解读", "风险提醒", "今日动作")
    pattern = re.compile(rf"^\s*({'|'.join(headings)})\s*$", re.MULTILINE)
    matches = list(pattern.finditer(analysis))
    if not matches:
        return {"AI 判断": analysis}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(analysis)
        sections[title] = analysis[start:end].strip()
    return sections


def _describe_cash(cash_pct: float) -> str:
    if cash_pct >= 40:
        return "偏防守"
    if cash_pct >= 20:
        return "还有余地"
    if cash_pct >= 10:
        return "处于常规区间"
    return "仓位比较满"
