# AI Portfolio Copilot

基于 Python 3.11 的个人投资组合日报系统。每个交易日自动拉取 IBKR 持仓报表、并行抓取实时市场情报，使用多级 AI 模型生成针对当前持仓的个性化简报，并通过 Telegram 推送 HTML 报告到手机。

系统设计目标不是一次性脚本，而是一个可持续演进的 **AI Portfolio Copilot**：Pipeline 模式负责每日自动跑批，未来的 Agent 模式可复用同一套核心能力进行多轮问答和交互分析。

---

## 目录

- [功能状态总览](#功能状态总览)
- [系统架构](#系统架构)
- [数据流](#数据流)
- [简报结构](#简报结构)
- [快速开始](#快速开始)
- [CLI 使用说明](#cli-使用说明)
- [API 与配置](#api-与配置)
- [IBKR Flex Query 配置](#ibkr-flex-query-配置)
- [GitHub Actions 自动化](#github-actions-自动化)
- [部署 Checklist](#部署-checklist)
- [运维建议](#运维建议)
- [待开发功能](#待开发功能)

---

## 功能状态总览

### 已实现（生产可用）

| 功能 | 模块 | 说明 |
|------|------|------|
| IBKR Flex Query 拉取 | `core/providers/ibkr_client.py` | 原始 XML 拉取、日期新鲜度轮询 |
| 持仓归一化 | `core/analysis/position_analysis.py` | 多货币换算、仓位权重、空头方向、风险标志 |
| 研究计划生成 | `core/analysis/position_analysis.py` | 纯代码生成，无额外 AI 调用，基于持仓自动确定关注代码/主题/问题 |
| AI 市场情报网关 | `core/providers/ai_client.py` | Perplexity sonar-pro（主新闻+宏观+组合资讯） + Grok grok-3（X 情绪） |
| 市场上下文聚合 | `core/analysis/market_context.py` | 并行拉取后组装为 `MarketContext` dataclass |
| AI 最终分析 | `core/providers/ai_client.py` | 三级降级：Perplexity Claude → 直连 Anthropic → Perplexity Sonar |
| Pipeline 编排 | `pipeline/daily_report.py` | 5 阶段顺序编排，返回 `DailyReportArtifacts` 结构体 |
| Telegram 消息 | `interface/telegram/brief_builder.py` | 带账户快照、市场情报、AI 分析的结构化消息 |
| HTML 报告生成 | `interface/telegram/html_report.py` | 移动端优先 HTML，含 hero 区、持仓列表、情报、AI 分析 |
| Telegram 投递 | `interface/telegram/notify.py` + `delivery.py` | 发文字消息 / 发 HTML 文档 / 失败告警 |
| CLI 入口 | `main.py` | 5 种运行模式，~130 行薄封装 |
| GitHub Actions | `.github/workflows/daily_brief.yml` | 周二至周六 UTC 03:45 定时触发，最长等待 120 分钟 |
| 单元测试 | `tests/test_portfolio_math.py` | 多货币权重计算、空头方向、研究计划优先级、新闻过滤 |

### 待开发（占位符 / 空文件）

| 功能 | 模块 | 说明 |
|------|------|------|
| Agent 编排器 | `agent/orchestrator.py` | 多轮对话规划与工具路由，目前空文件 |
| Agent 记忆 | `agent/memory.py` | 对话历史、用户偏好持久化，目前空文件 |
| Agent 评审层 | `agent/reviewer.py` | 事实核查、风险核查、置信度打分，目前空文件 |
| Agent 工具注册 | `agent/tools/registry.py` | 内部工具暴露给编排器，目前空文件 |
| 报告持久化 | `storage/report_store.py` | 历史报告和分析 artifact 存储，目前空文件 |
| 记忆持久化 | `storage/memory_store.py` | 用户偏好和会话历史存储，目前空文件 |
| 持仓 Schema | `core/schemas/portfolio.py` | 持仓级跨模块数据契约，目前空文件 |
| 市场 Schema | `core/schemas/market.py` | 市场事件数据契约，目前空文件 |
| 决策 Schema | `core/schemas/decision.py` | 决策输出契约，目前空文件 |
| 决策上下文 | `core/analysis/decision_context.py` | 组合 + 市场 + 记忆合并上下文，目前空文件 |
| 市场纯分析引擎 | `core/analysis/market_analysis.py` | 独立的市场解读，不依赖持仓，目前空文件 |
| 确定性风险引擎 | `core/analysis/risk_engine.py` | 基于规则的风险评分与告警，目前空文件 |

---

## 系统架构

项目采用模块化单体架构（Modular Monolith），所有业务能力按层隔离，Pipeline 和未来 Agent 共用同一套核心层。


```text
src/
├── core/
│   ├── providers/              # 外部数据接入层（全部已实现）
│   │   ├── networking.py           HTTP 连接池 & OpenAI 兼容客户端工厂
│   │   ├── ibkr_client.py          IBKR Flex Query 原始 XML 拉取、日期轮询
│   │   ├── ai_client.py            统一 AI 网关：市场情报 + 最终分析模型调用
│   ├── analysis/               # 核心分析层（4 个已实现，3 个空文件）
│   │   ├── portfolio_context.py        ✅ 原始 XML → 结构化分析 payload，含多账户合并
│   │   ├── position_analysis.py        ✅ 持仓归一化、研究计划生成、风险标志
│   │   ├── market_context.py           ✅ 并行拉取 → MarketContext dataclass
│   │   ├── portfolio_market_analysis.py  ✅ 最终 AI 简报生成
│   │   ├── decision_context.py         🚧 待开发：组合+市场+记忆合并上下文
│   │   ├── market_analysis.py          🚧 待开发：独立市场解读引擎
│   │   └── risk_engine.py              🚧 待开发：确定性风险评分
│   └── schemas/                # 跨模块数据契约（全部空文件）
│       ├── portfolio.py            🚧 待开发
│       ├── market.py               🚧 待开发
│       └── decision.py             🚧 待开发
├── pipeline/
│   └── daily_report.py         ✅ 5 阶段 Pipeline 编排 + DailyReportArtifacts 结构体
├── interface/
│   └── telegram/               # 全部已实现
│       ├── delivery.py             ✅ 投递入口（report / message / failure alert）
│       ├── presenter.py            ✅ pipeline 输出 → Telegram 渲染层
│       ├── brief_builder.py        ✅ Telegram 消息拼装 & MarketSnapshot 数据契约
│       ├── notify.py               ✅ Telegram Bot API（发文字 / 发文件）
│       └── html_report.py          ✅ 移动端优先 HTML 报告生成器
├── agent/                      # Agent 层（全部空文件）
│   ├── orchestrator.py             🚧 待开发：意图理解与工具路由
│   ├── reviewer.py                 🚧 待开发：事实与风险核查
│   ├── memory.py                   🚧 待开发：对话与偏好记忆
│   └── tools/registry.py           🚧 待开发：内部工具注册表
└── storage/                    # 持久化层（全部空文件）
    ├── report_store.py             🚧 待开发：历史报告归档
    └── memory_store.py             🚧 待开发：用户偏好与会话持久化
main.py                         ✅ 薄 CLI bootstrap（~130 行，不含业务逻辑）
```

### 分层职责

| 层 | 职责 | 禁止 |
|---|---|---|
| `core/providers` | 连接外部系统、拉取原始数据、处理重试降级 | 业务判断、报告生成 |
| `core/analysis` | 消费结构化输入、输出结构化结论 | 直接发 Telegram、处理原始 API 格式 |
| `core/schemas` | 定义跨模块数据契约 | 业务逻辑、API 请求 |
| `pipeline` | 按顺序编排固定业务流 | 动态调度、用户交互 |
| `interface` | 格式化输出、对接推送渠道 | 核心业务逻辑、访问原始 IBKR XML |
| `agent` | 理解用户意图、调用核心能力、多轮规划 | 重复实现 core 层逻辑 |
| `storage` | 持久化报告、记忆、会话 | 分析逻辑、业务流程决策 |


- 职责详解
    # providers/              # 外部数据接入层
    
    # networking.py
    
    requests.Session
    
    - 复用 TCP 连接，不用每次请求都重新建连接
    - 统一保存配置，比如 headers、cookies、认证信息
    - 适合连续请求同一个或多个外部 API
    
    # ibkr_client.py
    
    - 读取 IBKR_FLEX_TOKEN 和 IBKR_FLEX_QUERY_ID
    - 向 IBKR Flex Web Service 发起报表请求
    - 轮询报表是否生成完成
    - 拿回原始 XML
    - 判断这份报表是不是最新日期
    - 在失败时做兜底处理
    
    后续会在portfolio_context.py进行下一步处理
    
    # ai_client.py

---

## 数据流

### 每日 Pipeline（5 阶段）

```
阶段 1  IBKR Flex Query API
          → ibkr_client.py（原始 XML 拉取，日期新鲜度轮询）

阶段 2  position_analysis.py
          → 持仓归一化（多货币换算、仓位权重、空头符号）
          → 研究计划（focus_symbols / focus_themes / risk_flags / news_questions）

阶段 3  ┌── ai_client.py → Perplexity sonar-pro（主新闻 + 宏观 + 组合资讯）    ┐ 并行
        └── ai_client.py → Grok grok-3（X 平台情绪）                           ┘
          → market_context.py（组装 MarketContext dataclass）

阶段 4  portfolio_market_analysis.py → ai_client.py（最终 AI 简报）

阶段 5  presenter.py → brief_builder.py（Telegram 消息）
                     → html_report.py（HTML 报告）
                     → delivery.py → notify.py → Telegram Bot
```

### LLM 调用链（自动三级降级）

```
1. Perplexity Responses API（anthropic/claude-sonnet-4-6）  优先，有 web 搜索能力
2. Anthropic API（claude-sonnet-4-6）                       次选，直连 Claude
3. Perplexity Chat API（sonar-pro）                         兜底，最终保障
```

只要 `PERPLEXITY_API_KEY` 或 `ANTHROPIC_API_KEY` 任意一个有效，分析就能完成。

---

## 简报结构

每次完整运行会发送一份移动端优先的 **HTML 报告**（通过 Telegram 文档发送）。

### Telegram 消息结构

```
📊 每日投资简报 | YYYY-MM-DD

一句话先看：
- 账户今天 ...，当前仓位感觉：现金 X%，影响最大的是 ...

⚡ 今日要点
- 账户盈亏 / 总资产 / 当日回报率
- 现金占比描述
- 止损 / 集中度告警（如有触发）

🌍 市场情报
主线新闻     (Perplexity, 3-5 条)
宏观看板     (Perplexity, 3-5 条，格式：指标 | 最新值 | 变化 | 含义)
组合相关资讯 (Perplexity, 3-6 条，格式：代码/主题 | 事实 | 为何影响持仓)
市场情绪     (Grok X, 4-5 条，格式：主题 | 情绪方向 | 为何影响持仓)

💼 账户快照
总资产 / 现金 / 当日盈亏
当前持仓（前 5，按绝对仓位排序）

🤖 AI 判断
市场判断     (2-3 条，只写与组合最相关的大环境)
相关资讯     (3-5 条，只写影响持仓的新闻)
组合解读     (3-5 条，优先点评前几大仓位)
风险提醒     (2-4 条，只写有阈值意义的风险)
今日动作     (2-4 条，建议而非命令)
```

### HTML 报告结构

- **Hero 区**：账户总值、现金占比、当日盈亏、最大持仓
- **风险芯片**：集中度预警、止损线触发（阈值：单仓 ≥30% 或浮亏 ≤-15%）
- **持仓列表**：前 8 只，含盈亏 / 仓位权重 / 市值
- **市场情报**：主新闻 / 宏观 / 组合资讯 / X 情绪
- **AI 分析**：5 个 section 全文

---

## 快速开始

```bash
# 1. 创建虚拟环境
python3.11 -m venv .venv && source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入所有 API Key

# 4. 用模拟持仓测试完整流程（不调用 IBKR）
python main.py --test

# 5. 只看当天市场快讯
python main.py --news-only

# 6. 完整生成并发送到 Telegram
python main.py --send
```

生成的 HTML 报告保存在 `reports/daily-brief-YYYY-MM-DD.html`。

---

## CLI 使用说明

```
python main.py [选项]
```

| 选项 | 说明 |
|------|------|
| `--test` | 使用模拟持仓，跳过 IBKR 实际拉取，仍调用真实新闻和分析 API |
| `--news-only` | 只生成市场快讯（Perplexity + Grok），不做持仓分析 |
| `--ibkr-only` | 只拉取 IBKR 持仓并输出快照，不调用任何 AI |
| `--ibkr-payload` | 拉取 IBKR 并输出结构化 JSON 分析 payload（供调试用）|
| `--send` | 将生成结果发送到 Telegram（与其他选项组合使用）|

**常用组合：**

```bash
# 每日正式运行（GitHub Actions 使用此命令）
python main.py --send

# 调试新闻模块（不需要 IBKR）
python main.py --news-only

# 调试 IBKR 解析
python main.py --ibkr-payload

# 不发 Telegram 的完整本地测试（使用模拟持仓）
python main.py --test

# 本地测试并发送到 Telegram
python main.py --test --send
```

---

## API 与配置

在 `.env` 中配置以下变量：

```bash
# Perplexity — 新闻、宏观、持仓相关资讯 + LLM 分析（必填）
PERPLEXITY_API_KEY=

# xAI Grok — X 平台市场情绪（必填）
GROK_API_KEY=

# Anthropic Claude — 最终分析备选（选填）
# 不填时自动使用 Perplexity 的 Claude 端点，功能相同但走 Perplexity 计费
ANTHROPIC_API_KEY=

# IBKR Flex Query
IBKR_FLEX_TOKEN=
IBKR_FLEX_QUERY_ID=

# IBKR 轮询行为（GitHub Actions 推荐配置）
IBKR_WAIT_FOR_FRESH_REPORT=true    # 是否等待当日新报表
IBKR_MAX_WAIT_MINUTES=120          # 最长等待分钟数（0 = 不等待）
IBKR_POLL_INTERVAL_SECONDS=300     # 轮询间隔（秒，最小 30）

# Telegram Bot
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

**最小配置：** `PERPLEXITY_API_KEY` + `GROK_API_KEY` + Telegram 三个变量即可运行 `--news-only`。完整流程还需要 IBKR 凭证。

---

## IBKR Flex Query 配置

1. 登录 IBKR Client Portal。
2. 打开 `Performance & Reports` → `Flex Queries`。
3. 创建一个 **Activity Flex Query**，至少勾选以下字段：
   - `Open Positions`（持仓）
   - `Cash Report`（现金）
   - `Equity Summary in Base`（账户总值）
   - `MTM Performance Summary in Base`（当日盈亏）
   - `Trades`（当日交易，可选）
   - `Cash Transactions`（股息/税/利息，可选）
   - `Option EAE`（期权到期/行权事件，可选）
   - `FX Rates`（多币种汇率，多货币账户必须启用）
4. 在 **Flex Web Service** 页面生成 Token。
5. 将 Token 和 Query ID 填入 `.env`。

**多账户支持：** 系统自动检测多个 `FlexStatement` 节点并合并为统一视图。多账户用户无需额外配置。

**日期判断逻辑：** 系统以美国东部时间 20:30 为基准判断"当日报表"；当日 20:30 前触发时，期望的是前一个交易日的报表。

---

## GitHub Actions 自动化

工作流定义在 [.github/workflows/daily_brief.yml](.github/workflows/daily_brief.yml)。

**触发时间：** 周二到周六 UTC `03:45`（对应美国交易日收盘后 IBKR 报表最早可用窗口）

| 时区 | 时间 |
|------|------|
| UTC | 03:45 |
| 美国东部（ET）| 前一天 23:45 |
| 新西兰夏令时（NZDT, UTC+13）| 16:45 |
| 新西兰冬令时（NZST, UTC+12）| 15:45 |

**轮询机制：** 启动后每 5 分钟（300 秒）检查 IBKR 报表日期，最长等待 120 分钟。超时后以最新可用报表继续运行，不中断流程。Job 最长超时 150 分钟。

**配置 Secrets：** 在仓库 `Settings` → `Secrets and variables` → `Actions` 中添加：

```
PERPLEXITY_API_KEY
GROK_API_KEY
ANTHROPIC_API_KEY         （选填）
IBKR_FLEX_TOKEN
IBKR_FLEX_QUERY_ID
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

手动触发：Actions 页面 → `IBKR Daily Brief` → `Run workflow`。

---

## 部署 Checklist

首次上线前按以下顺序验证：

- [ ] 本地执行 `python main.py --news-only`，确认 Perplexity 和 Grok 正常返回
- [ ] 本地执行 `python main.py --ibkr-payload`，确认 IBKR Flex Query 能返回正确数据
- [ ] 本地执行 `python main.py --test --send`，确认 Telegram 能收到 HTML 报告
- [ ] 本地执行 `python main.py --send`，确认完整流程端到端正常
- [ ] 将 `.env` 中所有 Key 同步到 GitHub Secrets
- [ ] 在 Actions 页面手动触发一次，检查日志
- [ ] 等待定时触发，确认自动运行正常

---

## 运维建议

**新闻数据**
- 出现"宏观数据暂时不可用"通常是当天信源不足，是正常降级，不是程序故障。
- 需要调整新闻质量时，修改 `src/core/providers/ai_client.py` 中的市场情报 prompt。

**IBKR 数据**
- 账户总资产异常时，优先检查 Flex Query 是否包含了所有必要字段（见上文配置说明）。
- 多货币账户必须在 Flex Query 中启用 `FX Rates`，否则基币换算会有偏差。

**Telegram 投递**
- 消息未收到时，先在 GitHub Actions 日志里确认 `Run daily brief` 步骤是否成功。
- 运行失败时，系统会自动向同一 Telegram 频道发送失败告警（含错误信息和耗时）。

**AI 分析质量**
- 分析结论不符合预期时，优先调整 `src/core/analysis/portfolio_market_analysis.py` 中的 system prompt，而不是修改消息模板。
- 分析模型遵循"只用系统提供的数字，不补造"原则。如输出出现无法解释的数字，可在 prompt 中加硬性约束。

**单元测试**

```bash
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖范围：
- 多货币持仓权重计算（USD→HKD 换算验证）
- 空头方向处理（净敞口符号、盈亏方向）
- 研究计划生成逻辑（风险资产优先级、主题识别）
- 市场新闻过滤（空占位条目剔除）

---

## 待开发功能

以下功能已创建文件和注释占位，尚未实现任何逻辑：

### Agent 模式

目标是支持多轮对话和交互分析，复用 `core` 层的所有能力。

- **`agent/orchestrator.py`** — 意图理解、工具路由、多轮规划
- **`agent/reviewer.py`** — 生成结果的事实核查、风险核查、置信度打分
- **`agent/memory.py`** — 对话历史和用户偏好的读写
- **`agent/tools/registry.py`** — 内部工具注册表，供编排器调用

### 存储层

- **`storage/report_store.py`** — 历史报告和分析 artifact 的持久化与检索
- **`storage/memory_store.py`** — 用户偏好和会话状态的持久化

### 类型化 Schema

- **`core/schemas/portfolio.py`** — 持仓级 dataclass 契约（取代当前的 `dict[str, Any]`）
- **`core/schemas/market.py`** — 市场事件类型契约
- **`core/schemas/decision.py`** — 决策输出类型契约

### 扩展分析能力

- **`core/analysis/risk_engine.py`** — 基于规则的确定性风险评分（不依赖 AI）
- **`core/analysis/market_analysis.py`** — 独立的市场解读引擎（不依赖持仓）
- **`core/analysis/decision_context.py`** — 组合 + 市场 + 历史记忆的合并上下文构建器
