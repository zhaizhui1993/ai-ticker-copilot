"""技术指标纯函数测试（docs/05-scoring/layered-technicals.md 口径）。"""

from datetime import date, timedelta

from domain.stock import DailyBar
from domain import technicals


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[DailyBar]:
    volumes = volumes or [1_000_000.0] * len(closes)
    return [
        DailyBar(date=date(2026, 1, 1) + timedelta(days=i),
                 open=c, high=c * 1.01, low=c * 0.99, close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def test_sma() -> None:
    bars = _bars([10, 20, 30, 40, 50])
    assert technicals.sma(bars, 5) == 30.0
    assert technicals.sma(bars, 6) is None  # 数据不足


def test_rsi_extremes() -> None:
    up = _bars([float(i) for i in range(1, 25)])          # 连涨
    assert technicals.rsi(up) == 100.0
    down = _bars([float(25 - i) for i in range(1, 25)])   # 连跌
    assert technicals.rsi(down) == 0.0
    assert technicals.rsi(_bars([1.0, 2.0]), 14) is None   # 数据不足


def test_rsi_midrange() -> None:
    # 涨跌各半：gains=losses → RSI=50
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
    assert abs(technicals.rsi(_bars(closes)) - 50.0) < 1e-9


def test_atr_pct_positive() -> None:
    bars = _bars([100.0] * 20)
    atr = technicals.atr_pct(bars)
    assert atr is not None and atr > 0  # high-low = 100*1.01-100*0.99 ≈ 2 → ~2%


def test_drawdown_and_bias() -> None:
    closes = [100.0] * 250 + [80.0]
    bars = _bars(closes)
    dd = technicals.drawdown_from_high_pct(bars)
    assert dd is not None and abs(dd - (-20.0)) < 1e-6     # 距高点 -20%
    bias = technicals.bias_vs_ma200_pct(bars)
    assert bias is not None and bias < -15                  # 明显低于 MA200
    assert technicals.closed_below_ma200(bars) is True      # 破位确认


def test_ma_slope() -> None:
    rising = _bars([float(100 + i) for i in range(70)])     # 匀速上行
    slope = technicals.ma_slope_pct(rising, n=50, lookback=10)
    assert slope is not None and slope > 0
    falling = _bars([float(170 - i) for i in range(70)])
    slope2 = technicals.ma_slope_pct(falling, n=50, lookback=10)
    assert slope2 is not None and slope2 < 0


def test_volume_ratio() -> None:
    bars = _bars([100.0] * 25, volumes=[1_000_000.0] * 24 + [3_000_000.0])
    vr = technicals.volume_ratio(bars)
    assert vr is not None and abs(vr - 3.0) < 1e-6          # 3 倍均量
