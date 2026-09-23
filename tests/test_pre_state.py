"""pre-state 模块验收（v1.3）：T0 前状态计算、匹配附加、回填保守语义。"""

from datetime import date, timedelta

from domain.events import EventMatchResult, HistoricalEvent, MarketMetrics, TickerImpact
from domain.stock import DailyBar
from events_lib import pre_state
from events_lib.loader import load_seed_events


def _bars(closes: list[float], start: date = date(2025, 1, 1)) -> list[DailyBar]:
    day, bars = start, []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(date=day, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6))
        day += timedelta(days=1)
    return bars


# ---------- compute_pre_state ----------


def test_compute_pre_state_ramp() -> None:
    bars = _bars([100 * (1 + 0.001 * i) for i in range(260)])
    t0 = bars[-1].date + timedelta(days=1)     # 全部 K 线都在 T0 前
    state = pre_state.compute_pre_state(bars, t0)
    assert state is not None
    assert -1 < state["pre_drawdown_52w"] <= 0  # 上升序列：贴近前高
    assert state["pre_bias_ma200"] > 0          # 收盘在 MA200 上方
    expected_runup = (bars[-1].close / bars[-21].close - 1) * 100
    assert abs(state["pre_runup_20d"] - round(expected_runup, 1)) < 0.05
    assert 50 < state["pre_rsi14"] <= 100       # 单边上行


def test_compute_pre_state_excludes_event_day_and_short_history() -> None:
    bars = _bars([100.0] * 30 + [95.0] * 5)     # 末 5 根下跌（模拟事件后走势）
    t0 = bars[-5].date                          # 事件日 = 下跌首日 → 前状态不含下跌
    state = pre_state.compute_pre_state(bars, t0)
    assert state is not None
    assert state["pre_drawdown_52w"] == 0.0     # 只看 T0 前（全平）
    assert state["pre_bias_ma200"] is None      # 不足 200 根 → 乖离缺失（不硬造）
    assert state["pre_runup_20d"] == 0.0

    assert pre_state.compute_pre_state(bars[:10], t0) is None   # 前置 K 线不足 → None


# ---------- attach_pre_state ----------


def _hist_event() -> HistoricalEvent:
    return HistoricalEvent(
        event_id="2022-10-chip-export-rule", name="芯片出口管制", start_date=date(2022, 10, 7),
        category="regulation", summary="x", mechanism="y",
        tickers_affected=[
            TickerImpact(ticker="NVDA", direction=-1, magnitude=0.8,
                         pre_drawdown_52w=-50.0, pre_bias_ma200=-15.0),
            TickerImpact(ticker="SMH", direction=-1, magnitude=0.6),
        ],
        market=MarketMetrics(),
    )


def test_attach_pre_state() -> None:
    event = _hist_event()
    match = EventMatchResult(event_id=event.event_id, similarity=0.8, direction=-1)
    assert pre_state.attach_pre_state(match, event, "nvda") is True   # 大小写不敏感
    assert match.pre_drawdown_52w == -50.0 and match.pre_bias_ma200 == -15.0

    match2 = EventMatchResult(event_id=event.event_id, similarity=0.7, direction=-1)
    assert pre_state.attach_pre_state(match2, event, "AMD") is False  # 未列出标的
    assert match2.pre_bias_ma200 is None
    # SMH 已列出但未回填 pre-state → False 且不动
    match3 = EventMatchResult(event_id=event.event_id, similarity=0.7, direction=-1)
    assert pre_state.attach_pre_state(match3, event, "SMH") is False


# ---------- backfill_events（保守语义） ----------


class FakeMarket:
    def __init__(self, bars_by_symbol, fail_symbols=()):
        self._bars = bars_by_symbol
        self._fail = set(fail_symbols)

    def get_daily_bars_between(self, symbol, start, end):
        if symbol in self._fail:
            raise RuntimeError("rate limited")
        return self._bars[symbol]


def test_backfill_conservative_semantics() -> None:
    # 400 根 K 线横跨 t0 前后（前 ≥200 根供乖离，后 ≥21 根供市场指标窗口）
    ramp = _bars([100 * (1 + 0.001 * i) for i in range(400)], start=date(2024, 3, 1))
    t0 = date(2025, 6, 2)
    event = HistoricalEvent(
        event_id="e-backfill", name="测试事件", start_date=t0, category="macro",
        summary="s", mechanism="m",
        tickers_affected=[
            TickerImpact(ticker="AAA", direction=-1, magnitude=0.5),          # 待回填
            TickerImpact(ticker="BBB", direction=-1, magnitude=0.5,
                         pre_drawdown_52w=-12.3),                             # 已有人工值
            TickerImpact(ticker="ERR", direction=-1, magnitude=0.5),          # 获取失败
        ],
        market=MarketMetrics(),
    )
    market = FakeMarket({"AAA": ramp, "BBB": ramp, "SPY": ramp, "^VIX": ramp},
                        fail_symbols={"ERR"})
    report = pre_state.backfill_events([event], market, sleep=lambda: None, progress=None)

    assert report["pre_state_filled"] == 2                     # AAA + BBB（补缺失字段）
    assert event.tickers_affected[0].pre_bias_ma200 is not None
    assert event.tickers_affected[1].pre_drawdown_52w == -12.3  # 人工值不被覆盖
    assert event.tickers_affected[1].pre_bias_ma200 is not None  # 其余字段照补
    assert report["market_filled"] == 1 and event.market.sp500_1w is not None
    assert any(f[1] == "ERR" for f in report["failed"])         # 失败记录不中断

    # 再跑一遍：全部已回填 → 不再计
    report2 = pre_state.backfill_events([event], market, sleep=lambda: None, progress=None)
    assert report2["pre_state_filled"] == 0 and report2["market_filled"] == 0


# ---------- 种子库扩容校验（v1.3） ----------


def test_seed_library_expanded_and_valid() -> None:
    events = load_seed_events()                 # loader 严格校验 + 唯一性
    assert len(events) >= 43
    assert sum(1 for e in events if e.fizzled) >= 5
    assert sum(1 for e in events if "机制类比" in e.tags) >= 5
    assert any(e.start_date.year < 2018 for e in events)        # pre-2018 覆盖体制转折
    assert any("fizzled" in e.tags for e in events if e.fizzled)
