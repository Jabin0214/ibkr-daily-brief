# AI Portfolio Copilot 重构架构规范

## 1. 文档目的

本文档是本项目后续重构、迁移、扩展和 AI 辅助开发的最高优先级架构说明。

后续任何 AI、开发者或自动化流程在修改代码前，都应优先遵守本文档定义的：

- 目录结构
- 模块边界
- 命名规则
- 职责归属
- 数据流方向
- 迁移顺序
- 禁止事项

如果旧代码与本规范冲突，以本规范为准，并逐步迁移旧代码。

---

## 2. 项目目标

本项目不是一个单纯的日报脚本，而是一个可持续演进的 `AI Portfolio Copilot`。

系统应同时支持两种模式：

1. `Pipeline Mode`
   每日自动拉取报表、生成市场情报、完成分析、输出日报

2. `Agent Mode`
   用户可以围绕持仓、市场、历史建议、历史报表进行多轮问答和交互分析

因此，本项目必须同时具备：

- 稳定的日常跑批流程
- 可复用的分析能力模块
- 可被 Agent 调用的内部工具能力
- 清晰的输入输出边界
- 可存储、可回放、可审计的历史数据

---

## 3. 核心架构原则

### 3.1 总体原则

- 采用 `modular monolith`，即模块化单体架构
- 当前阶段不拆微服务
- 所有业务能力先做模块边界，再考虑部署边界
- Pipeline 和 Agent 共用底层核心能力

### 3.2 设计原则

- `Single Responsibility`
  每个模块只负责一类职责
- `Stable Boundaries`
  模块之间通过稳定接口和数据契约通信
- `Pipeline First, Agent Ready`
  先保证日报主流程稳定，再让 Agent 复用这些能力
- `Rule First, LLM Second`
  规则和结构化分析优先，LLM 主要负责解释、补充和整合
- `Storage Early`
  尽早归档关键输入、中间结果和输出，方便后续 Agent 和记忆系统使用
- `Thin Entrypoints`
  入口层尽量轻，不承载复杂逻辑

### 3.3 明确禁止

禁止继续新增“把所有逻辑塞进一个文件”的代码。

禁止新功能直接：

- 写进 `main.py`
- 直接依赖原始 XML 做跨模块分析
- 在 interface 层做业务判断
- 在 provider 层做高层业务决策
- 在 agent 层重复实现 core 里的业务逻辑

---

## 4. 目标目录结构

后续目标结构如下：

```text
src/
  core/
    analysis/
    providers/
    schemas/
  agent/
    tools/
    prompts/
  interface/
    telegram/
    api/
  pipeline/
    daily_report.py
  storage/
```

如后续需要扩展，可以在不破坏主结构的前提下新增：

```text
src/
  core/
    utils/
  agent/
    memory/
  interface/
    chat/
```

---

## 5. 各目录职责定义

## 5.1 `src/core/`

`core` 是整个项目最重要的业务核心层。

它的职责是：

- 连接外部数据源
- 清洗并规范化输入
- 执行核心分析逻辑
- 定义统一数据契约

`core` 不直接面向用户，也不直接承担 Agent 编排职责。

### 5.1.1 `src/core/providers/`

职责：

- 与外部系统交互
- 拉取原始数据
- 处理认证、请求、轮询、重试、降级

允许的内容：

- IBKR 请求
- 新闻 API 请求
- 市场情绪接口调用
- LLM API 调用
- 价格/宏观数据抓取

不允许的内容：

- 复杂业务判断
- 报告文案生成
- 风险结论生成
- 高层推荐逻辑

典型文件：

- `ibkr_client.py`
- `news_client.py`
- `market_data_client.py`
- `llm_client.py`

### 5.1.2 `src/core/analysis/`

职责：

- 承载全部核心分析逻辑
- 消费结构化输入
- 输出结构化结论或信号

允许的内容：

- 持仓分析
- 市场分析
- 风险识别
- 持仓与市场联合分析
- 建议候选项生成

不允许的内容：

- 直接发 Telegram
- 直接生成 HTML
- 直接处理原始 API 响应格式
- 直接承担 Agent 调度

典型文件：

- `portfolio_context.py`
- `market_context.py`
- `position_analysis.py`
- `portfolio_market_analysis.py`
- `risk_engine.py`

说明：
这里的 `context` 虽然语义上是“上下文构建”，但本质上仍是核心分析输入准备的一部分，因此统一放入 `core/analysis/` 是合理的。

### 5.1.3 `src/core/schemas/`

职责：

- 定义模块之间共享的数据结构
- 定义输入输出边界
- 保证跨模块契约稳定

允许的内容：

- Portfolio schema
- Market schema
- Decision schema
- Tool input/output schema

不允许的内容：

- 业务逻辑
- API 请求
- 报告生成

推荐文件：

- `portfolio.py`
- `market.py`
- `decision.py`
- `tool_contracts.py`

---

## 5.2 `src/agent/`

`agent` 层负责让项目从“自动化 pipeline”升级成“可交互 AI 系统”。

它的职责是：

