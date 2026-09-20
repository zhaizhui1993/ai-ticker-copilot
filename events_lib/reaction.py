"""事件关联个股的价格反应富化。

解决"当前事件缺乏个股股价变动趋势"：事件入库时，对其提及的股票
（最多 MAX_TICKERS_PER_EVENT 只）计算五项反应指标，随 payload 落库：

- event_day_pct：事件日涨跌（事件日未收盘/无数据时取最近已收交易日，note 标注）
- prior_5d / prior_20d_pct：事件前趋势背景（**不含**事件日，避免污染"背景"语义）
- drawdown_52w：事件时点距 52 周高点回撤
- volume_ratio：事件日量比（vs 前 20 日均量）

所有计算以 occurred_date 截断日线（纯函数 compute_reaction 可独立测试）。
行情失败按降级协议：该 ticker 反应缺省，不影响事件入库。
"""

from datetime import date

from domain.events import CurrentEvent, PriceReaction
from domain.stock import DailyBar

MAX_TICKERS_PER_EVENT = 3


def compute_reaction(ticker: str, bars: list[DailyBar], event_date: date) -> PriceReaction | None:
    """以 event_date 截断日线后计算五项反应指标（纯函数）。"""
    bars = [b for b in bars if b.date <= event_date]
    if not bars:
        return None
    last = bars[-1]
    note = "" if last.date == event_date else f"事件日无收盘数据，取最近交易日 {last.date}"

    event_day_pct = prior_5d = prior_20d = drawdown = volume_ratio = None
    if len(bars) >= 2 and bars[-2].close:
        event_day_pct = round((last.close / bars[-2].close - 1) * 100, 2)
    if len(bars) >= 6 and bars[-6].close:
        prior_5d = round((bars[-2].close / bars[-6].close - 1) * 100, 2)
    if len(bars) >= 21 and bars[-21].close:
        prior_20d = round((bars[-2].close / bars[-21].close - 1) * 100, 2)
    window = bars[-252:]
    if window:
        high = max(b.close for b in window)
        if high:
            drawdown = round((last.close / high - 1) * 100, 2)
    if len(bars) >= 21 and last.volume:
        avg = sum(b.volume for b in bars[-21:-1]) / 20
        if avg:
            volume_ratio = round(last.volume / avg, 2)

    return PriceReaction(
        ticker=ticker, event_day_pct=event_day_pct,
        prior_5d_pct=prior_5d, prior_20d_pct=prior_20d,
        drawdown_52w=drawdown, volume_ratio=volume_ratio,
        as_of=last.date, note=note,
    )


def enrich_events(events: list[CurrentEvent], market) -> list[CurrentEvent]:
    """对每条事件的 tickers_mentioned 富化价格反应（原地更新，返回同一列表）。

    market：MarketCollector 或 MockMarket（get_daily_bars 接口）。
    单 ticker 行情失败静默降级（该反应缺省），不中断管道。
    """
    bars_cache: dict[str, list[DailyBar]] = {}
    for event in events:
        reactions: list[PriceReaction] = []
        for ticker in [t for t in event.tickers_mentioned if t][:MAX_TICKERS_PER_EVENT]:
            try:
                if ticker not in bars_cache:
                    bars_cache[ticker] = market.get_daily_bars(ticker, 300)
                reaction = compute_reaction(ticker, bars_cache[ticker], event.occurred_date)
                if reaction:
                    reactions.append(reaction)
            except Exception as exc:
                print(f"[reaction] {ticker} 行情获取失败（反应缺省）：{exc}")
        event.price_reactions = reactions
    return events
