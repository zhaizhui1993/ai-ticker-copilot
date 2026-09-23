"""评测模块验收（P0-3 演进）：基准对照、超额计算、偏离分类、校准分箱、追加式存档。

全部用合成行情（FakeMarket），不依赖 DB/网络——DB 路径由 mock 冒烟覆盖。
"""

from datetime import date, datetime, timedelta

from analyzer import evaluation
from domain.stock import DailyBar


def _bars(closes: list[float], low_ratio: float = 1.0,
          start: date = date(2026, 1, 5)) -> list[DailyBar]:
    day, bars = start, []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(date=day, open=c, high=c * 1.01,
                             low=c * low_ratio, close=c, volume=1e6))
        day += timedelta(days=1)
    return bars


class FakeMarket:
    def __init__(self, bars_by_symbol: dict[str, list[DailyBar]]):
        self._bars = bars_by_symbol

    def get_daily_bars_between(self, symbol, start, end):
        return self._bars[symbol]


def _two_ticker_setup() -> tuple[list[dict], FakeMarket, dict[str, list[DailyBar]]]:
    """A 每日 +0.1%、B 每日 -0.1%（近似对称，基准≈0），供超额口径断言。"""
    n = 75  # 信号在第 11 根（i=10），需 i+60 < n
    up = _bars([100 * (1 + 0.001 * i) for i in range(n)], low_ratio=0.98)
    down = _bars([100 * (1 - 0.001 * i) for i in range(n)])
    d0 = up[10].date
    records = [
        {"ticker": "UP", "date": d0, "action": "accumulate", "band": "积极",
         "confidence": 0.55, "close": up[10].close, "regime_gate": False, "source": "rule"},
        {"ticker": "DN", "date": d0, "action": "watch", "band": "积极",
         "confidence": 0.70, "close": down[10].close, "regime_gate": False, "source": "llm"},
    ]
    bars = {"UP": up, "DN": down}
    return records, FakeMarket(bars), bars


def test_benchmark_and_excess_math() -> None:
    records, market, bars = _two_ticker_setup()
    missed = evaluation.attach_forward_returns(records, market)
    assert missed == 0
    up, dn = records
    i = 10  # 信号日 = 第 11 根 K 线
    exp_up = (bars["UP"][i + 5].close / bars["UP"][i].close - 1) * 100
    exp_dn = (bars["DN"][i + 5].close / bars["DN"][i].close - 1) * 100
    exp_bench = (exp_up + exp_dn) / 2
    # 前瞻收益、等权基准、超额均按行情口径精确计算
    assert abs(up["fwd_5d"] - exp_up) < 1e-9
    assert abs(up["bench_5d"] - exp_bench) < 1e-9
    assert abs(up["excess_5d"] - (exp_up - exp_bench)) < 1e-9
    assert abs(dn["excess_5d"] - (exp_dn - exp_bench)) < 1e-9
    assert up["fwd_5d"] > 0 > dn["fwd_5d"]
    assert abs(exp_bench) < 0.05                       # 近似对称行情 → 基准接近 0
    # MAE：UP 低点 0.98×次日收盘 ≈ -1.9%
    assert -2.5 < up["mae_20d"] < -1.5
    # 60 日窗口内可算，且不越界崩溃
    assert up["fwd_60d"] is not None and dn["fwd_60d"] is not None


def test_deviation_classification_and_report() -> None:
    records, market, _ = _two_ticker_setup()
    evaluation.attach_forward_returns(records, market)
    assert evaluation.deviation_tag(records[0]) == "compliant"
    assert evaluation.deviation_tag(records[1]) == "accumulate->watch"
    assert evaluation.deviation_tag({"band": None, "action": "watch"}) is None

    text = evaluation.report_deviation(records)
    assert "偏离 1" in text and "遵守 1" in text
    assert "accumulate->watch" in text and "下偏" in text
    # 破位日仍 accumulate → 体制封顶违背计数
    records[0]["regime_gate"] = True
    assert "体制封顶违背" in evaluation.report_deviation(records)
    assert "1 条" in evaluation.report_deviation(records)


def test_calibration_bins_and_report() -> None:
    assert evaluation._confidence_bin(0.49) == 0
    assert evaluation._confidence_bin(0.50) == 1   # 左闭右开
    assert evaluation._confidence_bin(0.59) == 1
    assert evaluation._confidence_bin(0.60) == 2
    assert evaluation._confidence_bin(0.70) == 3

    records, market, _ = _two_ticker_setup()
    evaluation.attach_forward_returns(records, market)
    text = evaluation.report_calibration(records, "all")
    assert "[0.5, 0.6)" in text and "[0.7" in text and "校准差" in text
    llm_only = evaluation.report_calibration(records, "llm")
    assert "仅 LLM" in llm_only and "0 条" not in llm_only


def test_signals_report_renders_groups() -> None:
    records, market, _ = _two_ticker_setup()
    evaluation.attach_forward_returns(records, market)
    text = evaluation.report_signals(records)
    assert "accumulate" in text and "跑赢基准" in text and "20d基准" in text


def test_archive_report_append_only(tmp_path) -> None:
    out = tmp_path / "eval"
    p1 = evaluation.archive_report("# 第一轮报告", out_dir=str(out))
    assert p1.exists() and "第一轮" in p1.read_text(encoding="utf-8")
    p2 = evaluation.archive_report("# 第二轮报告（追加）", out_dir=str(out))
    assert p1 == p2                                   # 同月同一文件
    content = p2.read_text(encoding="utf-8")
    assert "第一轮" in content and "第二轮" in content  # 追加而非覆盖
    assert content.index("第一轮") < content.index("第二轮")
    assert p2.name.startswith("monthly-") and str(datetime.now().year) in p2.name


def test_regime_whipsaw_flat_market() -> None:
    bars = _bars([100.0] * 250)                       # 恒平 → 无破位段
    text = evaluation.regime_whipsaw(FakeMarket({"^SOX": bars}), "^SOX", years=1)
    assert "无破位段" in text
