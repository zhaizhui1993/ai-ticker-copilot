# 08-Web ｜ REST API 清单

> 模块：08 Web 面板 ｜ 成分：API 路由 ｜ 对应代码：web/api/ ｜ 实施阶段：P8（/api/chat 为实施期增补）
> 来源：原方案 §8.1

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查：mock_mode / scheduler_enabled / llm_model / db_host 等运行状态 |
| GET | /api/dashboard | 股票池卡片聚合：现价/涨跌/最新信号（总分与四维分待接入，快照中暂为 null）；体制层条（指数 vs MA200/VIX/费半 ATR14）；数据源状态；`?refresh=1` 实时拉报价（默认读快照防限频） |
| GET | /api/stocks | 读取股票池 |
| PUT | /api/stocks | 保存股票池（校验 symbol 合法） |
| GET | /api/stocks/{symbol} | 个股详情：K 线 + MA20/MA50（`?window=3M/6M/1Y`，默认 6M）+ 技术指标表（RSI14/ATR14/量比/回撤/乖离）；四维分与事件类比卡为规划 |
| GET | /api/events | 当前事件列表（含每事件的 `price_reactions` 价格反应；`?limit=` 默认 100）；scope 筛选与类比卡为规划 |
| GET | /api/events/poll?since= | 增量拉取新事件（since 为 ISO 日期，按 occurred_date 过滤 current_events，默认 limit 50；前端轮询驱动未读徽章） |
| GET | /api/calendar | 经济日历（FOMC 静态日程/宏观发布惯例/财报日，未来 7 天） |
| GET | /api/events/lib | 历史事件库浏览（`?source=` 可筛选 seed/user/auto；**DB 不可用时自动降级展示 seed_events.yaml 文件内容**） |
| PUT | /api/events/lib | 用户新增历史事件（source='user'，direction/magnitude 当前固定 -1/0.5） |
| POST | /api/analysis/run | 触发分析；body `{refresh: bool, tickers?: list[str]}`——refresh 区分"用现有数据"与"刷新并分析"，tickers 可选只分析池内子集 |
| GET | /api/analysis/history | 历史分析记录列表（analysis_runs 的 run_id/created_at） |
| GET | /api/config | 博主列表、评分权重、数据源状态（x_mode/x api key 已配置/crawl cookie 就绪/调度器开关/股票池规模） |
| PUT | /api/config | 更新博主列表 / 权重 |
| POST | /api/chat | 研究助理多轮对话（实施期增补）：body `{messages: [{role, content}]}`（1~60 条，服务端截最近 20 轮）；返回 `{reply, disclaimer}`；LLM 未配置 503、空消息 400、调用失败 502（详见 [06-analyzer/README.md](../06-analyzer/README.md)） |

全局：分析接口由 web 层模块级 **threading.Lock** 串行化（FastAPI 同步路由线程池并发），重复提交返回 409（已有分析进行中）；`GET /api/x/posts`（帖子流 + 情绪分布）为 P7 规划端点，暂未实现。

启动行为：lifespan 建库建表 + 种子 upsert + 按 `SCHEDULER_ENABLED` 拉起调度器；环境变量 `SKIP_DB_CHECK=true` 为开发逃生门（DB 失败仅警告继续启动）。
