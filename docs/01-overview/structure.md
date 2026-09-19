# 01-总览 ｜ 项目目录结构

> 模块：01 总览与架构 ｜ 成分：目录结构 ｜ 实施阶段：P0
> 来源：原方案 §4；仓库名 v1.2 后定为 ai-ticker-copilot

```
ai-ticker-copilot/
├── pyproject.toml              # uv 工程定义与依赖（见 09-delivery/runbook.md）
├── .python-version             # 3.13.9
├── .env.example                # 环境变量模板（中文注释）
├── docker-compose.yml          # 本地 MySQL 8 容器（本机无 MySQL 时一键拉起）
├── README.md                   # 上手步骤：准备 MySQL → 填 key → 填股票 → 起服务
├── docs/                       # 本套模块化方案文档（README 索引 + 10 契约 + 01~09 模块目录）
├── main.py                     # 入口：uvicorn.run(create_app())
├── config/
│   ├── settings.py             # 全局配置单例（.env → Settings）
│   └── loader.py               # 三个 YAML 的加载/校验/模板复制
├── config_files/               # 用户可编辑 YAML（*.example 随仓库提交）
│   ├── stocks.yaml.example     # 股票池模板（空）
│   ├── influencers.yaml.example# X 博主模板（空）
│   └── scoring_weights.yaml    # 四维权重（默认 0.25×4，随仓库提交）
├── domain/                     # pydantic 数据模型（无业务逻辑）
│   ├── stock.py                # StockConfig / MarketQuote
│   ├── events.py               # HistoricalEvent / CurrentEvent / EventMatchResult 等
│   ├── scoring.py              # ScoreBreakdown / FourDimScores
│   └── signal.py               # Action 枚举 / TickerSignal / AnalysisResult
├── collectors/                 # 数据采集层（每个源一个文件）
│   ├── base.py                 # DataSource 协议 + @ttl_cache（内存+磁盘两级）
│   ├── market.py               # yfinance：日线/MA/ATR14/量比/RSI/财报/PE 分位 + ^VIX + ^GSPC/^NDX/^SOX 指数体制层
│   ├── macro.py                # FRED：FEDFUNDS/DGS10/T10Y2Y/CPIAUCSL/UNRATE + 核心PCE(PCEPILFE)/HY利差(BAMLH0A0HYM2)
│   ├── news.py                 # RSS + WebSearch → LLM 批量抽取 CurrentEvent
│   ├── x_crawler.py            # Playwright 爬 X + 防风控
│   └── mock.py                 # MOCK_MODE 时读 tests/fixtures 静态数据
├── events_lib/
│   ├── seed_events.yaml        # 种子事件库（10 条，随仓库版本管理）
│   ├── loader.py               # yaml → 校验 → upsert MySQL events 表（source='seed'）
│   └── matcher.py              # 硬检索 top-K + LLM 精排 + 降级路径
├── scoring/
│   ├── macro_score.py          # 宏观规则打分（FRED 规则表）
│   ├── event_score.py          # 事件类比打分 + X 情绪分
│   ├── industry_score.py       # 产业相对强弱 + 财报动量 + AI 词频
│   ├── company_score.py        # 公司基本面（成长/估值/质量/技术面）
│   └── engine.py               # 加权汇总 + 信号分档
├── analyzer/
│   ├── llm.py                  # LLM 构造（OpenAI 兼容，供应商 .env 可配）+ with_structured_output(method="function_calling")
│   └── pipeline.py             # run_analysis() 编排（取数→匹配→评分→LLM→落库）
├── prompts/
│   ├── event_match.py          # 事件相似度精排 prompt（输出 similarity/direction/magnitude/notes）
│   └── analysis.py             # 综合研判 prompt（含偏离说明规则与免责声明）
├── storage/
│   ├── db.py                   # PyMySQL 连接池（DBUtils）、MySQL DDL（启动时幂等建表）
│   └── repository.py           # 快照 UPSERT / 事件 CRUD / 帖子去重 / 日志追加
├── web/
│   ├── app.py                  # create_app、lifespan、全局分析锁
│   ├── deps.py                 # 依赖注入（settings/repository）
│   ├── api/                    # dashboard.py stocks.py events.py analysis.py config_api.py
│   └── static/                 # index.html / app.js / api.js / components/ / vendor/
├── scripts/                    # CLI 工具（每个数据源可独立验证）
│   ├── refresh_data.py         # --scope market|macro|news|x|all
│   ├── analyze.py              # --ticker NVDA：不起 Web 直接端到端分析
│   ├── export_x_cookie.py      # 有头浏览器登录 X → 保存 storage_state.json
│   ├── build_events.py         # 事件事实层生成：主题→权威源检索→LLM 结构化→YAML 草稿（人工核对）
│   ├── backfill_events.py      # 历史事件量化回填：按事件日+标的实测回撤/达底/恢复天数
│   └── crawl_x.py              # 手动抓 X 并打印结果
├── scheduler.py                # APScheduler（默认开，SCHEDULER_ENABLED=true）：事件轮询(15~30min)+收盘分析+X 低频三类任务
├── data/                       # 运行时数据（gitignore）：cache/ / x_state/
└── tests/                      # conftest + fixtures + 各模块测试
```