- 理解用户问题或任务
- 调用底层能力
- 规划步骤
- 复用历史记忆
- 输出最终回答

### 5.2.1 `src/agent/tools/`

职责：

- 将 `core` 层能力封装成 Agent 可调用的工具

工具的典型形式：

- `fetch_latest_portfolio_context`
- `fetch_latest_market_context`
- `run_position_analysis`
- `run_portfolio_market_analysis`
- `load_recent_reports`

工具层的要求：

- 输入清晰
- 输出结构化
- 无 UI 耦合
- 无多余副作用

### 5.2.2 `src/agent/prompts/`

职责：

- 存放 Agent 与分析模型使用的提示词模板
- 将提示词版本化

要求：

- 提示词不要散落在多个业务文件中
- 每个提示词要有明确用途和命名
- 高价值提示词后续要支持版本管理

示例：

- `portfolio_summary.md`
- `market_interpretation.md`
- `decision_review.md`
- `copilot_chat.md`

### 5.2.3 `src/agent/` 根目录下的未来核心模块

后续建议新增：

- `orchestrator.py`
  负责整体调度和任务规划
- `reviewer.py`
  负责审查建议、附加置信度
- `memory.py`
  负责历史偏好、历史结论和会话记忆

---

## 5.3 `src/interface/`

`interface` 层是系统所有输入输出通道。

它负责：

- 接收外部请求
- 调用 pipeline 或 agent
- 把结果转成适合渠道的格式

它不负责核心业务逻辑。

### 5.3.1 `src/interface/telegram/`

职责：

- Telegram 推送
- 告警消息发送
- 每日摘要推送

### 5.3.2 `src/interface/api/`

职责：

- 提供 HTTP API
- 提供对外或本地接口
- 为未来 dashboard/chat 前端提供服务

未来可扩展：

- `src/interface/chat/`
  负责 chat-style 交互界面适配

禁止：

- 在 interface 层写复杂分析逻辑
- 在 interface 层直接访问原始 IBKR XML

---

## 5.4 `src/pipeline/`

`pipeline` 层是自动化日报流程入口层。

职责：

- 按固定顺序执行每日流程
- 调用 `core` 层能力
- 将最终结果交给 `interface` 层发送

当前目标文件：

- `daily_report.py`

后续可扩展：

- `daily_news_only.py`
- `backfill_reports.py`
- `rebuild_history.py`

`pipeline` 的特点是：

- 面向自动定时任务
- 面向固定业务流
- 不承担 Agent 动态调度

---

## 5.5 `src/storage/`

`storage` 层负责系统持久化。

职责：

- 保存日报 payload
- 保存分析结果
- 保存历史报告
- 保存用户记忆
- 保存会话记录

推荐后续拆分：

- `report_store.py`
- `memory_store.py`
- `artifact_store.py`

禁止：

- 在 storage 层写分析逻辑
- 在 storage 层直接决定业务流程

---

## 6. 数据流规范

系统中允许的数据主流向如下：

### 6.1 每日自动报表流程

```text
pipeline/daily_report.py
  -> core/providers
  -> core/analysis
  -> storage
  -> interface/telegram or interface/api
```

### 6.2 Agent 问答流程

```text
agent/orchestrator
  -> agent/tools
  -> core/analysis
  -> storage
  -> interface/api or interface/chat
```

### 6.3 数据依赖规则

允许：

- `pipeline -> core`
- `pipeline -> interface`
- `agent -> core`
- `agent -> storage`
- `interface -> pipeline`
- `interface -> agent`

不建议：

- `core -> interface`
- `core -> pipeline`
- `storage -> interface`
- `providers -> agent`

禁止：

- 高层模块反向依赖低层实现细节
- interface 直接绕过 core 写业务逻辑

---

## 7. 业务能力拆分规范

后续能力应按下面方式拆分。

## 7.1 报表链路

### `IBKR 拉取`

位置：
- `core/providers/ibkr_client.py`

职责：
- 发起 Flex Query
- 轮询 statement
- 返回原始 XML 或原始 broker payload

### `Portfolio Context`

位置：
- `core/analysis/portfolio_context.py`

职责：
- 将原始 broker 数据转成标准化组合上下文
- 生成账户级、持仓级、活动级、现金级结构

输出应至少包括：

- 账户概览
- 持仓列表
- 现金概览
- 交易事件
- 期权事件
- 风险基础信号

## 7.2 新闻链路

### `新闻源拉取`

位置：
- `core/providers/news_client.py`

职责：
- 调 Perplexity
- 调 Grok
- 后续可扩其他数据源

### `Market Context`

位置：
- `core/analysis/market_context.py`

职责：
- 统一输出市场主线、宏观、组合相关资讯、市场情绪
- 清洗低质量文本
- 为后续联合分析准备结构化输入

## 7.3 分析链路

### `Position Analysis`

位置：
- `core/analysis/position_analysis.py`

职责：
- 只分析账户与持仓自身
- 不依赖外部新闻

应输出：

- 集中度
- 回撤
- 现金压力
- 期权到期风险
- 单仓异常

### `Portfolio Market Analysis`

