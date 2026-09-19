"""两级类比匹配：硬检索 top-K → 精排 → 类比结论合成。

规格：docs/04-events/matcher.md（docs/10-module-contracts.md §10.2② 签名）
- 硬检索：category 相同 +10；keywords 交集每词 +5；tickers 交集每 +8；
  月份邻近（同月±1）+3；取 top-5
- 精排：P4 为规则版（可解释的相似度成分），P6 接真 LLM（供应商无关）后
  替换 rerank 实现，接口不变；LLM 路径 confidence='high'
- 降级路径：LLM 不可用 → 硬检索 top-2 直接合成，confidence='low' 并标注
- 样本量保护：聚合 n<3 输出"样本不足"而非平均值（v1.1 防自欺）
"""

from domain.events import (
    AnalogyConclusion,
    CurrentEvent,
    EventMatchResult,
    HistoricalEvent,
)

SIMILARITY_THRESHOLD = 0.6  # ≥0.6 才进入类比聚合


# ---------- ① 硬检索 ----------


def _month_closeness(a_month: int, b_month: int) -> bool:
    diff = abs(a_month - b_month)
    return diff <= 1 or diff >= 11  # 同月或相邻月（跨年 12↔1 视为相邻）


def hard_retrieve(
    event: CurrentEvent,
    lib: list[HistoricalEvent],
    k: int = 5,
) -> list[HistoricalEvent]:
    """对事件库全量规则打分排序（库小，O(N) 即可），取 top-k。"""
    event_keywords = {kw.lower() for kw in event.keywords}
    event_tickers = set(event.tickers_mentioned)
    event_month = event.occurred_date.month

    scored: list[tuple[float, str, HistoricalEvent]] = []
    for candidate in lib:
        score = 0.0
        if candidate.category == event.category:
            score += 10
        cand_keywords = {kw.lower() for kw in candidate.keywords}
        score += 5 * len(event_keywords & cand_keywords)
        cand_tickers = {t.ticker for t in candidate.tickers_affected}
        score += 8 * len(event_tickers & cand_tickers)
        if _month_closeness(event_month, candidate.start_date.month):
            score += 3
        scored.append((score, candidate.event_id, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:k]]


# ---------- ② 精排（P4 规则版；P6 换 LLM，签名不变） ----------


def rule_rerank(event: CurrentEvent, candidates: list[HistoricalEvent]) -> list[EventMatchResult]:
    """规则版精排：相似度由四个可核对成分构成（P6 替换为 LLM 精排）。"""
    event_keywords = {kw.lower() for kw in event.keywords}
    event_tickers = set(event.tickers_mentioned)

    results: list[EventMatchResult] = []
    for candidate in candidates:
        parts = 0.0
        if candidate.category == event.category:
            parts += 0.3
        cand_keywords = {kw.lower() for kw in candidate.keywords}
        if event_keywords:
            coverage = len(event_keywords & cand_keywords) / min(len(event_keywords), 4)
            parts += 0.4 * min(1.0, coverage)
        cand_tickers = {t.ticker for t in candidate.tickers_affected}
        if event_tickers:
            parts += 0.2 * min(1.0, len(event_tickers & cand_tickers))
        if _month_closeness(event.occurred_date.month, candidate.start_date.month):
            parts += 0.1

        # 方向/强度沿用库内记录的众数水平（规则版无法独立判断）
        impacts = [t for t in candidate.tickers_affected
                   if not event_tickers or t.ticker in event_tickers] or candidate.tickers_affected
        direction = impacts[0].direction if impacts else -1
        magnitude = max((t.magnitude for t in impacts), default=0.5)

        results.append(EventMatchResult(
            event_id=candidate.event_id,
            similarity=round(min(1.0, parts), 3),
            direction=direction,
            magnitude=magnitude,
            affected_tickers=[t.ticker for t in impacts],
            analogy_notes=(
                f"规则版精排：category{'一致' if candidate.category == event.category else '不同'}"
                f" +关键词交集{len(event_keywords & cand_keywords)}词"
                f" +标的交集{len(event_tickers & cand_tickers)}个"
                f"{' +月份邻近' if _month_closeness(event.occurred_date.month, candidate.start_date.month) else ''}"
                "（未经 LLM 校验）"
            ),
        ))
    results.sort(key=lambda m: -m.similarity)
    return results


