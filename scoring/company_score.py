"""公司面评分（权重 25%，逐 ticker）：成长 35% + 估值 30% + 质量 20% + 技术面 15%。

规格：docs/05-scoring/company-score.md + layered-technicals.md
技术面子项按三层体系实现：伤害度量（回撤/乖离）+ 趋势（MA50）+ 择时（RSI/量比）。
估值：PE 5 年分位数据不足时以绝对 PE 粗分并标注（docs 已允许降级近似）。
"""

from domain import technicals
from domain.scoring import ScoreBreakdown
from domain.stock import DailyBar, Financials


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


class CompanyScorer:
    name = "company"

    def score(
        self,
        ticker: str,
        bars: list[DailyBar],
        fin: Financials | None = None,
    ) -> ScoreBreakdown:
        notes = []
        fin = fin or Financials()

        # ① 成长 35%
        growth = 50.0
        if fin.revenue_yoy is not None:
            growth = (90 if fin.revenue_yoy >= 30 else 70 if fin.revenue_yoy >= 10
                      else 50 if fin.revenue_yoy >= 0 else 25)
        else:
            notes.append("营收 YoY 缺失（成长计中性）")

        # ② 估值 30%（PE 5 年分位不可得 → 绝对 PE 粗分近似）
        valuation = 50.0
        if fin.pe_ttm is not None and fin.pe_ttm > 0:
            valuation = (80 if fin.pe_ttm < 20 else 60 if fin.pe_ttm < 35
                         else 45 if fin.pe_ttm < 60 else 30)
            notes.append("估值为绝对 PE 粗分（5 年分位数据不足）")
        else:
            notes.append("PE 数据缺失（估值计中性）")

        # ③ 质量 20%
        quality = 50.0
        if fin.gross_margin is not None:
            quality = _clamp(50 + (fin.gross_margin - 40) * 0.5
                             + (15 if fin.fcf_positive else -15)
                             + ((fin.roe or 15) - 15) * 0.3)
        elif fin.fcf_positive is not None:
            quality = 65 if fin.fcf_positive else 35

        # ④ 技术面 15%：分层（伤害 25% + 趋势 40% + 择时 35%）
        tech = 50.0
        tech_parts = {}
        if len(bars) >= 60:
            # 趋势层：MA50 斜率 + 价格相对 MA50
            slope = technicals.ma_slope_pct(bars, 50, 10)
            ma50 = technicals.sma(bars, 50)
            trend = 50.0
            if slope is not None:
                trend += max(-30.0, min(30.0, slope * 6))
            if ma50:
                trend += 10 if bars[-1].close >= ma50 else -10
            tech_parts["趋势"] = _clamp(trend)

            # 择时层：RSI 区间语义（强势趋势 70+ 不算卖出信号）
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

            # 伤害度量：52 周回撤 + 乖离率（主指标，破位仅确认）
            drawdown = technicals.drawdown_from_high_pct(bars)
            damage = 60.0
            if drawdown is not None:
                damage = (60 if drawdown > -10 else 50 if drawdown > -25
                          else 40 if drawdown > -40 else 30)
            tech_parts["伤害"] = damage

            tech = round(tech_parts["趋势"] * 0.40 + tech_parts["择时"] * 0.35 + tech_parts["伤害"] * 0.25, 1)
        else:
            notes.append("K 线数据不足（技术面计中性）")

        total = round(growth * 0.35 + valuation * 0.30 + quality * 0.20 + tech * 0.15, 1)
        tone = "偏多" if total >= 60 else ("偏空" if total <= 40 else "中性")
        return ScoreBreakdown(
            score=total,
            indicators={"成长": growth, "估值": valuation, "质量": round(quality, 1),
                        "技术面": tech, **tech_parts},
            rationale=(f"{ticker}：成长 {growth:.0f}、估值 {valuation:.0f}、质量 {quality:.0f}、"
                       f"技术面 {tech:.0f}，公司面{tone}。"),
            degraded=bool(notes), degraded_note="；".join(notes),
        )
