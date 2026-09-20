"""价格回调挖掘器（纯函数）：从日线序列自动检出回调波段。

用途（docs/04-events 种子库增长路线④）：从指数/个股日线挖出
peak→trough≥阈值 的回调波段，产出日期/幅度/达底/恢复天数，
作为历史事件库的量化骨架；事件归因（名称/机制）由人工或 LLM 补。

口径与 events_lib/linkage.py 一致：交易日计数、close 基准。
"""

from domain.stock import DailyBar


def detect_pullbacks(
    bars: list[DailyBar],
    min_dd_pct: float = 5.0,
    rebound_pct: float = 3.0,
) -> list[dict]:
    """检出全部"距滚动高点回撤 ≥ min_dd_pct"的回调波段。

    算法（zigzag 变体）：
    - 维护滚动峰值 peak；价格创新高则更新；
    - 自 peak 的回撤达到 min_dd_pct 时进入"回调中"，记录最低点 trough；
    - 自 trough 反弹 ≥ rebound_pct 或收复 peak，回调确认结束；
      输出波段（峰/谷日期价格、回撤%、达底与恢复交易日数）；
    - 未收复 peak 的开放波段也输出（recovery_days=None）。
    """
    if len(bars) < 3:
        return []

    episodes: list[dict] = []
    peak_idx, peak = 0, bars[0].close
    trough_idx, trough = 0, bars[0].close
    active = False

    def close_episode(end_idx: int) -> None:
        dd = (trough / peak - 1) * 100
        if dd <= -min_dd_pct:
            # 恢复：谷底之后首个收复峰值之日（若在 end_idx 内）
            recovery_days = None
            for j in range(trough_idx, len(bars)):
                if bars[j].close >= peak:
                    recovery_days = j - trough_idx
                    break
            episodes.append({
                "peak_date": bars[peak_idx].date,
                "peak": round(peak, 2),
                "trough_date": bars[trough_idx].date,
                "trough": round(trough, 2),
                "drawdown_pct": round(dd, 2),
                "days_down": trough_idx - peak_idx,       # 峰 → 谷交易日数
                "recovery_days": recovery_days,           # 谷 → 收复峰；None=尚未
            })

    for i, bar in enumerate(bars[1:], start=1):
        close = bar.close
        if not active:
            if close > peak:
                peak, peak_idx = close, i
                trough, trough_idx = close, i
            elif close < trough:
                trough, trough_idx = close, i
                if (trough / peak - 1) * 100 <= -min_dd_pct:
                    active = True  # 进入回调
        else:
            if close < trough:
                trough, trough_idx = close, i  # 回调加深，谷继续下移
            elif close >= peak:
                close_episode(i)               # 直接收复峰值，回调结束
                peak, peak_idx = close, i
                trough, trough_idx = close, i
                active = False
            elif close >= trough * (1 + rebound_pct / 100):
                close_episode(i)               # 显著反弹，波段确认结束
                # 峰值维持（未创新高则继续以旧峰为参照）
                trough, trough_idx = close, i
                active = False

    if active:  # 收尾的开放波段（进行中回调）
        close_episode(len(bars) - 1)
    return episodes
