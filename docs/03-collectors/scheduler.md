# 03-采集 ｜ 调度器（scheduler.py）

> 模块：03 数据采集层 ｜ 成分：APScheduler 调度 ｜ 对应代码：scheduler.py ｜ 实施阶段：P9
> 来源：原方案 §6.4（调度器/时区/同日重复条目）

## 四类任务（核心组件，默认开：`SCHEDULER_ENABLED=true`）

APScheduler AsyncIOScheduler 挂 FastAPI lifespan（`job_defaults: coalesce=True, max_instances=1`；任务到点在线程池执行，避免阻塞事件循环）：

| # | 任务 | 触发 | 说明 |
|---|---|---|---|
| ① | 事件轮询 | interval，`EVENT_POLL_INTERVAL_MIN`（默认 20 分钟） | 驱动 [news-pipeline.md](news-pipeline.md)，24 小时运行覆盖美东盘前/盘中/盘后 |
| ② | 完整分析 | cron，America/New_York"周一至五 17:35"收盘后 | 调 [06-analyzer](../06-analyzer/README.md) 的 pipeline.run_analysis() |
| ③ | X 低频抓取 | cron，每日 ET 09:00 | 经 x_source 路由驱动（X_MODE=api/crawl/off；每博主每天 1 次为防风控/控费硬约束） |
| ④ | 事件自动沉淀 | cron，每日 ET 08:00 | T+60/T+180 天回填，见 [04-events/auto-sedimentation.md](../04-events/auto-sedimentation.md) |

## 并发与幂等约定

- 防并发：Web 层模块级 `threading.Lock`（手动触发与调度撞车时后到者直接返回 409）+ 调度器 `max_instances=1`；pipeline 本身无锁，靠同日幂等兜底。
- **同日重复分析**：当日快照已存在且未显式 refresh 时直接返回已存快照，不重复调 LLM。

## 时区约定

- 所有"日"以美东交易日为准；调度 cron 用 America/New_York；
- 事件时间戳存 UTC，展示层转 Asia/Shanghai 并标注；全程 USD，不做汇率换算。
