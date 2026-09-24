"""事件面评分（权重 25%）= 历史类比 80% + X 情绪 20%（两腿齐备时）。

规格：docs/05-scoring/event-score.md
  事件影响分 = Σ 命中事件 (direction × magnitude × similarity × 新鲜度衰减)
  新鲜度衰减按事件性质分类型（v1.2 / P1-1）：政策/管制/危机类影响以季度计，
  财报与企业类冲击数日即均值回归——单一 7 天半衰期对芯片管制这类季度级
  影响衰减过快（2022-10 管制影响持续一年以上）。
  X 情绪缺失时不再塞中性 50，而是把类比腿权重显式重归一化至 100%（P1-4），
  保证当前任何分档校准不建立在残缺维度上。
  v1.3 状态缺口调节（P1-2 演进）：匹配携带历史样本事件前状态（pre_bias_ma200）
  且传入当前标的状态时，按拥挤度缺口调节 magnitude（clamp ×0.5~×1.5）——
  同样的芯片管制打在"乖离 +80% 新高"与"已跌 30%"位置，冲击深度不同
  （实证：2026-07 回调深度主要由事件前乖离率决定）。
"""

from collections import defaultdict

from domain.events import EventMatchResult
from domain.scoring import ScoreBreakdown

HALF_LIFE_DAYS = 7.0                       # 默认（企业类/未分类事件）
HALF_LIFE_BY_CATEGORY = {                  # 按历史事件性质（category）分类型半衰期
    "macro": 30.0,                         # 宏观政策/贸易摩擦
    "monetary": 30.0,                      # 货币政策
    "regulation": 45.0,                    # 监管/出口管制
    "crisis": 60.0,                        # 危机事件
    "tech": 14.0,                          # 技术冲击
}
NON_LISTED_DISCOUNT = 0.5

# v1.3 状态缺口调节（P1-2 演进）：当前标的比历史样本更拥挤 → 冲击放大
STATE_FACTOR_MIN, STATE_FACTOR_MAX = 0.5, 1.5
STATE_FACTOR_GAIN = 0.5                    # 每 100pt 乖离缺口调节 0.5 倍


def _state_factor(match: EventMatchResult, current_state: dict | None) -> float:
    """历史前状态 vs 当前状态的拥挤度缺口 → magnitude 调节系数（clamp 0.5~1.5）。

    依据：2026-07 实证——回调深度主要由事件前 +40%~120% 乖离率决定。
    任一侧状态缺失 → 1.0（中性，不调节）。
    """
    if not current_state or match.pre_bias_ma200 is None:
        return 1.0
    current_bias = current_state.get("bias_ma200")
    if current_bias is None:
        return 1.0
    gap = current_bias - match.pre_bias_ma200   # 正 = 当前更拥挤
    factor = 1.0 + gap / 100 * STATE_FACTOR_GAIN
    return max(STATE_FACTOR_MIN, min(STATE_FACTOR_MAX, factor))


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class EventScorer:
    name = "event"

    def score(
        self,
        ticker: str,
        matches: list[tuple[EventMatchResult, int]] | None = None,
        x_sentiment: float | None = None,
        category_by_event: dict[str, str] | None = None,
        current_state: dict | None = None,
    ) -> ScoreBreakdown:
        """matches: (匹配结果, 事件距今天数)；x_sentiment: 0-100 或 None；
        category_by_event: {event_id: category.value}，供分类型衰减查表；
        current_state: 当前标的状态 {"bias_ma200": 乖离%, "drawdown_52w": 回撤%}，
        供状态缺口调节（v1.3）。"""
        groups = defaultdict(dict)
        for match, age in matches or []:
            if match.similarity >= 0.6 and age >= 0:
                key = match.current_event_id or match.event_id
                old = groups[key].get(match.event_id)
                if old is None or match.similarity > old[0].similarity:
                    groups[key][match.event_id] = (match, age)
        matches = [pair for group in groups.values() for pair in group.values()]
        weight_sums = {key: sum(m.similarity for m, _ in group.values()) for key, group in groups.items()}
        category_by_event = category_by_event or {}
        indicators: dict = {"matched": len(matches)}

        analogy_score = 0.0
        half_lives_used = set()
        state_factors = []
        for match, days_ago in matches:
            half_life = HALF_LIFE_BY_CATEGORY.get(
                category_by_event.get(match.event_id, ""), HALF_LIFE_DAYS)
            half_lives_used.add(half_life)
            freshness = 0.5 ** (days_ago / half_life)
            listed = ticker.upper() in {t.upper() for t in match.affected_tickers}
            discount = 1.0 if listed else NON_LISTED_DISCOUNT
            factor = _state_factor(match, current_state)
            if factor != 1.0:
                state_factors.append(factor)
            key = match.current_event_id or match.event_id
            confidence = max(m.similarity for m, _ in groups[key].values())
            weight = match.similarity / weight_sums[key] * confidence
            analogy_score += (match.direction * match.magnitude * weight
                              * freshness * discount * factor)
        analogy_score = _clamp(analogy_score * 100, -100, 100)
        indicators["类比分"] = round(analogy_score, 1)
        if half_lives_used:
            indicators["半衰期(天)"] = "/".join(str(int(h)) for h in sorted(half_lives_used))
        if state_factors:
            indicators["状态调节"] = f"x{min(state_factors):.2f}~x{max(state_factors):.2f}"

        degraded_notes = []
        if not matches:
            degraded_notes.append("无事件命中（计中性）")

        if x_sentiment is None:
            # P1-4：情绪腿缺失 → 类比权重 0.8→1.0 显式重归一化，不塞中性 50
            sentiment = None
            total = _clamp(50 + analogy_score * 0.5)
            degraded_notes.append("X 数据缺失（情绪腿剔除，类比权重重归一化 0.8→1.0）")
        else:
            sentiment = _clamp(x_sentiment)
            total = _clamp(50 + analogy_score * 0.4 + (sentiment - 50) * 0.2)
        indicators["情绪分"] = round(sentiment, 1) if sentiment is not None else None

        strongest = max(matches, key=lambda m: m[0].similarity)[0] if matches else None
        rationale = (
            f"类比命中 {len(matches)} 条"
            + (f"（最强相似度 {strongest.similarity}，事件 {strongest.event_id}" +
               (f"，差异：{strongest.difference}" if strongest.difference else "") + "）"
               if strongest else "")
            + (f"，状态调节 ×{min(state_factors):.2f}~×{max(state_factors):.2f}"
               if state_factors else "")
            + (f"，X 情绪 {sentiment:.0f}" if sentiment is not None else "，X 情绪缺失（类比权重重归一化）")
            + f"，事件面{'偏空' if total < 45 else ('偏多' if total > 55 else '中性')}。"
        )
        return ScoreBreakdown(
            score=round(total, 1), indicators=indicators, rationale=rationale,
            degraded=bool(degraded_notes), degraded_note="；".join(degraded_notes),
        )
