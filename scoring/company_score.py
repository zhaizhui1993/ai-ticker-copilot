"""公司面评分（权重 25%，逐 ticker）：成长 40% + 估值 15% + 质量 30% + 技术面 15%。

规格：docs/05-scoring/company-score.md + layered-technicals.md
技术面子项按三层体系实现：伤害度量（回撤/乖离）+ 趋势（MA50）+ 择时（RSI/量比）。
v1.2 修复（P0-1/P1-4）：
- 估值不再用绝对 PE 直接驱动总分：正增长时按类 PEG（PE/营收 YoY）分桶；
  周期段（equipment/foundry）低 PE 视为盈利峰值信号、封顶不加高分；
  PE 缺失或亏损时剔除估值腿（权重重归一化），而不是塞中性 50。
- 任何子腿数据缺失都显式重归一化并在 degraded_note 标注。
"""

from domain import technicals
from domain.scoring import ScoreBreakdown
from domain.stock import DailyBar, Financials

# 子项权重（v1.2：估值 30%→15% 让渡给质量，合计 = 1.0）
WEIGHT_GROWTH = 0.40
WEIGHT_VALUATION = 0.15
WEIGHT_QUALITY = 0.30
WEIGHT_TECH = 0.15

# 周期段：低 PE 常伴盈利峰值（如设备/代工周期顶），估值分封顶不加高分
CYCLICAL_SEGMENTS = {"equipment", "foundry"}
CYCLICAL_VALUATION_CAP = 55.0


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _peg_valuation(pe: float, revenue_yoy: float, cyclical: bool) -> tuple[float, str]:
    """类 PEG（PE / 营收 YoY）分桶；周期段封顶。返回 (分数, 口径标注)。"""
    peg = pe / revenue_yoy
    if peg < 1.5:
        v = 75.0
    elif peg < 2.5:
        v = 60.0
    elif peg < 3.5:
        v = 45.0
    else:
        v = 30.0
    note = f"类 PEG 口径（PE {pe:.0f}/增速 {revenue_yoy:.0f}%={peg:.1f}）"
    if cyclical and v > CYCLICAL_VALUATION_CAP:
        v = CYCLICAL_VALUATION_CAP
        note += "；周期段低 PE 常伴盈利峰值，已封顶"
    return v, note


def _absolute_valuation_capped(pe: float) -> tuple[float, str]:
    """无正增长支撑时的绝对 PE 参考：不给高分（≤55），仅作粗参考。"""
    v = 55.0 if pe < 20 else 50.0 if pe < 35 else 40.0 if pe < 60 else 30.0
    return v, f"绝对 PE 参考口径（PE {pe:.0f}，无正增长支撑不给高分）"


