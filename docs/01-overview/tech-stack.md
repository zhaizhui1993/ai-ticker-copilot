# 01-总览 ｜ 技术选型

> 模块：01 总览与架构 ｜ 成分：技术选型 ｜ 实施阶段：P0
> 来源：原方案 §3

## 3. 技术选型

| 层 | 选型 | 版本约束 | 理由 / 备选 |
|---|---|---|---|
| 语言/包管理 | Python + uv | 3.13.9 | 复用现有环境与 lock 缓存；uv 管理 Python 与依赖 |
| Web 框架 | FastAPI + uvicorn | fastapi>=0.115 | 异步、自带 OpenAPI；本地个人服务足够 |
| 配置 | pydantic-settings + python-dotenv + PyYAML | >=2.6 | 与现有项目模式一致，.env 集中管理 key |
| LLM | LangChain + langchain-openai | 对齐现有 lock | 任意 OpenAI 兼容大模型（供应商经 .env 切换、代码零改动）；LangChain 负责结构化输出封装 |
| 行情/财报 | yfinance | ==1.5.2 | 免费无 key；需配 `curl-cffi>=0.15,<0.16`（0.16 曾致断裂）；备选降级 Stooq CSV |
| 宏观数据 | FRED + fred-py-api | >=1.2.1 | 美联储官方，免费 key 注册即得，120 req/min |
| 新闻 | feedparser + httpx | — | RSS 零成本；WebSearch 补充检索 |
| 爬虫 | Playwright | >=1.50 | 唯一可靠方案（X 免费 API 已关闭）；storage_state 注入登录态 |
| 重试 | tenacity | >=9.0 | 指数退避 |
| 调度 | APScheduler | >=3.11 | 事件轮询（15~30min）与收盘分析的核心组件，默认开 |
| 前端 | Vue3 全局构建 + ECharts + 原生 CSS | — | 无 node 构建链；用户有 Vue3 经验；ECharts 金融图表事实标准，本地 vendor 化 |
| 存储 | MySQL 8 + PyMySQL + DBUtils 连接池 | 8.0 | 用户指定；原生 JSON 类型存评分/分析结果；薄 repository 裸 SQL，不引 ORM |
| 测试 | pytest + pytest-asyncio | >=8.3 | mock 路径全链路 |

**明确不用**：LangGraph（流程线性，普通函数编排即可）、embedding 向量检索（事件库几十条规模，见 [04-events/matcher.md](../04-events/matcher.md)）、ORM、Redis/消息队列、用户系统、前端构建链（Vite/npm）、Docker 容器化（应用本体本地直接 uv run；仅 MySQL 例外，本机无实例时用随仓库的 docker-compose 拉起）。
