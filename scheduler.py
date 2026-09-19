"""APScheduler 调度器（P9 实现，默认开 SCHEDULER_ENABLED=true）。

三类任务（docs/03-collectors/scheduler.md）：
① 事件轮询：interval EVENT_POLL_INTERVAL_MIN（15~30min），24h 运行
② 完整分析：cron，America/New_York 时区周一至五 17:35（收盘后）
③ X 低频抓取：每天 1 次（防风控硬约束）
另挂事件自动沉淀任务（T+60/T+180，docs/04-events/auto-sedimentation.md）。

并发约定：模块级 asyncio.Lock 全局锁；同日重复分析直接返回已存快照。
时区约定：所有"日"以美东交易日为准；事件时间戳存 UTC。
"""
