"""APScheduler 调度器（默认开 SCHEDULER_ENABLED=true）。

三类核心任务 + 自动沉淀（docs/03-collectors/scheduler.md、docs/04-events/auto-sedimentation.md）：
① 事件轮询：interval EVENT_POLL_INTERVAL_MIN（默认 20min），24h 运行
② 完整分析：cron，America/New_York 周一至五 17:35（收盘后）
③ X 低频抓取：每天 1 次（防风控硬约束）
④ 当前事件自动沉淀：T+60/T+180 天回填草稿（source='auto'，人工核对后转正）

实现约定：
- 任务到点后在线程中执行（避免阻塞 asyncio 事件循环）；
- 并发防护：完整分析走 pipeline/web 的全局锁语义；X 抓取靠 crawl_state 每日节流；
  事件轮询天然增量幂等（hash 去重）。
"""

import threading

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings

ET = "America/New_York"


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True, name=f"atc-{fn.__name__}").start()


def _pool_tickers() -> list[str]:
    from config.loader import load_stocks
    return [s.symbol for s in load_stocks()]


# ---------- 任务体 ----------


def poll_events_job() -> None:
    """① 事件轮询：抓取→去重→预过滤→抽取→入库（不触发分析）。"""
    from collectors import get_news
    from collectors.news import poll_once

    tickers = _pool_tickers()
    collector = get_news()
    summary = (collector.poll_once(tickers)
               if hasattr(collector, "poll_once") else poll_once(tickers))
    if summary.get("stored"):
        print(f"[scheduler] 事件轮询：新增 {summary['stored']} 条事件入库")
    if summary.get("db_error"):
        print(f"[scheduler] 事件轮询入库降级：{summary['db_error']}")


def full_analysis_job() -> None:
    """② 收盘后完整分析（refresh=True）。"""
    from analyzer.pipeline import run_analysis
    try:
        outcome = run_analysis(refresh=True)
        signals = ", ".join(f"{s.ticker}:{s.action.value}" for s in outcome["result"].signals)
        print(f"[scheduler] 收盘分析完成 → {signals or '（空池）'}")
    except Exception as exc:
        print(f"[scheduler] 收盘分析失败（不影响下轮）：{exc}")


def crawl_x_job() -> None:
    """③ X 低频抓取（每博主每天 1 次节流；X_MODE=api|crawl|off 路由）。"""
    from collectors.x_source import crawl_and_store
    from config.loader import load_influencers
    from config.settings import settings as cfg

    if cfg.x_mode == "off":
        return
    influencers = load_influencers()
    if not influencers:
        return
    try:
        outcome = crawl_and_store(influencers, _pool_tickers())
        print(f"[scheduler] X 抓取（{outcome.get('mode', cfg.x_mode)}）："
              f"{len(outcome['posts'])} 条，入库 {outcome['stored']}")
        if outcome.get("error"):
            print(f"[scheduler] X 抓取终止：{outcome['error']}")
    except Exception as exc:
        print(f"[scheduler] X 抓取失败（明日重试）：{exc}")


def sediment_events_job() -> None:
    """④ 当前事件自动沉淀：T+60/T+180 天回填实测反应，生成待核对草稿。

    草稿 source='auto' 且带 '待核对' 标签；不参与类比匹配（pipeline 的
    类比库只取 seed + user），人工在 Web 端确认后转 source='user'。
    """
    from datetime import date

    from events_lib.auto_sediment import sediment_due_events
    try:
        created = sediment_due_events(date.today())
        if created:
            print(f"[scheduler] 自动沉淀：生成 {len(created)} 条待核对草稿（{', '.join(created)}）")
    except Exception as exc:
        print(f"[scheduler] 自动沉淀失败（不影响其他任务）：{exc}")


# ---------- 组装 ----------


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ET, job_defaults={"coalesce": True, "max_instances": 1})

    scheduler.add_job(
        lambda: _spawn(poll_events_job), "interval",
        minutes=settings.event_poll_interval_min, id="event_poll",
        name=f"事件轮询({settings.event_poll_interval_min}min)",
    )
    scheduler.add_job(
        lambda: _spawn(full_analysis_job), CronTrigger(
            day_of_week="mon-fri", hour=17, minute=35, timezone=ET),
        id="eod_analysis", name="收盘分析(ET 17:35)",
    )
    scheduler.add_job(
        lambda: _spawn(crawl_x_job), CronTrigger(
            hour=9, minute=0, timezone=ET),
        id="x_crawl", name="X 抓取(每日)",
    )
    scheduler.add_job(
        lambda: _spawn(sediment_events_job), CronTrigger(
            hour=8, minute=0, timezone=ET),
        id="auto_sediment", name="事件自动沉淀(每日)",
    )
    return scheduler
