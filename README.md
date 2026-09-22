# ai-ticker-copilot

美股 AI 股票分析辅助系统：**四维评分 + 历史事件类比 + 准实时事件跟进**，辅助判断 AI 产业链美股的**建仓/加仓时机**。

> 个人使用、本地运行、单用户；仅美股（USD 计价）。
> **辅助参考**：不自动下单、不接入券商、不构成投资建议。

## 功能特性

**分析决策**

- **四维评分**：宏观 / 事件 / 产业 / 公司四个维度规则打分（0-100，可解释、可复现），LLM 只做综合研判——分数是锚点，AI 挂了系统照样出分
- **历史事件类比**（核心特色）：当前事件与历史事件库（贸易摩擦、加息周期、芯片管制、DeepSeek 冲击等）做相似度匹配，用历史实测数据（最大回撤/达底天数/恢复天数）研判当前影响；事件库随使用自动沉淀增长
- **技术面分层指标体系**：体制层（指数 vs MA200 + VIX，只做门槛）→ 趋势层（MA50 斜率）→ 择时层（MA20 回踩 / RSI14 / ATR14 / 量比）；伤害度量以"52 周回撤 + 乖离率"为主
- **体制层硬约束**：指数环境破位时所有个股信号强制压至"观望"——环境关门时不看多任何个股
- **破位×事件分级**：区分"体制转折"与"牛市内深回调"（2026-07 实证），财报/FOMC 前 N 天技术买点自动降级为"等事件落地"

**数据能力**

- **准实时事件管道**：新闻 RSS + Google News 主题流默认 20 分钟轮询（可配），48h 年龄过滤 → 增量去重 → 预过滤 → LLM 结构化为四类事件（宏观政策/国际热点/行业/企业），入库前自动富化关联个股**价格反应**（事件日涨跌/前 5·20 日趋势/距 52 周回撤/量比）
- **多源免费数据**：yfinance（行情/财报/指数）+ FRED（宏观七系列）+ RSS + X 采集双通道（`X_MODE` 三选一：**api**=twitterapi.io 接口，免登录态、帖+回复+引用一次拿全，约 $1/月 ｜ **crawl**=Playwright 爬虫，免 API 费用需登录态 ｜ **off**=关闭）
- **经济日历**：FOMC / 宏观发布惯例 / 财报日预置，"预告 → 实时跟进 → 历史类比"闭环
- **对话式研究助理**：基于系统数据（四维分/指标/事件含价格反应/持仓）的多轮对话，可追问报告理由、质疑结论、做情景推演（"如果跌破 MA50？"）；助理只引用系统已采集的数据，缺失直说不编造
- **回调波段挖掘器**：从指数/个股日线自动检出 ≥5% 回调波段，产出事件草稿骨架（事件库的自动化增长引擎，种子库 31 条即含其产物）
- **全链路可回放**：每次分析的输入、输出、快照全部落 MySQL，历史信号可回溯

**工程特性**

- **LLM 供应商无关**：任意 OpenAI 兼容大模型（GPT / Qwen / GLM / Kimi / DeepSeek），`.env` 三项配置切换，代码零改动
- **降级优先于失败**：任一数据源失效计中性分并标注，主流程不中断
- **MOCK_MODE**：全链路假数据，无网无 key 验证系统
- 本地 Web 面板（FastAPI + Vue3 + ECharts，vendor 本地化断网可用）

## 工作原理

```
[1] 采集（两条独立管道）
    事件管道（默认 20min 轮询）：多源抓取 → 去重 → 预过滤 → LLM 结构化 → 价格反应富化 → 入库+提醒
    数据管道（低频）：yfinance 行情/财报 + FRED 宏观 + X 帖子（X_MODE 双通道，每博主每天 1 次）
[2] 事件匹配：当前事件 → 硬检索历史库 top-5 → LLM 精排(相似度/方向/强度) → 每事件 top-3 类比
[3] 四维评分：宏观 / 事件(类比+情绪) / 产业(篮子强弱) / 公司(基本面+技术面)
[4] 体制门槛：指数破位 → 信号上限压至观望（环境只做开关，不进加权）
[5] LLM 研判：四维分 + 原始指标 + 类比结论 → 结构化信号（偏离分档必须说明理由）
[6] 落库展示：快照 UPSERT → Web 面板（信号/理由/风险/免责声明）
[7] 对话追问：报告出来后在"对话"页签多轮追问（上下文=系统真实数据）
```

