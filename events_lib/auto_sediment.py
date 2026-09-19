"""当前事件自动沉淀（v1.1 滚雪球机制，docs/04-events/auto-sedimentation.md）。

对发生 T+60 / T+180 天的当前事件，复用 backfill 算法实测其市场反应，
生成 source='auto' 的草稿（tags 含"待核对"）；不参与类比匹配，
人工确认后转 source='user' 转正。幂等：同一事件同一窗口只沉淀一次。
"""

from datetime import date, timedelta

from domain.events import EventCategory, HistoricalEvent, TickerImpact
from events_lib.linkage import compute_linkage, compute_market_metrics
from events_lib.loader import load_seed_events

SEDIMENT_WINDOWS = (60, 180)
WINDOW_TOLERANCE = 3   # 允许 ±3 天触发（调度器每日一跑）
MAX_TICKERS = 6        # 单事件最多回填标的数（池内优先）


def _auto_event_id(source_event_id: str, window: int) -> str:
    return f"auto-{window}-{source_event_id}"


def sediment_due_events(today: date) -> list[str]:
    """扫描到期事件并生成草稿，返回新建的 event_id 列表。"""
    from collectors import get_market
    from storage import repository

    current_events = repository.list_current_events(limit=200)
    if not current_events:
        return []

    existing_ids = {e.event_id for e in repository.list_events()}
    market = get_market()
    pool_tickers = _pool_tickers()

    created: list[str] = []
    for event in current_events:
        age = (today - event.occurred_date).days
        window = next((w for w in SEDIMENT_WINDOWS
                       if abs(age - w) <= WINDOW_TOLERANCE), None)
        if window is None:
            continue
        auto_id = _auto_event_id(event.event_id, window)
        if auto_id in existing_ids:
            continue  # 幂等：该窗口已沉淀

        tickers = [t for t in pool_tickers if t in event.tickers_mentioned] \
            or event.tickers_mentioned[:MAX_TICKERS] or pool_tickers[:MAX_TICKERS]

        start = event.occurred_date - timedelta(days=90)
        end = event.occurred_date + timedelta(days=400)
        impacts: list[TickerImpact] = []
        for ticker in tickers:
            try:
                bars = market.get_daily_bars_between(ticker, start, end)
                result = compute_linkage(bars, event.occurred_date)
            except Exception:
                result = None
            if result:
                impacts.append(TickerImpact(
                    ticker=ticker, direction=-1 if result["drawdown"] < 0 else 1,
                    magnitude=0.5,
                    drawdown=result["drawdown"],
                    drawdown_days=result["drawdown_days"],
                    recovery_days=result["recovery_days"],
                ))

        market_metrics = {}
        try:
            spy = market.get_daily_bars_between("SPY", start, end)
            vix = market.get_daily_bars_between("^VIX", start, end)
            market_metrics = compute_market_metrics(spy, vix, event.occurred_date)
        except Exception:
            pass

        draft = HistoricalEvent(
            event_id=auto_id,
            name=f"[自动沉淀 T+{window}] {event.title[:60]}",
            start_date=event.occurred_date,
            category=event.category,
            summary=event.summary[:200],
            mechanism=f"源自当前事件 {event.event_id}（{event.source}）的 T+{window} 实测沉淀",
            keywords=event.keywords or [event.category.value],
            tickers_affected=impacts,
            market=_metrics_model(market_metrics),
            tags=["auto-draft", "待核对", f"window=T+{window}"],
        )
        repository.put_event(draft, source="auto")
        created.append(auto_id)
    return created


def _metrics_model(raw: dict):
    from domain.events import MarketMetrics
    return MarketMetrics(
        sp500_1w=raw.get("sp500_1w"), sp500_1m=raw.get("sp500_1m"),
        vix_peak=raw.get("vix_peak"),
    )


def _pool_tickers() -> list[str]:
    from config.loader import load_stocks
    return [s.symbol for s in load_stocks()]


def load_matching_lib() -> list[HistoricalEvent]:
    """类比库 = seed + user（auto 草稿不参与匹配，确认后转 user 才生效）。"""
    from storage import repository
    lib = load_seed_events()
    try:
        lib += repository.list_events(source="user")
    except Exception:
        pass
    return lib
