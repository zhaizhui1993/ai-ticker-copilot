# 09-交付 ｜ 配置与运行（runbook）

> 模块：09 交付与运维 ｜ 成分：环境与运行 ｜ 对应代码：pyproject.toml、.env、main.py ｜ 实施阶段：P0
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
X_STORAGE_STATE_PATH / MAX_X_BLOGGERS_PER_RUN / X_POST_HOURS_BACK
NEWS_RSS_FEEDS               # 逗号分隔，空则内置默认源（可追加）
SCHEDULER_ENABLED=true       # 事件轮询+收盘分析调度（准实时跟进，默认开）
EVENT_POLL_INTERVAL_MIN=20   # 事件管道轮询间隔（分钟）
NEW_EVENT_NOTIFY=false       # 新事件到达发 macOS 系统通知（osascript，零依赖）
```

## 10.3 运行方式

```bash
# 0. 准备 MySQL 8（二选一）：
#    A. 复用本机已有 MySQL：建库建表由应用启动时自动完成，只需在 .env 填连接信息
#    B. Docker 一键拉起：docker compose up -d mysql（随项目提供 docker-compose.yml）
uv sync
uv run playwright install chromium     # 首次需装浏览器内核（约 150MB）
uv run python scripts/export_x_cookie.py   # 登录 X 一次，保存登录态
uv run python main.py                  # 起 Web 面板 → http://127.0.0.1:8000
# CLI 备选：
uv run python scripts/refresh_data.py --scope market
uv run python scripts/analyze.py --ticker NVDA
```