位置：
- `core/analysis/portfolio_market_analysis.py`

职责：
- 将持仓和市场结合
- 解释“今天市场发生的事如何影响组合”

应输出：

- 市场影响映射
- 持仓相关新闻解释
- 风险提醒
- 行动建议

---

## 8. Pipeline 与 Agent 的边界

这是后续开发中最重要的概念之一。

### 8.1 Pipeline 的定位

Pipeline 是固定顺序的自动化业务流。

适合：

- 每日自动报表
- 每日市场推送
- 定时任务
- 回填任务

不适合：

- 动态问答
- 多轮交互
- 根据用户问题灵活规划

### 8.2 Agent 的定位

Agent 是动态任务调度层。

适合：

- 回答用户问题
- 选择要调用的工具
- 组织多轮分析步骤
- 读取历史结果和记忆

不适合：

- 直接替代底层核心分析模块

### 8.3 判断标准

如果一个流程是“每天固定跑一次”，它属于 `pipeline`。  
如果一个流程是“根据用户问题决定调用哪些能力”，它属于 `agent`。

---

## 9. 旧代码迁移要求

旧代码允许短期存在，但必须按以下方向逐步清空。

### 9.1 旧文件迁移目标

- `src/ibkr_data.py`
  迁到 `src/core/providers/ibkr_client.py`
- `src/ibkr_middleware.py`
  迁到 `src/core/analysis/portfolio_context.py`
- `src/perplexity_macro.py`
  迁到 `src/core/providers/news_client.py`
- `src/grok_news.py`
  迁到 `src/core/providers/news_client.py`
- `src/claude_analysis.py`
  拆到：
  - `src/core/providers/llm_client.py`
  - `src/core/analysis/position_analysis.py`
  - `src/core/analysis/portfolio_market_analysis.py`
- `src/reporting.py`
  迁到 `src/interface/telegram/` 或 `src/interface/api/` 相关输出模块
- `src/notify.py`
  迁到 `src/interface/telegram/`
- `main.py`
  最终弱化或替换为更薄的 bootstrap 入口

### 9.2 迁移策略

迁移必须按以下顺序：

1. 新目录建立
2. 新文件承载真实实现
3. 旧文件变兼容层
4. 调用方改为新路径
5. 测试通过
6. 删除旧兼容层

禁止长期让新旧两套实现并行维护。

---

## 10. 命名规范

### 10.1 文件命名

- 使用小写加下划线
- 文件名应体现职责，不体现临时步骤

推荐：

- `portfolio_context.py`
- `market_context.py`
- `position_analysis.py`
- `portfolio_market_analysis.py`
- `ibkr_client.py`
- `news_client.py`

避免：

- `utils2.py`
- `helper_new.py`
- `step123.py`
- `final_analysis_v2.py`

### 10.2 函数命名

规则：

- provider 层用 `fetch_`, `get_`, `request_`
- analysis 层用 `build_`, `analyze_`, `score_`, `classify_`
- agent 层用 `run_`, `plan_`, `review_`, `route_`
- storage 层用 `save_`, `load_`, `list_`, `archive_`

---

## 11. AI 迭代执行规范

后续让 AI 持续修改代码时，应遵守以下规则：

### 11.1 修改前先判断归属

每次新增功能前，先判断它属于：

- provider
- analysis
- schema
- tool
- interface
- pipeline
- storage

未经归类，不允许直接写代码。

### 11.2 优先复用已有结构

新增逻辑前应先检查：

- 是否已有对应 provider
- 是否已有可复用 schema
- 是否已有相近 analysis 模块
- 是否应该包装成 agent tool

### 11.3 保持边界清晰

AI 不应：

- 把业务逻辑直接写回 bootstrap 文件
- 把 provider 和 analysis 混写
- 在 interface 中拼业务决策
- 在 pipeline 中嵌入复杂解析细节

### 11.4 修改顺序

推荐顺序：

1. 先定义 schema
2. 再实现 provider / analysis
3. 再连接 pipeline 或 agent
4. 最后接 interface 和 storage

---

## 12. 当前推荐的近期实施顺序

后续实际重构建议按下面顺序执行：

1. 固化新的目录结构
2. 完成 `core/providers/ibkr_client.py`
3. 完成 `core/analysis/portfolio_context.py`
4. 完成 `core/providers/news_client.py`
5. 完成 `core/analysis/market_context.py`
6. 拆分 `position_analysis.py`
7. 拆分 `portfolio_market_analysis.py`
8. 重建 `pipeline/daily_report.py`
9. 接入 `interface/telegram/`
10. 再开始建设 `agent/tools/` 与 `agent/orchestrator`

---

## 13. 最终形态定义

本项目的最终形态应满足：

- 可以每日自动生成组合日报
- 可以独立生成市场日报
- 可以结合持仓和新闻生成建议
- 可以存档历史输入和输出
- 可以通过 Agent 对历史和当日数据进行多轮问答
- 所有核心能力都可复用，而不是只服务单一脚本

如果未来某个改动不能增强上述目标，或者破坏了模块边界，应优先回退或重构，而不是继续堆叠。
