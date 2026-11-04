# 03-采集 ｜ 调度器（scheduler.py）

> 模块：03 数据采集层 ｜ 成分：APScheduler 调度 ｜ 对应代码：scheduler.py ｜ 实施阶段：P9
> 来源：原方案 §6.4（调度器/时区/同日重复条目）

## 五类任务（核心组件，默认开：`SCHEDULER_ENABLED=true`）

APScheduler AsyncIOScheduler 挂 FastAPI lifespan（`job_defaults: coalesce=True, max_instances=1`；任务到点在守护线程执行，避免阻塞事件循环）：

| # | 任务 / 调度 ID | 触发 | 说明 |
|---|---|---|---|
| ① | 采集新闻并识别市场事件<br>`collect_news_events` | interval，`EVENT_POLL_INTERVAL_MIN`（默认 20 分钟） | 驱动 [news-pipeline.md](news-pipeline.md)，将新闻抽取为当前事件并入库，供展示与后续研判使用，24 小时运行 |
| ② | 生成股票池收盘研判与风险信号<br>`generate_stock_pool_close_signals` | cron，America/New_York"周一至五 17:35"收盘后 | 调 [06-analyzer](../06-analyzer/README.md) 的 pipeline.run_analysis()，输出逐股研究信号、理由和风险提示，保存快照与审计记录 |
| ③ | 采集关注博主的 X 帖子<br>`collect_influencer_x_posts` | cron，每日 ET 09:00 | 经 x_source 路由抓取帖子并入库（X_MODE=api/crawl/off；每博主每天 1 次）；当前尚未用于评分 |
| ④ | 回填事件市场表现并生成历史案例草稿<br>`backfill_event_outcomes_and_build_drafts` | cron，每日 ET 08:00 | 对 T+60/T+180 天的事件回填实测市场表现，生成待核对案例草稿，见 [04-events/auto-sedimentation.md](../04-events/auto-sedimentation.md) |
| ⑤ | 评估历史研判信号并归档月报<br>`evaluate_signals_and_archive_report` | cron，每月 1 日 ET 10:00 | 评估历史信号后续表现、超额收益及置信度校准，追加归档到 `data/eval/`；mock 模式跳过 |

各任务入口函数为对应调度 ID 加 `_job` 后缀，注册时的 `name` 使用表中的中文业务名称并附触发时间。

## 并发与幂等约定

- 防并发：Web 层模块级 `threading.Lock`（手动触发与调度撞车时后到者直接返回 409）+ 调度器 `max_instances=1`；pipeline 本身无锁，靠同日幂等兜底。
- **同日重复分析**：当日快照已存在且未显式 refresh 时直接返回已存快照，不重复调 LLM。

## 时区约定

- 所有"日"以美东交易日为准；调度 cron 用 America/New_York；
- 事件时间戳存 UTC，展示层转 Asia/Shanghai 并标注；全程 USD，不做汇率换算。
