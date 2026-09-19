"""技术指标纯函数库（无 IO、同输入同输出）。

放 domain 层的原因：契约 §10.2① 规定"采集层只返原始 OHLCV，指标由消费方自算"，
而消费方横跨 03（IndexRegime 组装）、05（评分）、scripts（CLI 验证）——
放在最底层 domain 可被三方共用且不破坏"依赖单向向下"。

指标口径：docs/05-scoring/layered-technicals.md
- 伤害度量主指标 = 距 52 周高点回撤 + 乖离率（MA200 破位仅作确认）
- RSI14：强势趋势中 70+ 可持续，"超买即卖"失效；回踩买区 40~50
- ATR14：仓位尺度 + 恐慌见底识别（骤增 2 倍 + 双向巨震 + 天量）
"""

from domain.stock import DailyBar


def sma(bars: list[DailyBar], n: int) -> float | None:
    """最近 n 日收盘简单均线；数据不足返回 None。"""
    if len(bars) < n:
        return None
    return sum(b.close for b in bars[-n:]) / n


def ma_slope_pct(bars: list[DailyBar], n: int = 50, lookback: int = 10) -> float | None:
    """均线斜率：MA(n,今日) 相对 MA(n, lookback 日前) 的变化 %。"""
    if len(bars) < n + lookback:
        return None
    now = sma(bars[-n:], n)  # 与 sma(bars,n) 等价，显式切片便于对照
    past = sma(bars[: len(bars) - lookback], n)
    if past in (None, 0):
        return None
    return (now / past - 1) * 100


def rsi(bars: list[DailyBar], n: int = 14) -> float | None:
    """RSI（简单平均版）。全涨=100，全跌=0；数据不足返回 None。"""
    if len(bars) < n + 1:
        return None
    gains = losses = 0.0
    for prev, cur in zip(bars[-n - 1 : -1], bars[-n:]):
        change = cur.close - prev.close
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def atr_pct(bars: list[DailyBar], n: int = 14) -> float | None:
    """平均真实波幅 ATR(n)，以最新收盘归一为百分比。"""
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-n - 1 : -1], bars[-n:]):
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    return (sum(trs) / n) / bars[-1].close * 100


def volume_ratio(bars: list[DailyBar], n: int = 20) -> float | None:
    """量比：最新成交量 / 最近 n 日均量。"""
    if len(bars) < n + 1 or bars[-1].volume == 0:
        return None
    avg = sum(b.volume for b in bars[-n - 1 : -1]) / n
    if avg == 0:
        return None
    return bars[-1].volume / avg


def drawdown_from_high_pct(bars: list[DailyBar], lookback: int = 252) -> float | None:
    """距区间高点回撤 %（≤0）。用收盘高点，52 周约 252 个交易日。"""
    window = bars[-lookback:]
    if not window:
        return None
    high = max(b.close for b in window)
    if high == 0:
        return None
    return (window[-1].close / high - 1) * 100


def bias_vs_ma200_pct(bars: list[DailyBar]) -> float | None:
    """乖离率：现价相对 MA200 偏离 %（伤害度量主指标之一）。"""
    ma = sma(bars, 200)
    if ma in (None, 0):
        return None
    return (bars[-1].close / ma - 1) * 100


def closed_below_ma200(bars: list[DailyBar]) -> bool | None:
    """收盘是否跌破 MA200（仅作确认，不作伤害度量）。数据不足返回 None。"""
    ma = sma(bars, 200)
    if ma is None:
        return None
    return bars[-1].close < ma
