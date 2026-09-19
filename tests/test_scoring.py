"""P5 验收：各维分数方向/区间、权重生效、分档正确、体制层硬约束（testing.md §12.4）。"""

from datetime import date, timedelta

from domain.events import EventMatchResult
from domain.scoring import (
    FourDimScores,
    IndexLevel,
    IndexRegime,
    MacroPoint,
    ScoreBreakdown,
)
from domain.stock import DailyBar, Financials
from scoring.company_score import CompanyScorer
from scoring.engine import Engine, band_of
from scoring.event_score import EventScorer
from scoring.industry_score import IndustryScorer
from scoring.macro_score import MacroScorer


def _bars(closes: list[float]) -> list[DailyBar]:
    day = date(2026, 1, 1)
    bars = []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(date=day, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6))
        day += timedelta(days=1)
    return bars


def _regime(broken: bool) -> IndexRegime:
    if broken:  # 两个指数破位 → 触发硬约束
        return IndexRegime(indexes=[
            IndexLevel(symbol="^GSPC", close=100, ma200=110),
            IndexLevel(symbol="^NDX", close=100, ma200=110),
            IndexLevel(symbol="^SOX", close=120, ma200=110),
        ], vix=18.0)
    return IndexRegime(indexes=[
        IndexLevel(symbol="^GSPC", close=7316, ma200=7050),
        IndexLevel(symbol="^NDX", close=27192, ma200=26480),
        IndexLevel(symbol="^SOX", close=10447, ma200=9190),
    ], vix=20.7)


# ---------- 宏观 ----------


def test_macro_direction_and_range() -> None:
    bullish = {
        "FEDFUNDS": MacroPoint(series_id="FEDFUNDS", as_of="2026-09-01", value=4.0, prev_value=4.5),
        "DGS10": MacroPoint(series_id="DGS10", as_of="2026-09-01", value=4.0, prev_value=4.2),
        "T10Y2Y": MacroPoint(series_id="T10Y2Y", as_of="2026-09-01", value=0.2, prev_value=0.1),
        "CPIAUCSL": MacroPoint(series_id="CPIAUCSL", as_of="2026-09-01", value=320.0, prev_value=319.8),
        "UNRATE": MacroPoint(series_id="UNRATE", as_of="2026-09-01", value=4.2, prev_value=4.2),
    }
    bearish = {
        "FEDFUNDS": MacroPoint(series_id="FEDFUNDS", as_of="2026-09-01", value=5.5, prev_value=5.0),
        "DGS10": MacroPoint(series_id="DGS10", as_of="2026-09-01", value=4.8, prev_value=4.2),
        "T10Y2Y": MacroPoint(series_id="T10Y2Y", as_of="2026-09-01", value=-0.5, prev_value=-0.2),
        "CPIAUCSL": MacroPoint(series_id="CPIAUCSL", as_of="2026-09-01", value=330.0, prev_value=328.0),
        "UNRATE": MacroPoint(series_id="UNRATE", as_of="2026-09-01", value=5.0, prev_value=4.2),
    }
    scorer = MacroScorer()
    bull = scorer.score(bullish, vix=13.0)
    bear = scorer.score(bearish, vix=28.0)
    assert bull.score > bear.score                     # 方向正确
    assert bull.score > 60 and bear.score < 40
    assert 0 <= bull.score <= 100

    degraded = scorer.score({}, vix=None)              # 全缺失 → 中性 + 标注
    assert degraded.degraded and "缺失" in degraded.degraded_note
    assert 40 <= degraded.score <= 60


# ---------- 事件面 ----------


def test_event_score_formula_and_freshness() -> None:
    scorer = EventScorer()
    match = EventMatchResult(event_id="e1", similarity=0.8, direction=-1, magnitude=0.8,
                             affected_tickers=["NVDA"])
    fresh = scorer.score("NVDA", [(match, 0)], x_sentiment=50.0)
    # 类比分 = -1*0.8*0.8*1.0*1.0*100 = -64 → 50 - 64*0.4 = 24.4
    assert abs(fresh.score - 24.4) < 0.1

    stale = scorer.score("NVDA", [(match, 14)], x_sentiment=50.0)  # 两周：衰减 1/4
    assert stale.score > fresh.score                  # 时间衰减让利空变淡

    non_listed = scorer.score("AMD", [(match, 0)], x_sentiment=50.0)
    assert non_listed.score > fresh.score             # 未列出标的 0.5 折扣

    no_x = scorer.score("NVDA", [(match, 0)], x_sentiment=None)
    assert no_x.degraded and "X 数据缺失" in no_x.degraded_note

    none_hit = scorer.score("NVDA", [], x_sentiment=60.0)
    assert 40 <= none_hit.score <= 60                 # 无命中 → 中性


