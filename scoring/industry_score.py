"""产业面评分（权重 25%）：相对强弱 40% + 财报动量 30% + AI 景气度 30%。

规格：docs/05-scoring/industry-score.md
篮子映射 segment → 固定龙头；`other` 无映射 → 该腿剔除（降级协议）。
v1.2（P1-4）：数据缺失的子腿不再塞中性 50，而是显式重归一化剩余腿权重
——当前财报动量与 AI 词频常缺，若塞两个 50 会把相对强弱信号稀释过半。
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
        legs: list[tuple[str, float, float]] = []  # (子项名, 分数, 权重)
        key = segment.value if hasattr(segment, "value") else str(segment)
        symbols = [s for s in BASKETS.get(key, []) if s in bars_by_symbol]

        # ① 相对强弱：篮子 1M/3M 平均收益 vs SPY 超额
        rel = None
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
                legs.append(("相对强弱", rel, WEIGHT_REL))
        if rel is None:
            notes.append(f"segment={key} 无篮子映射或无数据（相对强弱腿剔除，权重重归一化）")

        # ② 财报动量：篮子营收 YoY 中位数
        yoy_values = [
            financials[s].revenue_yoy for s in symbols
            if financials and s in financials and financials[s].revenue_yoy is not None
        ]
        if yoy_values:
            yoy_values.sort()
            mid = yoy_values[len(yoy_values) // 2]
            earn = 85 if mid >= 30 else 65 if mid >= 10 else 50 if mid >= 0 else 25
            legs.append(("财报动量", earn, WEIGHT_EARNINGS))
        elif symbols:
            notes.append("篮子财报数据缺失（财报动量腿剔除，权重重归一化）")

        # ③ AI 景气度：新闻词频命中率环比变化
        if ai_word_delta is not None:
            ai = 75 if ai_word_delta > 0.1 else 30 if ai_word_delta < -0.1 else 50
            legs.append(("AI景气", ai, WEIGHT_AI_WORDS))
        else:
            notes.append("AI 词频数据缺失（景气度腿剔除，权重重归一化）")

        if legs:
            w_sum = sum(w for _, _, w in legs)
            total = round(sum(v * w for _, v, w in legs) / w_sum, 1)
            norm = f"，权重重归一化 {w_sum:.0%}" if abs(w_sum - 1.0) > 1e-9 else ""
        else:
            total, norm = 50.0, ""
        tone = "偏多" if total >= 60 else ("偏空" if total <= 40 else "中性")

        indicators = {name: round(v, 1) for name, v, _ in legs}
        indicators["basket"] = ",".join(symbols)
        parts_desc = "、".join(f"{name} {v:.0f}" for name, v, _ in legs)
        return ScoreBreakdown(
            score=total,
            indicators=indicators,
            rationale=f"产业链篮子（{key}）{parts_desc}{norm}，产业面{tone}。",
            degraded=bool(notes), degraded_note="；".join(notes),
        )
