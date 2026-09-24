"""Deterministic final checks, shared by LLM and fallback outputs."""
from collections import Counter
from domain.signal import Action, AnalysisResult

RANK = {Action.REDUCE: 0, Action.WATCH: 1, Action.WATCH_ADD: 2, Action.ACCUMULATE: 3}


def enforce(result: AnalysisResult, fallback: AnalysisResult, ctx: dict, tickers: dict) -> AnalysisResult:
    counts = Counter(s.ticker for s in result.signals)
    given = {s.ticker: s for s in result.signals}
    defaults = {s.ticker: s for s in fallback.signals}
    signals = []
    for ticker, data in tickers.items():
        signal = (given[ticker] if counts[ticker] == 1 else defaults[ticker]).model_copy(deep=True)
        ceiling, cap, notes = Action.ACCUMULATE, 1.0, []
        if ctx.get("regime_gate") or data.get("company_gate"):
            ceiling, cap = Action.WATCH_ADD, 0.3 if ctx.get("regime_gate") else 1.0
            notes.append("体制或公司短板约束")
        if ctx.get("regime_unknown") or data.get("data_insufficient") or data.get("calendar_unknown"):
            ceiling, cap = Action.WATCH, 0.0
            notes.append("关键数据或日历不足，暂不增加风险")
        if data.get("event_window"):
            ceiling, cap = Action.WATCH, 0.0
            notes.append("等待" + data.get("event_desc", "重要事件") + "落地")
        if RANK[signal.action] > RANK[ceiling]:
            signal.action = ceiling
            signal.reason += "；系统约束：" + "；".join(notes)
            signal.confidence = min(signal.confidence, 0.5)
        signal.position_cap = cap
        signal.risks = list(dict.fromkeys(signal.risks + notes)) or ["研究假设可能无法兑现"]
        signals.append(signal)
    return result.model_copy(update={"signals": signals})
