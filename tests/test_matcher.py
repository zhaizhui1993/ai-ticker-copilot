"""P4 验收（docs/09-delivery/roadmap.md）：
构造"对华管制升级"假事件应命中 2023-10 轮次；硬检索排序、聚合与样本量保护。"""

from datetime import date

from domain.events import CurrentEvent, EventCategory, EventScope
from events_lib.loader import load_seed_events
from events_lib.matcher import (
    hard_retrieve,
    match_event,
    match_event_degraded,
    rule_rerank,
    synthesize_analogy,
)


def _event(**kwargs) -> CurrentEvent:
    defaults = dict(
        event_id="test-000",
        title="测试事件",
        occurred_date=date(2026, 10, 17),
        scope=EventScope.GEOPOLITICAL,
        category=EventCategory.REGULATION,
        summary="",
        keywords=[],
        tickers_mentioned=[],
        source="test",
    )
    defaults.update(kwargs)
    return CurrentEvent(**defaults)


def test_acceptance_fake_export_event_hits_2023_10() -> None:
    """验收：'对华管制升级'假事件 → 硬检索第一 + 精排 similarity≥0.6。"""
    lib = load_seed_events()
    fake = _event(
        title="对华芯片管制升级",
        keywords=["出口管制", "芯片", "制裁", "算力管制"],
        tickers_mentioned=["NVDA"],
    )
    top = hard_retrieve(fake, lib, k=5)
    assert top[0].event_id == "2023-10-chip-export-tighten"
    assert {e.event_id for e in top[:3]} >= {
        "2023-10-chip-export-tighten", "2022-10-chip-export-rule",
    }

    matches = rule_rerank(fake, top)
    best = next(m for m in matches if m.event_id == "2023-10-chip-export-tighten")
    assert best.similarity >= 0.6
    assert "规则版精排" in best.analogy_notes          # 可核对的匹配理由


def test_deepseek_event_hits_seed() -> None:
    lib = load_seed_events()
    fake = _event(
        title="开源模型再次冲击算力叙事",
        occurred_date=date(2026, 1, 27),
        category=EventCategory.TECH,
        keywords=["deepseek", "capex"],
        tickers_mentioned=["NVDA"],
    )
    assert hard_retrieve(fake, lib, k=1)[0].event_id == "2025-01-deepseek-shock"


def test_synthesize_analogy_aggregation_and_sample_guard() -> None:
    lib = load_seed_events()
    fake = _event(
        title="对华芯片管制升级",
        keywords=["出口管制", "芯片", "制裁", "算力管制"],
        tickers_mentioned=["NVDA"],
    )
    conclusion = match_event(fake, lib)
    assert "2023-10-chip-export-tighten" in conclusion.matched_event_ids
    assert conclusion.sample_size >= 1
    assert conclusion.confidence == "low"               # 规则版精排
    assert "样本不足" in conclusion.note or "未经 LLM" in conclusion.note

    # 无命中事件 → 空结论 + 标注
    unrelated = _event(
        title="某公司更换 logo", category=EventCategory.TECH,
        keywords=["logo"], tickers_mentioned=["ZZZZ"],
        occurred_date=date(2026, 6, 1),
    )
    empty = match_event(unrelated, lib)
    assert empty.matched_event_ids == []
    assert "无 similarity" in empty.note


def test_degraded_path_low_confidence() -> None:
    lib = load_seed_events()
    fake = _event(
        title="对华芯片管制升级",
        keywords=["出口管制", "芯片", "制裁", "算力管制"],
        tickers_mentioned=["NVDA"],
    )
    conclusion = match_event_degraded(fake, lib)
    assert conclusion.confidence == "low"
    assert "低置信" in conclusion.note
    assert len(conclusion.matched_event_ids) <= 2        # 硬检索 top-2


def test_2026_07_event_carries_measured_data() -> None:
    """种子库 2026-07 条目带实测数据，聚合时应产出非空平均回撤。"""
    lib = load_seed_events()
    event = next(e for e in lib if e.event_id == "2026-07-ai-valuation-pullback")
    assert event.market.vix_peak == 20.7
    drawdowns = [t.drawdown for t in event.tickers_affected if t.drawdown is not None]
    assert len(drawdowns) == 8                            # 八个标的（含 IXIC -10.1）均带实测回撤

    fake = _event(
        title="AI 估值疑虑再起，半导体板块大跌",
        occurred_date=date(2026, 7, 10),
        category=EventCategory.TECH,
        keywords=["AI回调", "收益率", "估值", "半导体"],
        tickers_mentioned=["NVDA", "BE"],
    )
    conclusion = match_event(fake, lib)
    assert "2026-07-ai-valuation-pullback" in conclusion.matched_event_ids
    assert conclusion.avg_drawdown is not None            # 实测数据可聚合出平均回撤