class CompanyScorer:
    name = "company"

    def score(
        self,
        ticker: str,
        bars: list[DailyBar],
        fin: Financials | None = None,
        segment: str | None = None,
    ) -> ScoreBreakdown:
        notes = []
        fin = fin or Financials()
        cyclical = (segment or "").lower() in CYCLICAL_SEGMENTS
        legs: list[tuple[str, float, float]] = []  # (子项名, 分数, 权重)

        # ① 成长 40%
        if fin.revenue_yoy is not None:
            growth = (90 if fin.revenue_yoy >= 30 else 70 if fin.revenue_yoy >= 10
                      else 50 if fin.revenue_yoy >= 0 else 25)
            legs.append(("成长", growth, WEIGHT_GROWTH))
        else:
            notes.append("营收 YoY 缺失（成长腿剔除，权重重归一化）")

        # ② 估值 15%（P0-1：类 PEG + 周期封顶 + 缺失剔除，不直接用绝对 PE 驱动总分）
        if fin.pe_ttm is not None and fin.pe_ttm > 0:
            if fin.revenue_yoy is not None and fin.revenue_yoy > 0:
                valuation, v_note = _peg_valuation(fin.pe_ttm, fin.revenue_yoy, cyclical)
            else:
                valuation, v_note = _absolute_valuation_capped(fin.pe_ttm)
            legs.append(("估值", valuation, WEIGHT_VALUATION))
            notes.append(f"估值口径：{v_note}")
        else:
            notes.append("PE 缺失或亏损（估值腿剔除，权重重归一化；亏损期看成长/质量）")

        # ③ 质量 30%
        quality_parts = []
        if fin.gross_margin is not None:
            quality_parts.append((_clamp(50 + (fin.gross_margin - 40) * 0.5), 0.5))
        if fin.fcf_positive is not None:
            quality_parts.append((80.0 if fin.fcf_positive else 20.0, 0.3))
        if fin.roe is not None:
            quality_parts.append((_clamp(50 + (fin.roe - 15) * 0.3), 0.2))
        if quality_parts:
            quality = sum(v * w for v, w in quality_parts) / sum(w for _, w in quality_parts)
            legs.append(("质量", quality, WEIGHT_QUALITY))
        if len(quality_parts) < 3:
            notes.append("质量证据不完整：缺失项不视为负值，已知子项归一化")

        # ④ 技术面 15%：分层（伤害 25% + 趋势 40% + 择时 35%）
        tech_parts = {}
        if len(bars) >= 60:
            slope = technicals.ma_slope_pct(bars, 50, 10)
            ma50 = technicals.sma(bars, 50)
            trend = 50.0
            if slope is not None:
                trend += max(-30.0, min(30.0, slope * 6))
            if ma50:
                trend += 10 if bars[-1].close >= ma50 else -10
            tech_parts["趋势"] = _clamp(trend)

            rsi = technicals.rsi(bars)
            if rsi is None:
                timing = 50.0
            elif 40 <= rsi <= 50:
                timing = 70.0    # 回踩买区
            elif 50 < rsi <= 65:
                timing = 60.0
            elif rsi > 70:
                timing = 45.0    # 过热不追，但不是看空
            elif 30 <= rsi < 40:
                timing = 55.0
            else:
                timing = 35.0    # 深度超卖（需体制层配合解读）
            tech_parts["择时"] = timing

            drawdown = technicals.drawdown_from_high_pct(bars)
            damage = 60.0
            if drawdown is not None:
                damage = (60 if drawdown > -10 else 50 if drawdown > -25
                          else 40 if drawdown > -40 else 30)
            tech_parts["伤害"] = damage

            tech = round(tech_parts["趋势"] * 0.40 + tech_parts["择时"] * 0.35
                         + tech_parts["伤害"] * 0.25, 1)
            legs.append(("技术面", tech, WEIGHT_TECH))
        else:
            notes.append("K 线数据不足（技术面腿剔除，权重重归一化）")

        if legs:
            w_sum = sum(w for _, _, w in legs)
            total = round(sum(v * w for _, v, w in legs) / w_sum, 1)
            norm = f"，权重重归一化 {w_sum:.0%}" if abs(w_sum - 1.0) > 1e-9 else ""
        else:
            total, norm = 50.0, ""
        tone = "偏多" if total >= 60 else ("偏空" if total <= 40 else "中性")

        indicators = {name: round(v, 1) for name, v, _ in legs}
        indicators["PE"] = fin.pe_ttm
        coverage = sum(x is not None for x in (
            fin.revenue_yoy, fin.pe_ttm, fin.gross_margin, fin.fcf_positive, fin.roe)) / 5
        indicators["data_coverage"] = coverage
        indicators["fundamentals_ready"] = int(all(x is not None for x in (
            fin.revenue_yoy, fin.gross_margin, fin.fcf_positive)))
        indicators.update(tech_parts)
        parts_desc = "、".join(f"{name} {v:.0f}" for name, v, _ in legs)
        return ScoreBreakdown(
            score=total,
            indicators=indicators,
            rationale=f"{ticker}：{parts_desc}{norm}，公司面{tone}。",
            degraded=bool(notes), degraded_note="；".join(notes),
        )
