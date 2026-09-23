"""事件前状态（pre-state）计算与回填（v1.3 / 评审 P1-2 演进）。

为什么需要：历史回撤 = f(事件强度, 标的状态)。只记结果不记状态，类比会把
不同位置下的结果做无条件平均——同样的芯片管制打在"已跌 30%"和"乖离 +80%
新高"的位置，回撤完全不同（实证：2026-07 回调深度主要由事件前 +40%~120%
乖离率决定，见 docs/05-scoring/layered-technicals.md）。

口径约定：状态 = T0 前一交易日收盘（不含事件日本身，避免事件日污染前状态）。
- pre_drawdown_52w：事件前距 52 周高点回撤 %（≤0）
- pre_bias_ma200：事件前收盘/MA200 乖离 %（拥挤度代理；不足 200 交易日为 None）
- pre_runup_20d：事件前 20 交易日涨幅 %
- pre_rsi14：事件前 RSI14
"""

from datetime import date, timedelta

from domain import technicals
from domain.events import EventMatchResult, HistoricalEvent
from domain.stock import DailyBar

PRE_LOOKBACK_DAYS = 420     # 日历日（≈290 交易日，覆盖 252 日回看窗 + 缓冲）
POST_WINDOW_DAYS = 400      # 联动回填（drawdown/recovery）的后窗，同 backfill_events.py
MIN_BARS = 21               # 少于 21 根前置 K 线 → 整体放弃（连 20 日涨幅都算不了）


def compute_pre_state(bars: list[DailyBar], t0: date) -> dict | None:
    """T0 前状态（纯函数）。bars 升序；取 date < t0 的部分；不足返回 None。"""
    pre = [b for b in bars if b.date < t0]
    if len(pre) < MIN_BARS:
        return None
    return {
        "pre_drawdown_52w": _round(technicals.drawdown_from_high_pct(pre)),
        "pre_bias_ma200": _round(technicals.bias_vs_ma200_pct(pre)),  # <200 根 → None
        "pre_runup_20d": _round((pre[-1].close / pre[-21].close - 1) * 100
                                if len(pre) >= 21 else None),
        "pre_rsi14": _round(technicals.rsi(pre)),
    }


def _round(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def attach_pre_state(match: EventMatchResult, historical_event: HistoricalEvent,
                     ticker: str) -> bool:
    """把历史样本中该标的的 T0 前状态复制到匹配结果（代码附加，非 LLM 产出）。

    找不到该标的的 TickerImpact（或未回填）→ 不动，返回 False。
    """
    impact = next((t for t in historical_event.tickers_affected
                   if t.ticker.upper() == ticker.upper()), None)
    if impact is None:
        return False
    changed = False
    for field in ("pre_drawdown_52w", "pre_bias_ma200"):
        value = getattr(impact, field)
        if value is not None:
            setattr(match, field, value)
            changed = True
    return changed


def backfill_events(events: list[HistoricalEvent], market,
                    fill_market: bool = True, fill_linkage: bool = False,
                    sleep=None, progress=print) -> dict:
    """对事件库做 pre-state（必做）+ market/linkage（可选）回填，原地更新。

    保守语义：任何已有值不覆盖（人工核对过的数字优先于算法值）。
    返回报告 {pre_state_filled, market_filled, linkage_filled, failed[]}。
    """
    sleep = sleep or (lambda: None)
    report = {"events": len(events), "pre_state_filled": 0, "market_filled": 0,
              "linkage_filled": 0, "failed": []}

    for event in events:
        t0 = event.start_date

        # ① 逐标的 pre-state
        for impact in event.tickers_affected:
            missing = [f for f in ("pre_drawdown_52w", "pre_bias_ma200",
                                   "pre_runup_20d", "pre_rsi14")
                       if getattr(impact, f) is None]
            if not missing:
                continue
            try:
                bars = market.get_daily_bars_between(
                    impact.ticker, t0 - timedelta(days=PRE_LOOKBACK_DAYS), t0)
                state = compute_pre_state(bars, t0)
            except Exception as exc:
                report["failed"].append((event.event_id, impact.ticker, f"pre: {exc}"))
                continue
            sleep()
            if state is None:
                report["failed"].append((event.event_id, impact.ticker, "pre: 前置K线不足"))
                continue
            for field, value in state.items():
                if value is not None and getattr(impact, field) is None:
                    setattr(impact, field, value)
            report["pre_state_filled"] += 1

        # ② market 指标（空才补）
        if fill_market and not any(
                v is not None for v in (event.market.sp500_1w, event.market.sp500_1m,
                                        event.market.vix_peak)):
            try:
                from events_lib.linkage import compute_market_metrics
                spy = market.get_daily_bars_between("SPY", t0 - timedelta(days=90),
                                                    t0 + timedelta(days=POST_WINDOW_DAYS))
                vix = market.get_daily_bars_between("^VIX", t0 - timedelta(days=90),
                                                    t0 + timedelta(days=POST_WINDOW_DAYS))
                metrics = compute_market_metrics(spy, vix, t0)
                sleep()
                for key in ("sp500_1w", "sp500_1m", "vix_peak"):
                    value = metrics.get(key)
                    if value is not None and getattr(event.market, key) is None:
                        setattr(event.market, key, value)
                report["market_filled"] += 1
            except Exception as exc:
                report["failed"].append((event.event_id, "SPY/^VIX", f"market: {exc}"))

        # ③ 联动结果（drawdown/recovery；显式开启才写，维持既有保守口径）
        if fill_linkage:
            from events_lib.linkage import compute_linkage
            for impact in event.tickers_affected:
                if impact.drawdown is not None:
                    continue
                try:
                    bars = market.get_daily_bars_between(
                        impact.ticker, t0 - timedelta(days=90),
                        t0 + timedelta(days=POST_WINDOW_DAYS))
                    result = compute_linkage(bars, t0)
                    sleep()
                except Exception as exc:
                    report["failed"].append((event.event_id, impact.ticker, f"linkage: {exc}"))
                    continue
                if result:
                    impact.drawdown = result["drawdown"]
                    impact.drawdown_days = result["drawdown_days"]
                    impact.recovery_days = result["recovery_days"]
                    report["linkage_filled"] += 1

        if progress:
            progress(f"[pre-state] {event.event_id} 完成"
                     f"（累计 pre-state {report['pre_state_filled']} 条标的）")
    return report
