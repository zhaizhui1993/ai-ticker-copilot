"""Regression tests for evidence quality, hard policy, and historical observations."""
from datetime import date, timedelta
import json

from domain.stock import Financials, DailyBar
from domain.scoring import MacroPoint
from domain.signal import Action, AnalysisResult, TickerSignal
from domain.events import EventMatchResult
from scoring.company_score import CompanyScorer
from scoring.event_score import EventScorer
from scoring.macro_score import MacroScorer
from analyzer.constraints import enforce
from events_lib.calendar import event_calendar
from events_lib.history_audit import observations
from events_lib.loader import load_seed_events


def test_missing_fcf_is_not_negative_and_zero_roe_is_not_missing():
    scorer = CompanyScorer()
    base = Financials(revenue_yoy=30, pe_ttm=40, gross_margin=60, roe=0)
    unknown = scorer.score("TEST", [], base)
    negative = scorer.score("TEST", [], base.model_copy(update={"fcf_positive": False}))
    assert unknown.indicators["质量"] > negative.indicators["质量"]
    assert not unknown.indicators["fundamentals_ready"]
    assert scorer.score("TEST", [], base.model_copy(update={"roe": None})).indicators["质量"] != unknown.indicators["质量"]


def test_current_event_analogs_normalized_and_deduplicated():
    scorer = EventScorer()
    one = EventMatchResult(event_id="a", current_event_id="now", similarity=1,
                           direction=-1, magnitude=.5, affected_tickers=["NVDA"])
    baseline = scorer.score("NVDA", [(one, 0)]).score
    assert scorer.score("NVDA", [(one, 0), (one, 0)]).score == baseline
    other = one.model_copy(update={"event_id": "b"})
    assert scorer.score("NVDA", [(one, 0), (other, 0)]).score == baseline
    weak = one.model_copy(update={"similarity": .5})
    assert scorer.score("NVDA", [(weak, 0)]).score == 50


def _result(signals):
    return AnalysisResult(generated_at="2026-09-24", market_summary="test", signals=signals)


def _signal(ticker="NVDA"):
    return TickerSignal(ticker=ticker, action=Action.ACCUMULATE, confidence=.99,
                        reason="test", position_cap=1)


def test_constraints_reject_outside_tickers_duplicate_and_missing():
    fallback = _result([_signal(), _signal("AMD")])
    raw = _result([_signal(), _signal(), _signal("OUT")])
    out = enforce(raw, fallback, {"regime_gate": True}, {"NVDA": {}, "AMD": {}})
    assert [s.ticker for s in out.signals] == ["NVDA", "AMD"]
    assert all(s.action == Action.WATCH_ADD and s.position_cap == .3 for s in out.signals)


def test_unknown_data_and_event_window_block_additions():
    result = _result([_signal()])
    for global_ctx, local_ctx in [({"regime_unknown": True}, {}), ({}, {"data_insufficient": True}),
                                  ({}, {"event_window": True, "event_desc": "财报"}),
                                  ({}, {"calendar_unknown": True})]:
        s = enforce(result, result, global_ctx, {"NVDA": local_ctx}).signals[0]
        assert s.action == Action.WATCH and s.position_cap == 0


def test_cpi_uses_actual_year_ago_observation():
    p = MacroPoint(series_id="CPIAUCSL", as_of="2026-08-01", value=103,
                   prev_value=103, year_ago_value=100)
    assert MacroScorer._cpi_yoy_proxy(p) == 3
    assert MacroScorer._cpi_yoy_proxy(p.model_copy(update={"year_ago_value": None})) is None


def test_calendar_shared_window_and_unknown_year():
    class Market:
        def get_earnings_dates(self, ticker):
            return [date(2026, 10, 27)]
    result = event_calendar(Market(), "NVDA", date(2026, 10, 25))
    assert {e["type"] for e in result["events"]} == {"earnings", "FOMC"}
    assert event_calendar(Market(), "NVDA", date(2027, 1, 1))["unknown"]


def test_history_does_not_align_pre_ipo_event_to_later_price():
    event = load_seed_events()[0].model_copy(update={"start_date": date(2000, 1, 1)})
    bars = [DailyBar(date=date(2010, 1, 1) + timedelta(days=i), open=100, high=100,
                     low=100, close=100) for i in range(300)]
    row = observations([event], "TEST", bars, date(2026, 1, 1))[0]
    assert row["status"] == "insufficient_or_not_listed"
    assert all(v is None for v in row["returns"].values())


