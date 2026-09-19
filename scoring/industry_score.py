"""产业面评分（权重 25%）：相对强弱 40% + 财报动量 30% + AI 景气度 30%。

规格：docs/05-scoring/industry-score.md
篮子映射 segment → 固定龙头；`other` 无映射 → 该子项中性并标注（降级协议）。
"""

from domain.stock import DailyBar, Financials
from domain.scoring import ScoreBreakdown

BASKETS: dict[str, list[str]] = {
    "gpu": ["NVDA", "AMD"],
    "foundry": ["TSM"],
    "equipment": ["ASML", "AMAT", "LRCX"],
    "cloud": ["MSFT", "GOOGL", "AMZN"],
    "software": ["MSFT", "CRM"],
    "power": ["CEG", "VST"],
    "etf": ["SMH", "SOXX"],
}

WEIGHT_REL = 0.40
WEIGHT_EARNINGS = 0.30
WEIGHT_AI_WORDS = 0.30


def _ret(bars: list[DailyBar], days: int) -> float | None:
    if len(bars) < days + 1:
        return None
    return (bars[-1].close / bars[-1 - days].close - 1) * 100


class IndustryScorer:
    name = "industry"

    def score(
        self,
        segment,
        bars_by_symbol: dict[str, list[DailyBar]],
        spy_bars: list[DailyBar] | None = None,
        financials: dict[str, Financials] | None = None,
        ai_word_delta: float | None = None,
    ) -> ScoreBreakdown:
        notes = []
        key = segment.value if hasattr(segment, "value") else str(segment)
        symbols = [s for s in BASKETS.get(key, []) if s in bars_by_symbol]

        # ① 相对强弱：篮子 1M/3M 平均收益 vs SPY 超额
        rel = 50.0
        if symbols and spy_bars:
            excesses = []
            for days in (21, 63):
                spy_ret = _ret(spy_bars, days)
                basket_ret = [r for r in (_ret(bars_by_symbol[s], days) for s in symbols) if r is not None]
                if spy_ret is not None and basket_ret:
                    excesses.append(sum(basket_ret) / len(basket_ret) - spy_ret)
            if excesses:
                excess = sum(excesses) / len(excesses)
                rel = 85 if excess >= 5 else 70 if excess >= 2 else 15 if excess <= -5 else 35 if excess <= -2 else 50
        elif not symbols:
            notes.append(f"segment={key} 无篮子映射或无数据（相对强弱计中性）")

        # ② 财报动量：篮子营收 YoY 中位数
        earn = 50.0
        yoy_values = [
            financials[s].revenue_yoy for s in symbols
            if financials and s in financials and financials[s].revenue_yoy is not None
        ]
        if yoy_values:
            yoy_values.sort()
            mid = yoy_values[len(yoy_values) // 2]
            earn = 85 if mid >= 30 else 65 if mid >= 10 else 50 if mid >= 0 else 25
        elif symbols:
            notes.append("篮子财报数据缺失（财报动量计中性）")

        # ③ AI 景气度：新闻词频命中率环比变化
        ai = 50.0
        if ai_word_delta is not None:
            ai = 75 if ai_word_delta > 0.1 else 30 if ai_word_delta < -0.1 else 50
        else:
            notes.append("AI 词频数据缺失（景气度计中性）")

        total = round(rel * WEIGHT_REL + earn * WEIGHT_EARNINGS + ai * WEIGHT_AI_WORDS, 1)
        tone = "偏多" if total >= 60 else ("偏空" if total <= 40 else "中性")
        return ScoreBreakdown(
            score=total,
            indicators={"basket": ",".join(symbols), "相对强弱": rel, "财报动量": earn, "AI景气": ai},
            rationale=f"产业链篮子（{key}）相对强弱 {rel:.0f}、财报动量 {earn:.0f}、AI 景气 {ai:.0f}，产业面{tone}。",
            degraded=bool(notes), degraded_note="；".join(notes),
        )
