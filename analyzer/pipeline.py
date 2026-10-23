"""分析编排（docs/10-module-contracts.md §10.4 场景 B）。

run_analysis：取数 → 事件匹配 → 四维评分 → 体制门槛 → LLM 研判 → 落库。
- 每次重新组装证据，采集缓存独立；每日快照仅用于展示
- 落库失败降级：DB 不可用时分析照常产出，跳过落库并标注
- 事件匹配：全部活跃当前事件 → 两级匹配（按当前事件类型衰减）
"""

from datetime import date, datetime
import json
from typing import Literal
from events_lib.calendar import ET, market_today, event_calendar

from analyzer import llm
from collectors import get_macro, get_market
from config.loader import EMPTY_POOL_MESSAGE, load_scoring_weights, load_stocks
from config.settings import settings
from domain.scoring import FourDimScores
from domain.asof import analysis_clock, completed_bars
from events_lib.exposure import exposure_for
from events_lib import matcher
from events_lib.loader import load_seed_events
from scoring.company_score import CompanyScorer
from scoring.engine import Engine
from scoring.event_score import EventScorer
from scoring.industry_score import IndustryScorer, BASKETS
from scoring.macro_score import MacroScorer
from scoring.valuation import assess_valuation


class EmptyPoolError(Exception):
    def __init__(self):
        super().__init__(EMPTY_POOL_MESSAGE)


