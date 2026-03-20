# IBKR Daily Brief

一个基于 Python 3.11 的每日投资简报系统。它会在每个交易日自动拉取市场新闻、宏观数据和 IBKR 持仓信息，生成个性化分析，并通过 Telegram 推送到手机。

## 业务流程

系统每天按下面的顺序运行：

1. `Perplexity` 抓取主新闻和宏观数据。
2. `Grok` 抓取 X 平台市场情绪。
3. `IBKR Flex Query` 拉取上一交易日的持仓、现金、总资产和盈亏。
4. 分析模型综合市场和持仓，输出投资简报。
5. Telegram 收到一份 `HTML` 详尽报告，便于在手机或电脑上查看完整内容。

## 简报结构

正式版简报固定分成三个区块：

1. `🌍 市场情报`
   - 主新闻
   - 宏观看板
   - X 情绪
2. `💼 账户快照`
   - 总资产
   - 现金与现金占比
   - 当日盈亏
   - 当前持仓明细
3. `🤖 AI 判断`
   - 市场判断
   - 组合解读
   - 风险提醒
   - 今日动作

正式发送时 Telegram 会直接收到一份 `HTML` 详尽报告文件，里面会把新闻、持仓、摘要和 AI 分析做成更易读的版式。

## 项目结构

```text
ibkr-daily-brief/
├── .github/
│   └── workflows/
│       └── daily_brief.yml
├── src/
│   ├── grok_news.py
│   ├── perplexity_macro.py
│   ├── claude_analysis.py
│   ├── ibkr_data.py
│   └── notify.py
├── main.py
├── requirements.txt
├── .env.example
├── reports/
└── README.md
```

## 快速开始

1. 创建并激活 Python 3.11 虚拟环境。
2. 安装依赖：`pip install -r requirements.txt`
3. 复制 `.env.example` 为 `.env`，填入所有 API Key。
4. 本地测试：`python main.py --test`
5. 只看新闻快讯：`python main.py --news-only`
6. 正式生成并发送：`python main.py --send`
7. 每次完整生成后，会在本地 `reports/` 目录保存一份同日的 `HTML` 报告。

## 推荐运行方式

你可以把系统理解成两个模式：

1. `市场快讯模式`
   命令：`python main.py --news-only --send`
   用途：只看市场新闻、宏观和 X 情绪，不做持仓分析。

2. `完整投顾模式`
   命令：`python main.py --send`
   用途：抓市场、抓 IBKR 报表、生成投资分析，并发到 Telegram。

日常正式使用建议只跑第二种。

## API 与配置

### xAI Grok API

1. 在 xAI 平台创建 API Key。
2. 将 Key 写入 `GROK_API_KEY`。

### Perplexity API

1. 在 Perplexity 控制台创建 API Key。
2. 将 Key 写入 `PERPLEXITY_API_KEY`。

### Anthropic Claude API

1. 在 Anthropic 控制台创建 API Key。
2. 将 Key 写入 `ANTHROPIC_API_KEY`。
3. 如果没有该 Key，系统会自动回退到 `Perplexity` 做最终分析。

### IBKR Flex Query

1. 登录 IBKR Client Portal。
2. 打开 `Performance & Reports` -> `Flex Queries`。
3. 创建一个 Activity Flex Query，至少包含 `Open Positions`、`Cash Report`、`Equity Summary` 等字段。
4. 生成并保存 Query。
5. 在 Flex Web Service 页面拿到 Token。
6. 将 `Token` 与 `Query ID` 分别写入 `IBKR_FLEX_TOKEN` 与 `IBKR_FLEX_QUERY_ID`。
7. 如果你的 Query 返回多个 `FlexStatement`，系统会自动做汇总，更适合多账户用户。

## Telegram Bot

1. 通过 `@BotFather` 创建 Bot。
2. 获取 Bot Token，写入 `TELEGRAM_BOT_TOKEN`。
3. 获取目标聊天的 `chat_id`，写入 `TELEGRAM_CHAT_ID`。

## GitHub Actions

1. 将仓库推送到 GitHub。
2. 在仓库 `Settings` -> `Secrets and variables` -> `Actions` 中配置以下 Secrets：
   - `GROK_API_KEY`
   - `PERPLEXITY_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `IBKR_FLEX_TOKEN`
   - `IBKR_FLEX_QUERY_ID`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 工作流定义在 `.github/workflows/daily_brief.yml`。
4. 它会在周二到周六 UTC `03:45` 启动，对应美国交易日收盘后下一份 `IBKR Activity Statement` 的最早可用窗口。
5. 工作流会开启 `IBKR` 新日报轮询：如果拿到的还是旧 statement，会每 `5` 分钟重试一次，最长等 `120` 分钟。
6. 以新西兰夏令时 `NZDT (UTC+13)` 计算，启动时间约为下午 `16:45`；冬令时 `NZST (UTC+12)` 约为 `15:45`。
7. 这意味着周五美股那份日报，会在周六新西兰时间尽快发送；这是“最快拿到新日报”的代价。
8. 这样做的目的不是固定在晚上 20:00 发送，而是尽量在 IBKR 新日报一出来后就尽快拿到并发送。
9. 如果你更在意固定晚间发送，而不是最快拿到日报，可以把 cron 调回更晚的时间，并改回周一到周五。
10. 失败通知邮件使用 GitHub Actions 对仓库通知订阅者的默认机制。

## 部署 Checklist

在第一次上线前，建议按下面顺序检查：

1. 本地先跑通一遍：
   - `python main.py --news-only --send`
   - `python main.py --send`
2. 确认 Telegram 已经能收到消息。
3. 确认 IBKR Flex Query 能稳定返回前一交易日数据。
4. 把本地 `.env` 中的值同步到 GitHub Secrets。
5. 到 GitHub `Actions` 页面手动执行一次 `Run workflow`。
6. 手动执行成功后，再等待定时任务。

## 运维建议

- 如果消息里出现“宏观数据暂无可靠最新数据”，通常是当天可用信源不足，不一定是程序故障。
- 如果账户总资产明显不对，优先检查 IBKR Flex Query 里是否保留了：
  - `Cash Report`
  - `Open Positions`
  - `Equity Summary in Base`
  - `MTM Performance Summary in Base`
- 如果同一个 Query 返回了多个账户或多个 statement，系统会自动做汇总。
- 如果 Telegram 没有收到消息，先在 GitHub Actions 日志里看 `Run daily brief` 这一步是否成功。
- 如果你未来新增更多持仓规则，优先修改分析 prompt，而不是先改消息模板。

## 运行说明

- 正常模式会调用真实 IBKR Flex Query API。
- `--test` 模式会跳过真实 IBKR，改用模拟持仓，方便联调整体流程。
- `--news-only` 模式只生成市场快讯，不做持仓分析。
- `--send` 会将最终结果发送到 Telegram。
- 完整模式会发送一份 `HTML` 详尽报告文件，不再额外发送 Telegram 文字摘要。
- 新闻与宏观数据会并行拉取，以减少总耗时。
- 如果主流程出现异常，系统会尝试通过 Telegram 发送失败告警。

## 输出示例

```text
📊 每日投资简报 | 2026-03-17

⚡ 今日要点
- 账户总资产 xxx,xxx，当日盈亏 xxx。
- 现金占比 10.6%，处于可用区间。

🌍 市场情报
- 主线新闻
- 宏观看板
- X 情绪

💼 账户快照
- 总资产
- 现金与现金占比
- 当前持仓

🤖 AI 判断
- 市场判断
- 组合解读
- 风险提醒
- 今日动作
```
