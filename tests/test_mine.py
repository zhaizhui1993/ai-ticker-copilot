"""回调挖掘器测试（合成序列已知值）。"""

from datetime import date, timedelta

from domain.stock import DailyBar
from events_lib.mine import detect_pullbacks


def _bars(closes: list[float], start: date = date(2024, 1, 1)) -> list[DailyBar]:
    day, bars = start, []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(date=day, open=c, high=c, low=c, close=c, volume=1e6))
        day += timedelta(days=1)
    return bars


def test_detects_full_episode_with_recovery() -> None:
    # 涨到 100 → 3 天跌到 90（-10%）→ 反弹 5% 确认 → 收复 100
    bars = _bars([80, 90, 100] + [100, 95, 90] + [94] + [97, 100, 105])
    eps = detect_pullbacks(bars, min_dd_pct=5.0, rebound_pct=3.0)
    assert len(eps) == 1
    ep = eps[0]
    assert ep["drawdown_pct"] == -10.0
    assert ep["days_down"] == 3
    assert ep["recovery_days"] == 3          # 90 → 94 → 97 → 100：谷后第 3 根收复


def test_open_episode_without_recovery() -> None:
    bars = _bars([100] + [95, 90, 88, 89, 90])  # 跌破后横盘未收复
    eps = detect_pullbacks(bars, min_dd_pct=5.0, rebound_pct=3.0)
    assert len(eps) == 1
    assert eps[0]["drawdown_pct"] == -12.0
    assert eps[0]["recovery_days"] is None     # 开放波段


def test_below_threshold_ignored() -> None:
    bars = _bars([100, 98, 97, 98, 100, 101])  # -3% 抖动
    assert detect_pullbacks(bars, min_dd_pct=5.0) == []


def test_deepening_trough_updates() -> None:
    bars = _bars([100, 96, 92, 91, 94, 99, 101])  # 谷在 91 而非 96
    eps = detect_pullbacks(bars, min_dd_pct=5.0, rebound_pct=3.0)
    assert eps[0]["drawdown_pct"] == -9.0
    assert eps[0]["days_down"] == 3


def test_two_separate_episodes() -> None:
    closes = ([100, 101, 102] + [92, 94, 98, 102, 104]     # 第一次：-10% 后收复创新高
              + [105, 106] + [97, 99, 103, 106])            # 第二次：约 -8.5% 后收复
    eps = detect_pullbacks(_bars(closes), min_dd_pct=5.0, rebound_pct=3.0)
    assert len(eps) == 2
    assert eps[0]["drawdown_pct"] == -9.8    # 峰 102 → 谷 92
    assert eps[1]["drawdown_pct"] == -8.49  # 峰 106 → 谷 97