def run_analysis(refresh: bool = False, tickers: list[str] | None = None,
                 mode: Literal["eod", "intraday_observe"] = "eod") -> dict:
    """返回 {result: AnalysisResult, outputs: {ticker: EngineOutput}, regime, db_saved: bool}。"""
    stocks = load_stocks()
    if not stocks:
        raise EmptyPoolError()
    if tickers:
        stocks = [s for s in stocks if s.symbol in tickers] or stocks

    market = get_market()
    clock = analysis_clock(mode)
    today = clock.decision_at.astimezone(ET).date()
    generated_at = datetime.now(ET).isoformat()

    # ---- 取数（各自降级） ----
    regime = None
    try:
        regime = market.get_index_regime(clock.price_session_limit)
    except Exception as exc:
        print(f"[pipeline] 指数体制层获取失败（限制新增风险并标注）：{exc}")

    macro_series: dict = {}
    try:
        macro_series = get_macro().get_all()
    except Exception as exc:
        print(f"[pipeline] 宏观数据缺失（中性降级）：{exc}")

    macro_score = MacroScorer().score(
        {k: v for k, v in macro_series.items() if k != "VIX"},
        vix=regime.vix if regime else None,
    )

    # ---- 事件匹配（全部 active 事件，不按抓取窗口截断） ----
    lib = [e for e in _load_lib() if e.start_date <= today]
    # 分类型新鲜度衰减查表：event_id → 历史事件性质（macro/regulation/…）
    category_by_event = {e.event_id: e.category.value for e in lib}
    lib_by_id = {e.event_id: e for e in lib}   # 状态附加：event_id → 历史事件（含 pre-state）
    event_data_unknown, event_data_note = False, ""
    try:
        recent_events = _active_current_events(today=today)
        if any(e.impact_date is None for e in recent_events):
            event_data_unknown, event_data_note = True, "存在参考日期未知的活跃事件"
    except Exception as exc:
        recent_events = []
        event_data_unknown, event_data_note = True, "活跃事件读取失败，不能确认风险信息完整"
        print(f"[pipeline] {event_data_note}：{exc}")
    # 完整相关篮子一次预取，避免把产业分退化为当前股票自身动量。
    symbols = {s.symbol for s in stocks} | {"SPY"}
    for stock in stocks:
        symbols.update(BASKETS.get(stock.segment.value, []))
    bars_by_symbol, financials = {}, {}
    for symbol in sorted(symbols):
        try:
            bars_by_symbol[symbol] = completed_bars(market.get_daily_bars(symbol, 300), clock)
        except Exception:
            bars_by_symbol[symbol] = []
        if symbol != "SPY":
            try:
                financials[symbol] = market.get_financials(symbol)
            except Exception:
                pass
    calendar_by_symbol = {s.symbol: event_calendar(market, s.symbol, today) for s in stocks}
    per_event_matches: list[tuple[list, object]] = []
    for event in recent_events:
        from analyzer import llm as llm_mod

        candidates = matcher.hard_retrieve(event, lib, k=5)
        reranked = llm_mod.rerank_matches(event, candidates)
        matches = reranked if reranked is not None else matcher.rule_rerank(event, candidates)
        per_event_matches.append((matches, event))

    # ---- 逐票评分 ----
    weights = load_scoring_weights()
    engine = Engine(weights)
    event_scorer = EventScorer()
    industry_scorer = IndustryScorer()
    company_scorer = CompanyScorer()

    outputs, ticker_ctx = {}, {}
    per_ticker_blocks = []
    four_by_symbol: dict = {}
    closes_by_symbol: dict = {}
    for stock in stocks:
        bars = bars_by_symbol.get(stock.symbol, [])
        fin = financials.get(stock.symbol)
        match_inputs = []
        event_exposures = []
        for matches, event in per_event_matches:
            exposure = exposure_for(event, stock.symbol, stock.segment.value)
            if exposure is None:
                continue
            event_exposures.append(exposure.model_dump(mode="json"))
            for m in matches[:3]:
                if event.impact_date and (today - event.impact_date).days >= 0:
                    m2 = m.model_copy(update={"current_event_id": event.event_id,
                                              "current_category": event.category})
                    hist = lib_by_id.get(m.event_id)
                    if hist is not None:
                        from events_lib.pre_state import attach_pre_state
                        attach_pre_state(m2, hist, stock.symbol)
                    match_inputs.append((m2, (today - event.impact_date).days))

        current_state = None
        if len(bars) >= 60:
            from domain import technicals
            current_state = {
                "bias_ma200": technicals.bias_vs_ma200_pct(bars),
                "drawdown_52w": technicals.drawdown_from_high_pct(bars),
            }
        event_score = event_scorer.score(stock.symbol, match_inputs, x_sentiment=None,
                                         category_by_event=category_by_event,
                                         current_state=current_state)

        industry_score = industry_scorer.score(stock.segment, bars_by_symbol,
                                              bars_by_symbol.get("SPY"), financials)
        company_score = company_scorer.score(stock.symbol, bars, fin, segment=stock.segment.value)

        four = FourDimScores(macro=macro_score, event=event_score,
                             industry=industry_score, company=company_score)
        four_by_symbol[stock.symbol] = four
        closes_by_symbol[stock.symbol] = bars[-1].close if bars else None
        output = engine.run(four, regime) if regime else engine.run(
            four, _neutral_regime())
        if regime is None:
            output.regime_note = "指数数据缺失：体制层无法判定，暂不增加风险"
        outputs[stock.symbol] = output

        analogy_note = ""
        if match_inputs:
            best = max(match_inputs, key=lambda mi: mi[0].similarity)
            analogy_note = f"最强类比 {best[0].event_id}（相似度 {best[0].similarity}，方向 {'负' if best[0].direction < 0 else '正'}）"
        case_evidence = []
        for match, age in match_inputs:
            hist = lib_by_id.get(match.event_id)
            if hist and match.similarity >= 0.6:
                impacts = [t.model_dump(mode="json") for t in hist.tickers_affected if t.ticker == stock.symbol]
                case_evidence.append({"event_id": hist.event_id, "similarity": match.similarity,
                                      "mechanism": hist.mechanism, "difference": match.difference,
                                      "ticker_metrics": impacts, "fizzled": hist.fizzled})
        if case_evidence:
            analogy_note = json.dumps(case_evidence, ensure_ascii=False)
        calendar = calendar_by_symbol[stock.symbol]
        valuation = assess_valuation(stock.valuation, bars, today)
        data_insufficient = (not company_score.indicators.get("fundamentals_ready") or not bars
                             or (today - bars[-1].date).days > 5
                             or (fin is not None and fin.period_end is not None
                                 and (today - fin.period_end).days > 550))
        regime_dates = {i.as_of for i in regime.indexes if i.as_of is not None} if regime else set()
        if regime and regime.vix_as_of is not None:
            regime_dates.add(regime.vix_as_of)
        market_mismatch = bool(bars and regime_dates and regime_dates != {bars[-1].date})
        if market_mismatch:
            data_insufficient = True
        if (data_insufficient or regime is None or event_data_unknown or calendar["unknown"]
                or clock.mode == "intraday_observe"
                or calendar["events"] or not valuation.allows_add):
            if output.band in ("积极", "中性偏多"):
                output.band = "中性偏空"
            output.position_cap = 0.0
            output.regime_note += "；证据不足或事件窗口：限制新增风险"
        degraded = [d for d in (macro_score, event_score, industry_score, company_score) if d.degraded]
        degraded_note = "；".join(d.degraded_note for d in degraded) if degraded else ""
        if event_data_note:
            degraded_note = "；".join(filter(None, [degraded_note, event_data_note]))

        ticker_ctx[stock.symbol] = {
            "total": output.weighted_total, "band": output.band,
            "scores": {"macro": four.macro.score, "event": four.event.score,
                       "industry": four.industry.score, "company": four.company.score},
            "analogy_note": analogy_note,
            "event_exposures": event_exposures,
            "degraded_note": degraded_note,
            "position": stock.position.value, "segment": stock.segment.value,
            "position_cap": output.position_cap,
            "company_gate": output.company_gate_applied,
            "valuation": valuation.model_dump(mode="json"),
            "data_insufficient": data_insufficient,
            "observation_only": clock.mode == "intraday_observe",
            "market_mismatch": market_mismatch,
            "calendar_unknown": calendar["unknown"],
            "event_window": bool(calendar["events"]),
            "event_desc": "、".join(e["name"] for e in calendar["events"]),
        }
        per_ticker_blocks.append(_format_ticker_block(stock, four, output, analogy_note, degraded_note, ticker_ctx[stock.symbol], weights))

    # ---- LLM 研判 ----
    ctx = _build_ctx(today, regime, macro_score, stocks, per_ticker_blocks)
    ctx["regime_unknown"] = regime is None
    ctx["event_data_unknown"] = event_data_unknown
    ctx["event_data_note"] = event_data_note
    result = llm.judge(ctx, ticker_ctx)
    result.generated_at = generated_at
    audit_input = {
        "version": "1.6-a", "generated_at": generated_at, "weights": weights,
        "analysis_clock": clock.model_dump(mode="json"),
        "stocks": [s.model_dump(mode="json") for s in stocks],
        "bars": {s: [b.model_dump(mode="json") for b in bars] for s, bars in bars_by_symbol.items()},
        "financials": {s: f.model_dump(mode="json") for s, f in financials.items()},
        "macro": {s: p.model_dump(mode="json") if p else None for s, p in macro_series.items()},
        "regime": regime.model_dump(mode="json") if regime else None,
        "events": [e.model_dump(mode="json") for e in recent_events],
        "historical_events": [e.model_dump(mode="json") for e in lib],
        "matches": [{"event_id": e.event_id, "matches": [m.model_dump(mode="json") for m in ms]}
                    for ms, e in per_event_matches],
        "calendar": calendar_by_symbol, "ticker_context": ticker_ctx,
        "model": settings.llm_model, "context": ctx,
    }
    from prompts.analysis import SYSTEM_PROMPT, build_analysis_prompt
    audit_input["prompt"] = {"system": SYSTEM_PROMPT, "user": build_analysis_prompt(ctx)}

    # ---- 落库（降级） ----
    db_saved = False
    run_id = None
    if not settings.mock_mode:
        try:
            from storage import repository
            for stock in stocks:
                output = outputs[stock.symbol]
                signal = next((s for s in result.signals if s.ticker == stock.symbol), None)
                repository.upsert_snapshot(repository.SnapshotRow(
                    snapshot_date=today, ticker=stock.symbol,
                    close=closes_by_symbol.get(stock.symbol),
                    signal=signal.action.value if signal else output.band,
                    confidence=signal.confidence if signal else None,
                    scores=four_by_symbol.get(stock.symbol),
                    analysis={  # 回测与同日回放所需字段（P0-3）
                        "signals": result.model_dump(mode="json")["signals"],
                        "market_summary": result.market_summary,
                        "regime_gate": output.regime_gate_applied,
                        "company_gate": output.company_gate_applied,
                        "position_cap": output.position_cap,
                        "band": output.band,
                        "valuation": ticker_ctx[stock.symbol]["valuation"],
                        "event_data_unknown": event_data_unknown,
                        "version": "1.6-a", "generated_at": generated_at,
                        "decision_at": clock.decision_at.isoformat(),
                        "price_session_limit": str(clock.price_session_limit),
                        "analysis_mode": clock.mode,
                        "source": ctx.get("result_source", "unknown"),
                        "price_date": str(bars_by_symbol[stock.symbol][-1].date) if bars_by_symbol.get(stock.symbol) else None,
                    },
                ))
            run_id = repository.append_analysis_run(
                audit_input,
                result.model_dump(mode="json"),
            )
            db_saved = True
        except Exception as exc:
            print(f"[pipeline] 落库失败（分析结果照常返回）：{exc}")

    return {"result": result, "outputs": outputs, "regime": regime,
            "db_saved": db_saved, "run_id": run_id, "cached": False,
            "audit_input": audit_input}