# ---------- 产业面 ----------


def test_industry_basket_and_neutral_degrade() -> None:
    scorer = IndustryScorer()
    rising = {s: _bars([100 * (1 + 0.002 * i) for i in range(80)]) for s in ("NVDA", "AMD")}
    spy = _bars([100 * (1 + 0.0002 * i) for i in range(80)])
    strong = scorer.score("gpu", rising, spy_bars=spy,
                          financials={"NVDA": Financials(revenue_yoy=50.0)}, ai_word_delta=0.2)
    assert strong.score >= 60

    other = scorer.score("other", rising, spy_bars=spy)   # 无篮子映射 → 降级标注
    assert other.degraded and "无篮子映射" in other.degraded_note
    assert 30 <= other.score <= 70


# ---------- 公司面 ----------


def test_company_growth_quality_direction() -> None:
    scorer = CompanyScorer()
    uptrend = _bars([100 * (1 + 0.002 * i) for i in range(120)])
    strong = scorer.score("NVDA", uptrend,
                          Financials(revenue_yoy=60, gross_margin=72, fcf_positive=True,
                                     roe=90, pe_ttm=30))
    downtrend = _bars([100 * (1 - 0.002 * i) for i in range(120)])
    weak = scorer.score("XYZ", downtrend,
                        Financials(revenue_yoy=-10, gross_margin=20, fcf_positive=False,
                                   roe=2, pe_ttm=90))
    assert strong.score > weak.score
    assert strong.score > 60 and weak.score < 45
    # RSI 回踩买区（涨后横盘回撤）不给卖出分
    pullback = _bars([100 * (1 + 0.003 * i) for i in range(100)] + [130, 128, 126, 125, 124])
    pr = scorer.score("NVDA", pullback, Financials(revenue_yoy=40))
    assert pr.indicators["择时"] >= 55


# ---------- 汇总与体制层硬约束 ----------


def _four(m: float, e: float, i: float, c: float) -> FourDimScores:
    def sb(s: float) -> ScoreBreakdown:
        return ScoreBreakdown(score=s, rationale="")
    return FourDimScores(macro=sb(m), event=sb(e), industry=sb(i), company=sb(c))


def test_engine_weights_and_bands() -> None:
    engine = Engine()                                  # 默认 0.25×4
    output = engine.run(_four(80, 80, 80, 80), _regime(broken=False))
    assert output.weighted_total == 80.0
    assert output.band == "积极"
    assert output.regime_gate_applied is False

    assert band_of(75) == "积极" and band_of(55) == "中性偏多"
    assert band_of(40) == "中性偏空" and band_of(20) == "防御"

    heavy = Engine({"macro": 0.4, "event": 0.4, "industry": 0.1, "company": 0.1})
    out1 = engine.run(_four(80, 80, 40, 40), _regime(broken=False))   # 默认等权 → 60
    out2 = heavy.run(_four(80, 80, 40, 40), _regime(broken=False))    # 重仓高分维度 → 72
    assert out2.weighted_total > out1.weighted_total   # 权重生效


def test_regime_hard_gate() -> None:
    engine = Engine()
    # 破位环境：积极/偏多被压至"观望偏加仓"上限以下（上限=观望）
    gated = engine.run(_four(80, 80, 80, 80), _regime(broken=True))
    assert gated.regime_gate_applied is True
    assert gated.band != "积极"                        # 档位被压制
    assert "体制层硬约束" in gated.regime_note
    assert "观望" in gated.regime_note

    # 防御档不受门控影响（本就低于上限）
    defensive = engine.run(_four(10, 10, 10, 10), _regime(broken=True))
    assert defensive.band == "防御"

    try:
        Engine({"macro": 0.3, "event": 0.3, "industry": 0.2, "company": 0.1})  # 0.9
        raise AssertionError("权重合计≠1 应拒绝")
    except ValueError:
        pass
