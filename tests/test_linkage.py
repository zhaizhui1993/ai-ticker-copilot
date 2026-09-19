"""联动层回填算法测试（合成数据已知值，docs/04-events/initialization.md ②口径）。

构造方式：_make(pre, post, t0) 保证 t0（工作日）恰好在 bars[len(pre)]，
避免周末对齐偏移干扰断言。
"""

from datetime import date, timedelta

from domain.stock import DailyBar
from events_lib.linkage import compute_linkage, compute_market_metrics

T0 = date(2025, 3, 3)  # 周一


def _bar(d: date, close: float) -> DailyBar:
    return DailyBar(date=d, open=close, high=close, low=close, close=close, volume=1e6)


def _make(pre_closes: list[float], post_closes: list[float], t0: date = T0) -> list[DailyBar]:
    """pre 严格位于 t0 之前（工作日倒排），post 从 t0 当天起（工作日顺排）。"""
    dates_pre: list[date] = []
    d = t0 - timedelta(days=1)
    while len(dates_pre) < len(pre_closes):
        if d.weekday() < 5:
            dates_pre.append(d)
        d -= timedelta(days=1)
    bars = [_bar(dt, c) for dt, c in zip(reversed(dates_pre), pre_closes)]

    dates_post: list[date] = []
    d = t0
    while len(dates_post) < len(post_closes):
        if d.weekday() < 5:
            dates_post.append(d)
        d += timedelta(days=1)
    bars += [_bar(dt, c) for dt, c in zip(dates_post, post_closes)]
    return bars


def test_t0_alignment() -> None:
    bars = _make([100.0] * 35, [90.0] * 5)
    assert bars[35].date == T0  # T0 恰为 post 首根


def test_drawdown_trough_and_recovery() -> None:
    # T0 前横盘 100；T0 后先横 10 天，再跌到 80 横 20 天，随后收复
    bars = _make([100.0] * 35, [100.0] * 10 + [80.0] * 20 + [100.0, 105.0])
    result = compute_linkage(bars, T0)
    assert result is not None
    assert result["peak"] == 100.0
    assert abs(result["drawdown"] - (-20.0)) < 1e-6
    assert result["drawdown_days"] == 10        # T0 → 最低点（第 10 个交易日触及 80）
    assert result["recovery_days"] == 20        # 最低点 → 收复前高


def test_no_recovery_within_window() -> None:
    bars = _make([100.0] * 35, [80.0] * 200)    # 跌破后窗口内永不收复
    result = compute_linkage(bars, T0)
    assert result is not None
    assert result["recovery_days"] is None


def test_deepseek_like_single_day_crash() -> None:
    # T0 当天闪崩 -17%，两个交易日后收复（DeepSeek 冲击 NVDA 原型）
    bars = _make([100.0] * 35, [83.0, 95.0, 101.0] + [102.0] * 30)
    result = compute_linkage(bars, T0)
    assert abs(result["drawdown"] - (-17.0)) < 1e-6
    assert result["drawdown_days"] == 0         # T0 当天即最低
    assert result["recovery_days"] == 2         # 两个交易日收复


def test_market_metrics() -> None:
    spy = _make([100.0] * 35, [99.0, 98.0, 99.5, 100.0, 101.0, 101.5] + [103.0] * 20)
    vix = _make([15.0] * 35, [25.0, 30.0, 22.0] + [18.0] * 25)
    metrics = compute_market_metrics(spy, vix, T0)
    # 1 周（5 个交易日）：99.0 → 101.5 = +2.53%
    assert abs(metrics["sp500_1w"] - 2.53) < 0.01
    assert metrics["sp500_1m"] is not None
    assert metrics["vix_peak"] == 30.0          # 窗口内 VIX 峰值


def test_missing_t0_returns_none() -> None:
    bars = _make([100.0] * 10, [100.0] * 10, t0=date(2024, 6, 3))
    assert compute_linkage(bars, date(2026, 1, 1)) is None  # T0 在数据之后
