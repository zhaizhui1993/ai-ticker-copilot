# 03 ｜ 数据采集层（collectors/ + scheduler.py）

> **职责**：所有外部数据的入口——行情/财报/指数体制层数据、FRED 宏观、新闻事件准实时管道、X 爬虫；统一 DataSource 协议、TTL 两级缓存、重试退避与三类调度任务。
> **对应代码**：collectors/（base / market / macro / news / x_crawler / mock）、scheduler.py ｜ **依赖模块**：02（模型）、07（落库） ｜ **实施阶段**：P3（market/macro/news/缓存）、P7（X 爬虫）、P9（调度器）
> **内容来源**：原方案 §6.4（分层频率与事件管道）、§6.3（X 爬虫）及 §4 目录注释

## 成分文档

| 文档 | 对应代码 | 内容 | 阶段 |
|---|---|---|---|
| [base-cache.md](base-cache.md) | collectors/base.py | DataSource 协议、TTL 两级缓存、重试退避、MOCK 切换 | P3 |
| [market.md](market.md) | collectors/market.py | 行情/财报/技术原始数据/指数体制层（yfinance） | P3 |
| [macro.md](macro.md) | collectors/macro.py | FRED 宏观系列（含 v1.1 扩充） | P3 |
| [news-pipeline.md](news-pipeline.md) | collectors/news.py | 事件增量管道：多源抓取→去重→预过滤→批量抽取 | P3 |
| [x-crawler.md](x-crawler.md) | collectors/x_crawler.py + scripts/export_x_cookie.py | X 登录态、抓取流程、防风控、情绪打标 | P7 |
| [scheduler.md](scheduler.md) | scheduler.py | 三类调度任务、时区约定、同日重复分析 | P9 |

## 分层频率总表

| 层 | 内容 | 频率 | 触发方式 |
|---|---|---|---|
| **事件管道（准实时）** | 新闻 RSS 多源 + Google News 关键词流 + WebSearch 定时检索 | **15~30 分钟一轮**（`EVENT_POLL_INTERVAL_MIN` 可配，默认 20） | APScheduler 常驻轮询，24 小时运行（覆盖美东盘前/盘中/盘后） |
| 行情 | yfinance 行情/财报 | 交易时段 15min TTL，收盘后当日不再刷新 | 轮询/按需 |
| 宏观数据 | FRED 系列 | 12h TTL（日频数据，高频无意义） | 轮询/按需 |
| X 博主 | Playwright 帖子 | 每博主每天最多 1 次（防风控硬约束，不参与准实时） | 低频定时 |
