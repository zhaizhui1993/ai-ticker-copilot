# 09-交付 ｜ 配置与运行（runbook）

> 模块：09 交付与运维 ｜ 成分：环境与运行 ｜ 对应代码：pyproject.toml、.env、main.py、scheduler.py ｜ 实施阶段：P0
> 来源：原方案 §10

## 10.1 依赖清单（pyproject.toml）

```
fastapi>=0.115  uvicorn[standard]>=0.34  pydantic>=2.10  pydantic-settings>=2.6
python-dotenv>=1.0  pyyaml>=6.0
langchain>=0.3.27  langchain-core>=1.0.2  langchain-openai>=0.3.35   # 对齐现有 lock，uv 缓存可复用
yfinance==1.5.2  curl-cffi>=0.15,<0.16  fred-py-api>=1.2.1  feedparser>=6.0
httpx>=0.28  playwright>=1.50  tenacity>=9.0  apscheduler>=3.11
pymysql>=1.1  dbutils>=3.1
dev: pytest>=8.3  pytest-asyncio>=0.25
```

## 10.2 .env 环境变量

```
LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_TEMPERATURE   # 任意 OpenAI 兼容大模型，供应商无关（v1.2）
FRED_API_KEY                 # https://fred.stlouisfed.org 注册免费
MOCK_MODE=false              # true=全链路 mock 数据（无网无 key 验证系统）
DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME   # MySQL 连接
CACHE_DIR                    # 相对项目根
# X 数据源三选一：api=twitterapi.io 接口（推荐，配 X_API_KEY）｜crawl=Playwright 爬虫（需登录态）｜off=关闭
X_MODE=crawl
X_API_KEY / X_API_BASE       # twitterapi.io 控制台获取；X_MODE=api 时必填
X_STORAGE_STATE_PATH / MAX_X_BLOGGERS_PER_RUN / X_POST_HOURS_BACK   # 两通道共用
NEWS_RSS_FEEDS               # 逗号分隔，空则内置默认源（可追加）
SCHEDULER_ENABLED=true       # 四类任务：事件轮询+收盘分析(ET 17:35)+X 抓取(ET 9:00)+自动沉淀(ET 8:00)
EVENT_POLL_INTERVAL_MIN=20   # 事件管道轮询间隔（分钟）
NEW_EVENT_NOTIFY=false       # 新事件到达发 macOS 系统通知（osascript，零依赖）
SKIP_DB_CHECK                # （仅开发逃生门，web/app.py 直读）DB 失败仅警告继续启动
```

## 10.3 运行方式

```bash
# 0. 准备 MySQL 8（二选一）：
#    A. 复用本机已有 MySQL：建库建表由应用启动时自动完成，只需在 .env 填连接信息
#    B. Docker 一键拉起：docker compose up -d mysql（随项目提供 docker-compose.yml）
uv sync
# X 采集准备（按 X_MODE 二选一）：
#   api（推荐）：twitterapi.io 控制台拿 key 填 .env，无需登录态
#   crawl：uv run playwright install chromium（约 150MB）
#         + uv run python scripts/export_x_cookie.py 登录 X 一次保存登录态
uv run python main.py                  # 起 Web 面板 → http://127.0.0.1:8000
# CLI 备选（scripts/，每个数据源可独立验证）：
uv run python scripts/refresh_data.py --scope market|macro|news|all   # 手动刷新缓存
uv run python scripts/analyze.py --ticker NVDA                        # 不起 Web 直接端到端分析
uv run python scripts/crawl_x.py                                      # 手动抓 X（X_MODE 路由）
uv run python scripts/mine_events.py --symbol ^IXIC --since 2024-01-01  # 回调波段挖掘（或 --csv 离线数据）
uv run python scripts/build_events.py --draft ...                     # 事件草稿骨架（占位版）
uv run python scripts/backfill_events.py --event 2025-01-deepseek-shock  # 历史事件量化回填（--write 回写 market 指标）
uv run pytest                                                         # 跑全部测试
```