# ---------- 辅助 ----------


def _neutral_regime():
    from domain.scoring import IndexLevel, IndexRegime
    return IndexRegime(indexes=[IndexLevel(symbol="^GSPC", close=1, ma200=1)], vix=None)


def _load_lib():
    try:
        from events_lib.auto_sediment import load_matching_lib
        events = load_matching_lib()
    except Exception:
        try:
            events = load_seed_events()
        except Exception:
            return []
    if not settings.mock_mode:
        from events_lib.history_audit import enrich_from_initialized_history
        events = enrich_from_initialized_history(events)
    return events


def _active_current_events(today: date) -> list:
    from storage import repository
    return repository.list_active_current_events(as_of=today)


def _format_ticker_block(stock, four, output, analogy_note, degraded_note, policy=None, weights=None) -> str:
    policy = policy or {}
    from prompts.analysis import PER_TICKER_TEMPLATE
    indicators = {}
    for dim in (four.macro, four.event, four.industry, four.company):
        indicators.update({k: v for k, v in dim.indicators.items() if not k.startswith("sub_")})
    return PER_TICKER_TEMPLATE.format(
        ticker=stock.symbol, segment=stock.segment.value, position=stock.position.value,
        total=output.weighted_total, band=output.band,
        weights=str(weights or "0.25×4"), regime_gate="",
        position_cap=f"{output.position_cap:g}",
        macro=four.macro.score, event=four.event.score,
        industry=four.industry.score, company=four.company.score,
        rationales="\n  ".join(f"{d.rationale}" for d in
                               (four.macro, four.event, four.industry, four.company)),
        indicators=str(indicators),
        valuation=json.dumps(policy.get("valuation"), ensure_ascii=False),
        analogy=analogy_note or "无命中",
        event_window=policy.get("event_window", False), event_desc=policy.get("event_desc", ""),
        x_summary="X 情绪尚未接入评分",
        degraded=degraded_note or "无",
    )


def _build_ctx(today, regime, macro_score, stocks, per_ticker_blocks) -> dict:
    from prompts.analysis import build_regime_desc
    return {
        "date": f"{today:%Y-%m-%d}",
        "regime_gate": bool(regime and regime.regime_broken()),
        "regime_desc": build_regime_desc(regime),
        "macro_summary": macro_score.rationale,
        "pool_desc": "；".join(f"{s.symbol}({s.segment.value}/{s.position.value})" for s in stocks),
        "per_ticker": "\n\n".join(per_ticker_blocks),
        "regime_note": "见体制层描述",
        "llm_degraded": not llm.llm_available(),
        "macro_summary_text": macro_score.rationale,
    }
