"""APScheduler 调度器（默认开 SCHEDULER_ENABLED=true）。

五类业务任务（docs/03-collectors/scheduler.md、docs/04-events/auto-sedimentation.md）：
① 采集新闻并识别市场事件：interval EVENT_POLL_INTERVAL_MIN（默认 20min），24h 运行
② 生成股票池收盘研判与风险信号：cron，America/New_York 周一至五 17:35（收盘后）
③ 采集关注博主的 X 帖子：每天 1 次（防风控硬约束）
④ 回填事件市场表现并生成历史案例草稿：T+60/T+180 天回填草稿（source='auto'，人工核对后转正）
⑤ 评估历史研判信号并归档月报：每月 1 日 10:00（ET）生成固定指标集评测报告并追加存档（data/eval/）

实现约定：
- 任务到点后在线程中执行（避免阻塞 asyncio 事件循环）；
- 并发防护：完整分析走 pipeline/web 的全局锁语义；采集关注博主的 X 帖子靠 crawl_state 每日节流；
  采集新闻并识别市场事件天然增量幂等（hash 去重）。
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


def collect_news_events_job() -> None:
    """① 采集新闻并识别市场事件：抓取→去重→预过滤→抽取→入库（不触发分析）。"""
    from collectors import get_news
    from collectors.news import poll_once

    tickers = _pool_tickers()
    collector = get_news()
    summary = (collector.poll_once(tickers)
               if hasattr(collector, "poll_once") else poll_once(tickers))
    if summary.get("stored"):
        print(f"[scheduler] 采集新闻并识别市场事件：新增 {summary['stored']} 条事件入库")
    if summary.get("db_error"):
        print(f"[scheduler] 采集新闻并识别市场事件入库降级：{summary['db_error']}")


def generate_stock_pool_close_signals_job() -> None:
    """② 生成股票池收盘研判与风险信号（refresh=True）。"""
    from analyzer.pipeline import run_analysis
    try:
        outcome = run_analysis(refresh=True)
        signals = ", ".join(f"{s.ticker}:{s.action.value}" for s in outcome["result"].signals)
        print(f"[scheduler] 生成股票池收盘研判与风险信号完成 → {signals or '（空池）'}")
    except Exception as exc:
        print(f"[scheduler] 生成股票池收盘研判与风险信号失败（不影响下轮）：{exc}")


def collect_influencer_x_posts_job() -> None:
    """③ 采集关注博主的 X 帖子（每博主每天 1 次节流；X_MODE=api|crawl|off 路由）。"""
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
        print(f"[scheduler] 采集关注博主的 X 帖子（{outcome.get('mode', cfg.x_mode)}）："
              f"{len(outcome['posts'])} 条，入库 {outcome['stored']}")
        if outcome.get("error"):
            print(f"[scheduler] 采集关注博主的 X 帖子终止：{outcome['error']}")
    except Exception as exc:
        print(f"[scheduler] 采集关注博主的 X 帖子失败（明日重试）：{exc}")


def backfill_event_outcomes_and_build_drafts_job() -> None:
    """④ 回填事件市场表现并生成历史案例草稿：T+60/T+180 天回填实测反应，生成待核对草稿。

    草稿 source='auto' 且带 '待核对' 标签；不参与类比匹配（pipeline 的
    类比库只取 seed + user），人工在 Web 端确认后转 source='user'。
    """
    from datetime import date

    from events_lib.auto_sediment import sediment_due_events
    try:
        created = sediment_due_events(date.today())
        if created:
            print(f"[scheduler] 回填事件市场表现并生成历史案例草稿：生成 {len(created)} 条待核对草稿（{', '.join(created)}）")
    except Exception as exc:
        print(f"[scheduler] 回填事件市场表现并生成历史案例草稿失败（不影响其他任务）：{exc}")


def evaluate_signals_and_archive_report_job() -> None:
    """⑤ 评估历史研判信号并归档月报：固定指标集全量报告 → data/eval/monthly-YYYY-MM.md 追加存档。

    追加式存档（只增不覆盖）形成不可回改的跟踪记录——防自欺机制；
    mock 模式跳过（数字无意义）。见 analyzer/evaluation.py。
    """
    from analyzer import evaluation
    try:
        evaluation.run_monthly_report()
    except Exception as exc:
        print(f"[scheduler] 评估历史研判信号并归档月报失败（不影响其他任务）：{exc}")


# ---------- 组装 ----------


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ET, job_defaults={"coalesce": True, "max_instances": 1})

    scheduler.add_job(
        lambda: _spawn(collect_news_events_job), "interval",
        minutes=settings.event_poll_interval_min, id="collect_news_events",
        name=f"采集新闻并识别市场事件({settings.event_poll_interval_min}min)",
    )
    scheduler.add_job(
        lambda: _spawn(generate_stock_pool_close_signals_job), CronTrigger(
            day_of_week="mon-fri", hour=17, minute=35, timezone=ET),
        id="generate_stock_pool_close_signals", name="生成股票池收盘研判与风险信号(ET 17:35)",
    )
    scheduler.add_job(
        lambda: _spawn(collect_influencer_x_posts_job), CronTrigger(
            hour=9, minute=0, timezone=ET),
        id="collect_influencer_x_posts", name="采集关注博主的 X 帖子(每日)",
    )
    scheduler.add_job(
        lambda: _spawn(backfill_event_outcomes_and_build_drafts_job), CronTrigger(
            hour=8, minute=0, timezone=ET),
        id="backfill_event_outcomes_and_build_drafts", name="回填事件市场表现并生成历史案例草稿(每日)",
    )
    scheduler.add_job(
        lambda: _spawn(evaluate_signals_and_archive_report_job), CronTrigger(
            day=1, hour=10, minute=0, timezone=ET),
        id="evaluate_signals_and_archive_report", name="评估历史研判信号并归档月报(每月1日)",
    )
    return scheduler
