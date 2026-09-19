# 02-数据模型 ｜ 用户配置文件（stocks.yaml / influencers.yaml）

> 模块：02 数据模型 ｜ 成分：用户 YAML 配置 ｜ 对应代码：config_files/、domain/stock.py ｜ 实施阶段：P1
> 来源：原方案 §5.1 / §5.2

## 5.1 股票池配置（config_files/stocks.yaml）

```yaml
# 股票池 —— 请填入你关注的 AI 产业链美股
#   symbol:    ticker 代码（大写，如 NVDA）
#   segment:   产业链环节：gpu/foundry/equipment/cloud/software/power/etf/other
#   position:  holding(持仓) / watchlist(关注未建仓)
#   cost_basis: 持仓成本 USD（可选，仅展示盈亏）
stocks: []
```

- 校验规则：symbol 匹配 `^[A-Z0-9.\-]{1,5}$`（支持 BRK.B 等）；非法条目**报错并列出明细**（个人数据，写错必须明说，不静默跳过）。
- **空池处理**：Web 面板与 CLI 均显示固定中文提示"股票池为空：请编辑 config_files/stocks.yaml 填入你的关注股票后刷新"，不报堆栈错误。
- stocks.yaml 属个人持仓隐私 → gitignore，仓库只提交 `.example` 模板，首次运行自动复制。

## 5.2 X 博主配置（config_files/influencers.yaml）

```yaml
influencers: []
#   - handle: elonmusk      # X 用户名（不带 @）
#     note: 半导体/AI       # 备注
#     tickers: [NVDA]       # 主要跟踪标的（可选，用于帖子→股票弱关联）
```

同样 gitignore + example 模板复制。单轮抓取上限 `MAX_X_BLOGGERS_PER_RUN`（默认 5）。