## 快速开始

### 前置要求

- [uv](https://docs.astral.sh/uv/)（会自动安装 Python 3.13.9）
- MySQL 8（二选一）：本机已有实例（`.env` 填连接信息即可，建库建表自动完成），或 Docker：`docker compose up -d mysql`

### 安装与运行

```bash
# 1. 安装依赖（首次自动装 Python 3.13.9）
uv sync

# 2. 配置
cp .env.example .env      # 填 LLM_* 与 FRED_API_KEY；DB_* 按你的 MySQL 填
# X 采集二选一（可跳过，X_MODE=off）：
#   api（推荐）：twitterapi.io 控制台获取 key 填 X_API_KEY，无需登录态
#   crawl：uv run playwright install chromium（约 150MB）+ scripts/export_x_cookie.py 导出登录态

# 3. 无 key 先跑通（MOCK 模式）
MOCK_MODE=true uv run python scripts/refresh_data.py --scope market

# 4. 起服务
uv run python main.py     # → http://127.0.0.1:8000
```

### 填股票池

编辑 `config_files/stocks.yaml`（首次运行自动从 `.example` 复制）：

```yaml
stocks:
  - symbol: NVDA        # ticker（大写，支持 BRK.B 格式）
    segment: gpu        # 产业链环节：gpu/foundry/equipment/cloud/software/power/etf/other
    position: holding   # holding(持仓) / watchlist(关注)
    cost_basis: 120.5   # 持仓成本（可选，仅展示盈亏）
```

## CLI 工具

| 命令 | 说明 |
|---|---|
| `uv run python scripts/refresh_data.py --scope market\|macro\|news\|all` | 数据刷新与验证（行情指标表 / FRED / 事件管道单轮） |
| `uv run python scripts/build_events.py --list` | 查看历史事件库与回填进度 |
| `uv run python scripts/build_events.py --draft "主题" --category regulation --date 2026-10-17` | 生成新事件事实层草稿（人工核对后入库） |
| `uv run python scripts/backfill_events.py --event <event_id>` | 历史事件量化回填（实测回撤/达底/恢复；`--write` 回写 market 指标） |
| `uv run python scripts/mine_events.py --symbol ^IXIC --since 2024-01-01` | 回调波段挖掘（真实行情；`--csv data/x.csv` 离线模式） |
| `uv run python scripts/analyze.py --ticker NVDA` | 端到端分析（信号/理由/风险/免责声明） |
| `uv run python scripts/export_x_cookie.py` | 有头浏览器登录 X 导出登录态（仅 X_MODE=crawl 需要） |
| `uv run python scripts/crawl_x.py` | 手动抓 X（X_MODE 路由 api/crawl/off）并入库 |

## 配置说明

**`.env` 关键项**（完整见 `.env.example`）：

| 变量 | 说明 |
|---|---|
| `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL` | 任意 OpenAI 兼容大模型，换供应商只改这三项 |
| `FRED_API_KEY` | [FRED](https://fred.stlouisfed.org) 免费注册 |
| `X_MODE` | X 数据源三选一：`api`（twitterapi.io，推荐）/ `crawl`（Playwright 爬虫）/ `off`（关闭） |
| `X_API_KEY / X_API_BASE` | twitterapi.io 控制台获取（X_MODE=api 时必填） |
| `MOCK_MODE` | `true` = 全链路 mock（无网无 key 验证） |
| `DB_*` | MySQL 连接 |
| `SCHEDULER_ENABLED` / `EVENT_POLL_INTERVAL_MIN` | 调度开关（四类任务）/ 事件轮询间隔（默认 20 分钟） |
| `NEW_EVENT_NOTIFY` | 新事件 macOS 系统通知 |

**`config_files/`**：`stocks.yaml`（股票池）、`influencers.yaml`（X 博主）属个人隐私已 gitignore，仓库只提交 `.example` 模板；`scoring_weights.yaml`（四维权重，合计必须 = 1.0）随仓库提交。

## 项目结构

```
ai-ticker-copilot/
├── main.py                 # 入口：uvicorn.run(create_app())
├── config/                 # settings（.env 唯一读取点）+ loader（YAML 校验）
├── config_files/           # 用户 YAML（股票池/博主/权重）
├── domain/                 # pydantic 模型 + 技术指标纯函数库
├── collectors/             # 采集层：market/macro/news/x_source 路由 + x_api/x_crawler 双通道/mock + TTL 缓存
├── events_lib/             # 历史事件库：种子 YAML(31 条) + 两级匹配 + 联动回填 + 波段挖掘 + 价格反应 + 自动沉淀
├── scoring/                # 四维评分引擎（P5）
├── analyzer/               # LLM 出口 + run_analysis 编排 + 对话研究助理（P6）
├── prompts/                # 研判/精排/对话 prompt（P6）
├── storage/                # MySQL 连接池 + repository（唯一读写口）
├── web/                    # FastAPI（六路由组含 chat）+ 前端面板（P8）
├── scheduler.py            # APScheduler 四类任务（P9）
├── scripts/                # CLI 工具（每数据源可独立验证）
├── docs/                   # 模块化技术方案（52 篇）
└── tests/                  # pytest（14 文件 84 用例；DB 测试无实例时自动 skip）
```

## 实施进度

按 [docs/09-delivery/roadmap.md](docs/09-delivery/roadmap.md) 推进（总工作量约 9~11 个业余工作日）：

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 项目骨架（uv 工程/settings/健康检查） | ✅ 完成 |
| P1 | 数据模型 + 配置加载校验 | ✅ 完成 |
| P2 | 存储层（连接池/DDL/repository）+ 种子事件库 | ✅ 完成 |
| P3 | 采集层（指标库/缓存/行情/宏观/事件管道/mock） | ✅ 完成 |
| P4 | 事件库（两级匹配/回填算法/工具脚本） | ✅ 完成 |
| P5 | 评分引擎（四 scorer/engine/体制层硬约束） | ✅ 完成 |
| P6 | LLM 研判（供应商无关接入/prompts/pipeline） | ✅ 完成 |
| P7 | X 采集（登录态导出/防风控；**增补：api/crawl 双通道路由 + 回复与引用抓取**） | ✅ 完成 |
| P8 | Web 面板（六页签含对话/K线/vendor 本地化/409 锁） | ✅ 完成 |
| P9 | 调度器四任务/通知/日历/自动沉淀 | ✅ 完成 |
| 增补 | 波段挖掘器（种子 31 条）/ 价格反应富化 / X API 通道 / 对话助理 | ✅ 完成（2026-09） |

> 单元测试 14 个文件 84 条用例（DB 相关 6 条需配置 MySQL 凭据后自动启用）。
> 真实数据联调 checklist：① `.env` 填 `DB_*`（本机 3306 已有实例）；② 填 `LLM_*`
> 与 `FRED_API_KEY`；③ 雅虎限频恢复后 `scripts/refresh_data.py --scope market`；
> ④ X 采集二选一：`X_MODE=api` + `X_API_KEY`，或 crawl 模式先跑 `scripts/export_x_cookie.py` 登录一次。

## 文档

完整技术方案见 [docs/README.md](docs/README.md)（模块化文档，粒度对齐代码文件）：

- 总览与架构：[docs/01-overview/](docs/01-overview/README.md)
- 模块交互与接口契约：[docs/10-module-contracts.md](docs/10-module-contracts.md)
- 各模块文档：采集 [03](docs/03-collectors/README.md) ｜ 事件库 [04](docs/04-events/README.md) ｜ 评分 [05](docs/05-scoring/README.md) ｜ LLM [06](docs/06-analyzer/README.md) ｜ 存储 [07](docs/07-storage/README.md) ｜ Web [08](docs/08-web/README.md)
- 交付运维：[docs/09-delivery/](docs/09-delivery/README.md)（运行手册/实施路线/测试/风险/演进）

## 免责声明

本系统仅供个人研究参考，不构成投资建议。市场有风险，投资需谨慎；任何交易决策及其后果由使用者自行承担。
