"""事件价格反应富化测试（合成数据已知值，含事件日截断语义）。"""

from datetime import date, timedelta

from collectors.mock import MockMarket
from domain.events import CurrentEvent, EventCategory, EventScope
from domain.stock import DailyBar
from events_lib.reaction import MAX_TICKERS_PER_EVENT, compute_reaction, enrich_events


def _bars(closes: list[float], volumes: list[float] | None = None,
          start: date = date(2026, 1, 1)) -> list[DailyBar]:
    volumes = volumes or [1e6] * len(closes)
    day, bars = start, []
    for c, v in zip(closes, volumes):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(date=day, open=c, high=c, low=c, close=c, volume=v))
        day += timedelta(days=1)
    return bars


def test_compute_reaction_known_values() -> None:
    # 30 根横盘 100，事件日跌到 90 且放量 3 倍
    closes = [100.0] * 29 + [90.0]
    volumes = [1e6] * 29 + [3e6]
    bars = _bars(closes, volumes)
    event_day = bars[-1].date

    r = compute_reaction("NVDA", bars, event_day)
    assert r is not None
    assert abs(r.event_day_pct - (-10.0)) < 1e-6
    assert r.prior_5d_pct == 0.0                       # 事件前的背景（不含事件日）
    assert r.prior_20d_pct == 0.0
    assert abs(r.drawdown_52w - (-10.0)) < 1e-6        # 事件日即 52 周新低
    assert abs(r.volume_ratio - 3.0) < 1e-6
    assert r.note == ""                                # 事件日有收盘数据


def test_compute_reaction_truncates_at_event_date() -> None:
    # 事件日之后还有暴跌：绝不能算进事件反应
    bars = _bars([100.0] * 20 + [95.0, 50.0])
    event_day = bars[-2].date
    r = compute_reaction("X", bars, event_day)
    assert abs(r.event_day_pct - (-5.0)) < 1e-6
    assert r.as_of == event_day


def test_compute_reaction_future_event_uses_latest() -> None:
    bars = _bars([100.0, 101.0, 102.0])
    future = bars[-1].date + timedelta(days=5)
    r = compute_reaction("X", bars, future)
    assert r is not None and "事件日无收盘数据" in r.note


def test_enrich_events_caps_and_degrades() -> None:
    market = MockMarket()
    event = CurrentEvent(
        event_id="t-1", title="t", occurred_date=date.today(),
        scope=EventScope.COMPANY, category=EventCategory.TECH, summary="",
        tickers_mentioned=["NVDA", "MRVL", "INTC", "LITE", "BADTICKER"],
        source="t",
    )
    enrich_events([event], market)
    assert len(event.price_reactions) == MAX_TICKERS_PER_EVENT   # 每事件最多 3 只
    assert all(r.event_day_pct is not None for r in event.price_reactions)

    # 行情整体失败：反应为空但不抛异常
    class DeadMarket:
        def get_daily_bars(self, *a, **k):
            raise RuntimeError("行情不可用")
    dead = CurrentEvent(event_id="t-2", title="t", occurred_date=date.today(),
                        scope=EventScope.COMPANY, category=EventCategory.TECH,
                        summary="", tickers_mentioned=["NVDA"], source="t")
    enrich_events([dead], DeadMarket())
    assert dead.price_reactions == []