def test_pipeline_passes_full_basket_and_serializable_audit(monkeypatch):
    from analyzer import pipeline
    from collectors.mock import MockMarket, MockMacro
    from domain.stock import StockConfig
    monkeypatch.setattr(pipeline.settings, "mock_mode", True)
    monkeypatch.setattr(pipeline, "load_stocks", lambda: [StockConfig(symbol="LITE", segment="optical")])
    monkeypatch.setattr(pipeline, "get_market", MockMarket)
    monkeypatch.setattr(pipeline, "get_macro", MockMacro)
    monkeypatch.setattr(pipeline, "_recent_current_events", lambda **kw: [])
    monkeypatch.setattr(pipeline.llm, "llm_available", lambda: False)
    result = pipeline.run_analysis(refresh=True)
    audit = result["audit_input"]
    assert {"LITE", "COHR", "SPY"} <= audit["bars"].keys()
    assert {"LITE", "COHR"} <= audit["financials"].keys()
    assert audit["prompt"]["system"]
    json.dumps(audit)


def test_calibration_reduce_success_uses_negative_excess():
    from analyzer.evaluation import report_calibration
    report = report_calibration([{"action": "reduce", "confidence": .9, "source": "llm",
                                  "fwd_20d": -4, "excess_20d": -2}])
    assert "动作成功率 100.0%" in report


def test_benchmark_excludes_tickers_not_in_that_days_pool():
    from analyzer.evaluation import attach_forward_returns
    from tests.test_evaluation import _two_ticker_setup
    records, market, bars = _two_ticker_setup()
    records[1]["date"] = bars["DN"][11].date
    attach_forward_returns(records, market)
    assert abs(records[0]["excess_5d"]) < 1e-10


def test_initialized_metrics_fill_only_existing_labels_and_preserve_manual_values(tmp_path):
    from events_lib.history_audit import enrich_from_initialized_history
    from tests.test_pre_state import _hist_event
    event = _hist_event()
    payload = {"version": "1.4", "source": "yfinance auto_adjust=True", "events": [{
        "event_id": event.event_id, "ticker": "NVDA", "event_date": str(event.start_date),
        "status": "observed", "pre_state": {"pre_bias_ma200": 99, "pre_rsi14": 44},
        "outcome_window_complete": False, "outcome": {"drawdown": -80}}]}
    (tmp_path / "NVDA.json").write_text(json.dumps(payload))
    enriched = enrich_from_initialized_history([event], tmp_path)[0]
    assert len(enriched.tickers_affected) == len(event.tickers_affected)
    assert enriched.tickers_affected[0].pre_bias_ma200 == -15  # manual preserved
    assert enriched.tickers_affected[0].pre_rsi14 == 44
    assert enriched.tickers_affected[0].drawdown is None  # immature observation not imported
    assert event.tickers_affected[0].pre_rsi14 is None  # original not mutated


def test_real_llm_path_cannot_bypass_final_policy(monkeypatch):
    from analyzer import llm
    class Chat:
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, *args, **kwargs):
            return _result([_signal(), _signal("OUTSIDE")])
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_chat", Chat)
    from prompts import analysis
    monkeypatch.setattr(analysis, "build_analysis_prompt", lambda ctx: "test")
    context = {"regime_gate": True}
    data = {"NVDA": {"total": 85, "band": "积极", "scores": {
        "macro": 85, "event": 85, "industry": 85, "company": 85}}}
    result = llm.judge(context, data)
    assert len(result.signals) == 1
    assert result.signals[0].action == Action.WATCH_ADD
    assert result.signals[0].position_cap == .3
    assert context["raw_result"]["signals"][0]["action"] == "accumulate"


def test_event_analog_count_does_not_raise_same_quality_evidence():
    scorer = EventScorer()
    match = EventMatchResult(event_id="one", current_event_id="current", similarity=.8,
                             direction=-1, magnitude=.5, affected_tickers=["NVDA"])
    other = match.model_copy(update={"event_id": "two"})
    assert scorer.score("NVDA", [(match, 0)]).score == scorer.score("NVDA", [(match, 0), (other, 0)]).score
