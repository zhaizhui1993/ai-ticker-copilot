"""LLM 层：全系统唯一的 LLM 出口（供应商无关，docs/06-analyzer/provider.md）。

- 真 LLM：langchain ChatOpenAI + with_structured_output(method="function_calling")
  ——OpenAI 兼容端点间兼容性最好的方式；换供应商只改 .env 三项（LLM_*）
- 降级（docs/10-module-contracts.md §10.5）：LLM_* 未配置或调用失败 →
  规则版直出并标注"LLM 降级"，分数与主流程不受影响
- 事件抽取：P3 规则版保留为降级路径（extract_events_rule），
  LLM 可用时走批量单次调用（extract_events）
"""

from datetime import date

from domain.events import CurrentEvent, EventCategory, EventMatchResult, EventScope, RawArticle
from domain.signal import Action, AnalysisResult, TickerSignal
from config.settings import settings

from analyzer.rule_extract import extract_events as extract_events_rule  # noqa: F401（降级路径）

DEGRADE_NOTE = "LLM 降级（未经 LLM 研判，按分档直出）"


def llm_available() -> bool:
    return bool(settings.llm_api_key and settings.llm_model)


def _chat():
    from langchain_openai import ChatOpenAI  # 延迟导入：无依赖环境可跑规则版

    return ChatOpenAI(
        openai_api_base=settings.llm_base_url,
        openai_api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )


# ---------- 事件抽取（P6：LLM 批量版 + 规则降级） ----------


def extract_events(
    articles: list[RawArticle],
    pool_tickers: list[str],
    seq_start: int = 1,
    today: date | None = None,
) -> list[CurrentEvent]:
    if not articles:
        return []  # 空批次不调 LLM（事件管道每 20min 一轮，空转是最大浪费源）
    if not llm_available():
        return extract_events_rule(articles, pool_tickers, seq_start, today)
    try:
        from analyzer.schemas import EventBatch

        structured = _chat().with_structured_output(EventBatch, method="function_calling")
        batch: EventBatch = structured.invoke(_build_extract_prompt(articles, pool_tickers))
        today = today or date.today()
        return [
            CurrentEvent(
                event_id=f"{today:%Y-%m-%d}-{seq_start + i:03d}",
                title=e.title[:200],
                occurred_date=today,
                scope=e.scope,
                category=e.category,
                summary=(e.summary or e.title)[:300],
                keywords=e.keywords or [],
                tickers_mentioned=[t for t in e.tickers_mentioned if t in pool_tickers] or [],
                source=articles[0].source if articles else "llm",
                raw_url=e.raw_url or "",
            )
            for i, e in enumerate(batch.events)
        ]
    except Exception as exc:
        print(f"[llm] 事件抽取降级为规则版：{exc}")
        return extract_events_rule(articles, pool_tickers, seq_start, today)


def _build_extract_prompt(articles: list[RawArticle], pool_tickers: list[str]) -> str:
    lines = [
        f"从以下新闻中抽取属于四类事件（macro_policy 宏观政策 / geopolitical 国际热点 / "
        f"industry 行业 / company 企业）的结构化事件。股票池：{','.join(pool_tickers) or '（空）'}。"
        "宁缺勿滥，无关的跳过；category 从 macro/monetary/regulation/tech/crisis 中选。"
    ]
    for i, a in enumerate(articles, start=1):
        lines.append(f"[{i}] {a.title}｜{a.summary[:150]}｜{a.source}｜{a.raw_url}")
    return "\n".join(lines)


# ---------- 事件精排（供 events_lib/matcher 调用；失败返回 None 走规则版） ----------


def rerank_matches(event, candidates) -> list[EventMatchResult] | None:
    if not llm_available():
        return None
    try:
        from prompts.event_match import SYSTEM_PROMPT, build_match_prompt
        from analyzer.schemas import MatchBatch

        structured = _chat().with_structured_output(MatchBatch, method="function_calling")
        batch: MatchBatch = structured.invoke(
            [("system", SYSTEM_PROMPT), ("human", build_match_prompt(event, candidates))]
        )
        valid_ids = {c.event_id for c in candidates}
        results = [m for m in batch.matches if m.event_id in valid_ids]
        return results or None
    except Exception as exc:
        print(f"[llm] 类比精排降级为规则版：{exc}")
        return None


# ---------- 综合研判 ----------


def judge(ctx: dict, ticker_ctx: dict) -> AnalysisResult:
    """ctx：全局上下文；ticker_ctx：{ticker: 每股输入（pipeline 组装）}。"""
    if llm_available():
        try:
            from prompts.analysis import SYSTEM_PROMPT, build_analysis_prompt

            structured = _chat().with_structured_output(AnalysisResult, method="function_calling")
            result: AnalysisResult = structured.invoke(
                [("system", SYSTEM_PROMPT), ("human", build_analysis_prompt(ctx))]
            )
            result.disclaimer = "本报告仅供个人研究参考，不构成投资建议。"
            ctx["raw_result"] = result.model_dump(mode="json")
            ctx["result_source"] = "llm"
            from analyzer.constraints import enforce
            return enforce(result, rule_judge(ctx, ticker_ctx), ctx, ticker_ctx)
        except Exception as exc:
            print(f"[llm] 综合研判降级为规则版：{exc}")
    ctx["result_source"] = "rule"
    from analyzer.constraints import enforce
    fallback = rule_judge(ctx, ticker_ctx)
    ctx["raw_result"] = fallback.model_dump(mode="json")
    return enforce(fallback, fallback, ctx, ticker_ctx)


def rule_judge(ctx: dict, ticker_ctx: dict) -> AnalysisResult:
    """规则版研判：分档直出 + 体制层分级约束封顶（watch_add·小仓 + 仓位系数）；
    理由必须引用分数（与 prompt 规则同语义）。"""
    gate = bool(ctx.get("regime_gate"))
    signals = []
    for ticker, data in ticker_ctx.items():
        total, band = data["total"], data["band"]
        action = {
            "积极": Action.ACCUMULATE, "中性偏多": Action.WATCH_ADD,
            "中性偏空": Action.WATCH, "防御": Action.REDUCE,
        }[band]
        reason = (
            f"总分 {total}（{band}）：宏观 {data['scores']['macro']:.0f}/事件 {data['scores']['event']:.0f}"
            f"/产业 {data['scores']['industry']:.0f}/公司 {data['scores']['company']:.0f}。"
        )
        analogy = data.get("analogy_note")
        if analogy:
            reason += f"事件类比：{analogy}。"
        position_cap = float(data.get("position_cap", 1.0))
        if gate and action == Action.ACCUMULATE:
            reason += (f"体制层分级约束生效（{ctx.get('regime_note', '')}），"
                       f"信号上限压至观望偏加仓（小仓），仓位上限系数 {position_cap}。")
            action = Action.WATCH_ADD
        if data.get("degraded_note"):
            reason += f"数据降级：{data['degraded_note']}。"
        if ctx.get("llm_degraded"):
            reason += f"（{DEGRADE_NOTE}）"
        signals.append(TickerSignal(
            ticker=ticker, action=action,
            confidence=0.55 if action != Action.REDUCE else 0.6,
            reason=reason,
            risks=[data.get("risk_hint") or "四维分数与信号为规则产物，未经 LLM 交叉研判"],
            price_target_hint=None,
            position_cap=position_cap if gate else None,
        ))
    return AnalysisResult(
        generated_at=ctx.get("date", ""),
        signals=signals,
        market_summary=ctx.get("macro_summary", ""),
        disclaimer="本报告仅供个人研究参考，不构成投资建议。",
    )
