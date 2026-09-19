"""事件面评分（权重 25%）= 历史类比 80% + X 情绪 20%。

规格：docs/05-scoring/event-score.md
  事件影响分 = Σ 命中事件 (direction × magnitude × similarity × 新鲜度衰减)
  新鲜度衰减 = 0.5 ^ (事件距今天数 / 7)   # 半衰期 7 天
  未直接列出该标的的命中按 0.5 折扣；X 缺失 → 情绪计 50 并标注
  总分 = 50 + 类比分×40% + (情绪分-50)×20%，截断 [0,100]
"""

from domain.events import EventMatchResult
from domain.scoring import ScoreBreakdown

HALF_LIFE_DAYS = 7.0
NON_LISTED_DISCOUNT = 0.5


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class EventScorer:
    name = "event"

    def score(
        self,
        ticker: str,
        matches: list[tuple[EventMatchResult, int]] | None = None,
        x_sentiment: float | None = None,
    ) -> ScoreBreakdown:
        """matches: (匹配结果, 事件距今天数) 列表；x_sentiment: 0-100 或 None。"""
        matches = matches or []
        indicators: dict = {"matched": len(matches)}

        analogy_score = 0.0
        for match, days_ago in matches:
            freshness = 0.5 ** (days_ago / HALF_LIFE_DAYS)
            listed = ticker.upper() in {t.upper() for t in match.affected_tickers}
            discount = 1.0 if listed else NON_LISTED_DISCOUNT
            analogy_score += match.direction * match.magnitude * match.similarity * freshness * discount
        analogy_score = _clamp(analogy_score * 100, -100, 100)
        indicators["类比分"] = round(analogy_score, 1)

        degraded_notes = []
        if not matches:
            degraded_notes.append("无事件命中（计中性）")
        if x_sentiment is None:
            sentiment = 50.0
            degraded_notes.append("X 数据缺失（情绪计中性 50）")
        else:
            sentiment = _clamp(x_sentiment)
        indicators["情绪分"] = round(sentiment, 1)

        total = _clamp(50 + analogy_score * 0.4 + (sentiment - 50) * 0.2)
        strongest = max(matches, key=lambda m: m[0].similarity)[0] if matches else None
        rationale = (
            f"类比命中 {len(matches)} 条"
            + (f"（最强相似度 {strongest.similarity}，事件 {strongest.event_id}）" if strongest else "")
            + f"，X 情绪 {sentiment:.0f}，事件面{'偏空' if total < 45 else ('偏多' if total > 55 else '中性')}。"
        )
        return ScoreBreakdown(
            score=round(total, 1), indicators=indicators, rationale=rationale,
            degraded=bool(degraded_notes), degraded_note="；".join(degraded_notes),
        )
