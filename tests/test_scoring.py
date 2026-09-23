"""P5 验收：各维分数方向/区间、权重生效、分档正确、体制层分级约束与公司面门槛（testing.md §12.4）。"""

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
    if broken:  # 两个指数破位 → 触发分级约束
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


def test_event_category_decay_and_renorm() -> None:
    scorer = EventScorer()
    match = EventMatchResult(event_id="e1", similarity=0.8, direction=-1, magnitude=0.8,
                             affected_tickers=["NVDA"])
    # 分类型衰减：管制类半衰期 45 天 vs 默认 7 天 → 30 天后利空留存差异显著
    slow = scorer.score("NVDA", [(match, 30)], x_sentiment=50.0,
                        category_by_event={"e1": "regulation"})
    fast = scorer.score("NVDA", [(match, 30)], x_sentiment=50.0)
    assert slow.score < fast.score
    assert slow.indicators["半衰期(天)"] == "45"

    # 情绪缺失 → 类比权重重归一化（0.8→1.0）：50 + 类比分×0.5
    no_x = scorer.score("NVDA", [(match, 0)], x_sentiment=None)
    assert abs(no_x.score - (50 + (-64) * 0.5)) < 0.1
    assert "重归一化" in no_x.degraded_note


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


def test_industry_missing_legs_renormalized() -> None:
    scorer = IndustryScorer()
    rising = {s: _bars([100 * (1 + 0.002 * i) for i in range(80)]) for s in ("NVDA", "AMD")}
    spy = _bars([100 * (1 + 0.0002 * i) for i in range(80)])
    # 财报动量与 AI 词频缺失 → 相对强弱占满权重（≈85），而不是被两个中性 50 稀释到 59
    one_leg = scorer.score("gpu", rising, spy_bars=spy)
    assert one_leg.score >= 80
    assert "重归一化" in one_leg.degraded_note


# ---------- 公司面 ----------


def test_event_state_factor() -> None:
    """v1.3 状态缺口调节：当前比历史样本更拥挤 → 冲击放大（clamp ×0.5~×1.5）。"""
    scorer = EventScorer()
    crowded = EventMatchResult(event_id="e1", similarity=0.8, direction=-1, magnitude=0.8,
                               affected_tickers=["NVDA"], pre_bias_ma200=20.0)
    # 历史样本乖离 +20% vs 当前 +80% → 缺口 60pt → 因子 1.3 → 利空更深
    hot = scorer.score("NVDA", [(crowded, 0)], x_sentiment=50.0,
                       current_state={"bias_ma200": 80.0, "drawdown_52w": -1.0})
    cool = scorer.score("NVDA", [(crowded, 0)], x_sentiment=50.0,
                        current_state={"bias_ma200": 20.0, "drawdown_52w": -1.0})
    assert hot.score < cool.score < 50
    assert "状态调节" in hot.indicators and "状态调节" in hot.rationale
    assert cool.indicators.get("状态调节") is None       # 状态可比 → 不调节

    # 极端拥挤被 clamp 在 1.5；状态缺失（无 current/pre）不调节
    extreme = scorer.score("NVDA", [(crowded, 0)], x_sentiment=50.0,
                           current_state={"bias_ma200": 300.0})
    no_state = scorer.score("NVDA", [(crowded, 0)], x_sentiment=50.0)
    assert extreme.score < hot.score                       # 放大有上限但仍随拥挤加深
    assert abs(no_state.score - 24.4) < 0.1                # 无状态 = 原公式（24.4 基准）


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


# ---------- 汇总与体制层分级约束 ----------


def _four(m: float, e: float, i: float, c: float) -> FourDimScores:
    def sb(s: float) -> ScoreBreakdown:
        return ScoreBreakdown(score=s, rationale="")
    return FourDimScores(macro=sb(m), event=sb(e), industry=sb(i), company=sb(c))


def test_company_valuation_peg_and_cyclical_cap() -> None:
    scorer = CompanyScorer()
    flat = _bars([100.0] * 120)

    # 超成长：PE 60 / 增速 60 → 类 PEG=1.0 → 估值不再因绝对 PE 高而给低分
    hyper = scorer.score("NVDA", flat, Financials(revenue_yoy=60, pe_ttm=60), segment="gpu")
    assert hyper.indicators["估值"] >= 70
    assert "类 PEG" in hyper.degraded_note

    # 周期段低 PE（盈利峰值特征）：估值分封顶不加高分
    cyc = scorer.score("AMAT", flat, Financials(revenue_yoy=12, pe_ttm=11), segment="equipment")
    assert cyc.indicators["估值"] <= 55
    assert "封顶" in cyc.degraded_note

    # 亏损/PE 缺失：估值腿剔除（重归一化），而不是塞中性 50
    loss = scorer.score("XYZ", flat, Financials(revenue_yoy=80))
    assert "估值腿剔除" in loss.degraded_note


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
    # 破位环境：档位封顶"中性偏多"+ 仓位上限系数 0.3（信号=观望偏加仓·小仓）
    gated = engine.run(_four(80, 80, 80, 80), _regime(broken=True))
    assert gated.regime_gate_applied is True
    assert gated.band == "中性偏多"                     # 档位被压制（不再一刀切观望）
    assert gated.position_cap == 0.3                    # 仓位调节系数输出
    assert "体制层" in gated.regime_note
    assert "观望" in gated.regime_note
    assert "0.3" in gated.regime_note

    # 防御档不受门控影响（本就低于上限）
    defensive = engine.run(_four(10, 10, 10, 10), _regime(broken=True))
    assert defensive.band == "防御"

    # 公司面短板门槛：其他三维强势把总分平均进"积极"（75），公司分 30 → 档位封顶
    weak_company = engine.run(_four(90, 90, 90, 30), _regime(broken=False))
    assert weak_company.weighted_total == 75.0
    assert weak_company.company_gate_applied is True
    assert weak_company.band == "中性偏多"
    assert weak_company.position_cap == 1.0             # 非破位环境不降仓位系数

    # 正常环境：无任何门槛触发
    normal = engine.run(_four(80, 80, 80, 80), _regime(broken=False))
    assert normal.band == "积极" and normal.position_cap == 1.0
    assert normal.company_gate_applied is False

    try:
        Engine({"macro": 0.3, "event": 0.3, "industry": 0.2, "company": 0.1})  # 0.9
        raise AssertionError("权重合计≠1 应拒绝")
    except ValueError:
        pass