def llm_rerank(event: CurrentEvent, candidates: list[HistoricalEvent]) -> list[EventMatchResult]:
    """LLM 精排入口（P6 接真实现；当前委托规则版并保持 confidence='low'）。"""
    return rule_rerank(event, candidates)


# ---------- ③ 类比结论合成 ----------


def synthesize_analogy(
    matches: list[EventMatchResult],
    lib: list[HistoricalEvent],
) -> AnalogyConclusion:
    """取 similarity≥0.6 的事件聚合平均影响；n<3 标注样本不足。"""
    lib_by_id = {e.event_id: e for e in lib}
    hit = [m for m in matches if m.similarity >= SIMILARITY_THRESHOLD]

    conclusion = AnalogyConclusion(confidence="low", matched_event_ids=[m.event_id for m in hit])
    if not hit:
        conclusion.note = "无 similarity≥0.6 的历史事件命中（低置信，未过 LLM 校验）"
        return conclusion

    drawdowns, dd_days, rec_days = [], [], []
    for match in hit:
        event = lib_by_id.get(match.event_id)
        if not event:
            continue
        for impact in event.tickers_affected:
            if impact.drawdown is not None:
                drawdowns.append(impact.drawdown)
            if impact.drawdown_days is not None:
                dd_days.append(impact.drawdown_days)
            if impact.recovery_days is not None:
                rec_days.append(impact.recovery_days)

    conclusion.sample_size = len(hit)
    if drawdowns:
        conclusion.avg_drawdown = round(sum(drawdowns) / len(drawdowns), 2)
    if dd_days:
        conclusion.avg_drawdown_days = round(sum(dd_days) / len(dd_days))
    if rec_days:
        conclusion.avg_recovery_days = round(sum(rec_days) / len(rec_days))

    if len(hit) < 3:
        conclusion.note = f"样本不足（n={len(hit)}<3），仅供参考"
    else:
        conclusion.note = "规则版精排（未经 LLM 校验）"
    return conclusion


# ---------- 组合入口与降级 ----------


def match_event(event: CurrentEvent, lib: list[HistoricalEvent]) -> AnalogyConclusion:
    """完整两级匹配。LLM 不可用/未接入时自动走降级路径（硬检索 top-2）。"""
    candidates = hard_retrieve(event, lib, k=5)
    if not candidates:
        return AnalogyConclusion(confidence="low", note="事件库为空")
    matches = llm_rerank(event, candidates)
    return synthesize_analogy(matches, lib)


def match_event_degraded(event: CurrentEvent, lib: list[HistoricalEvent]) -> AnalogyConclusion:
    """显式降级路径：硬检索 top-2 直接合成（docs/04-events/matcher.md）。"""
    candidates = hard_retrieve(event, lib, k=2)
    conclusion = synthesize_analogy(
        [EventMatchResult(
            event_id=c.event_id, similarity=SIMILARITY_THRESHOLD,  # 降级时视为边缘命中
            direction=(c.tickers_affected[0].direction if c.tickers_affected else -1),
            magnitude=max((t.magnitude for t in c.tickers_affected), default=0.5),
            affected_tickers=[t.ticker for t in c.tickers_affected],
            analogy_notes="低置信类比（未过 LLM 校验，硬检索 top-2 降级）",
        ) for c in candidates],
        lib,
    )
    conclusion.confidence = "low"
    conclusion.note = "低置信类比（未过 LLM 校验）"
    return conclusion
