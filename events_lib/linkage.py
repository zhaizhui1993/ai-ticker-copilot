"""联动层回填算法（纯函数，可独立于数据源测试）。

规格：docs/04-events/initialization.md ②（scripts/backfill_events.py 的核心算法）
窗口：T0 前 30 个交易日 ~ T0 后 180 个交易日
- 前高 = T0 前 30 日收盘高点与 T0 收盘取 max
- drawdown = 窗口内 max(1 − close/前高)（以负百分比记录）
- drawdown_days = T0 → 窗口内最低点的交易日数
- recovery_days = 最低点 → 重新站上前高的交易日数；窗口内未收复记 None
- market.sp500_1w / 1m = SPY 在 T0 后 5 / 21 个交易日涨跌 %
- market.vix_peak = 窗口内 ^VIX 最高值
"""

from datetime import date

from domain.stock import DailyBar

PRE_WINDOW = 30       # T0 前观察（定前高）
POST_WINDOW = 180     # T0 后观察（回撤/恢复）


def _index_of(bars: list[DailyBar], t0: date) -> int | None:
    """T0 对齐到首个 >= t0 的交易日；找不到返回 None。"""
    for i, bar in enumerate(bars):
        if bar.date >= t0:
            return i
    return None


def compute_linkage(bars: list[DailyBar], t0: date) -> dict | None:
    """单标的联动量化：回撤/达底/恢复。数据不足返回 None。"""
    i = _index_of(bars, t0)
    if i is None:
        return None
    window_start = max(0, i - PRE_WINDOW)
    window = bars[window_start: i + 1 + POST_WINDOW]
    if len(window) < 5:
        return None

    peak = max(b.close for b in window[: i - window_start + 1])  # 前高（含 T0 收盘）
    post = window[i - window_start:]                              # T0 起（T0 位于 window[PRE_WINDOW]）
    if not post or peak <= 0:
        return None

    closes = [b.close for b in post]
    trough_offset = min(range(len(closes)), key=lambda j: closes[j])
    drawdown = (closes[trough_offset] / peak - 1) * 100

    recovery_days = None
    for j in range(trough_offset + 1, len(closes)):
        if closes[j] >= peak:
            recovery_days = j - trough_offset
            break

    return {
        "t0": post[0].date,
        "peak": round(peak, 2),
        "drawdown": round(drawdown, 2),          # 负百分比
        "drawdown_days": trough_offset,          # T0 → 最低点的交易日数
        "recovery_days": recovery_days,          # None = 窗口内未收复
    }


def compute_market_metrics(
    spy_bars: list[DailyBar],
    vix_bars: list[DailyBar],
    t0: date,
) -> dict:
    """市场级指标：SPX 代理（SPY）1周/1月涨跌 + VIX 窗口峰值。缺失字段为 None。"""
    result: dict = {"sp500_1w": None, "sp500_1m": None, "vix_peak": None}

    i = _index_of(spy_bars, t0)
    if i is not None and i < len(spy_bars) - 1:
        base = spy_bars[i].close
        if i + 5 < len(spy_bars):
            result["sp500_1w"] = round((spy_bars[i + 5].close / base - 1) * 100, 2)
        if i + 21 < len(spy_bars):
            result["sp500_1m"] = round((spy_bars[i + 21].close / base - 1) * 100, 2)

    j = _index_of(vix_bars, t0)
    if j is not None:
        window = [b.close for b in vix_bars[j: j + 1 + POST_WINDOW]]
        if window:
            result["vix_peak"] = round(max(window), 2)

    return result
