"""First v1.6 tranche: completed daily evidence and explicit event exposure."""

from datetime import date, datetime, timezone

from domain.asof import analysis_clock, completed_bars
from domain.events import CurrentEvent, EventCategory, EventScope
from domain.stock import DailyBar
from events_lib.exposure import exposure_for
from analyzer import evaluation
from analyzer.constraints import enforce
from domain.signal import Action, AnalysisResult, TickerSignal


def _event(scope: EventScope, tickers: list[str]) -> CurrentEvent:
    return CurrentEvent(event_id="test", title="test", scope=scope,
                        category=EventCategory.TECH, summary="test",
                        tickers_mentioned=tickers, source="test")


def _bar(day: date) -> DailyBar:
    return DailyBar(date=day, open=1, high=1, low=1, close=1)


def test_intraday_excludes_current_partial_daily_bar():
    clock = analysis_clock(now=datetime(2026, 10, 22, 18, tzinfo=timezone.utc))
    assert clock.price_session_limit == date(2026, 10, 21)
    assert clock.mode == "intraday_observe"
    assert [b.date for b in completed_bars([_bar(date(2026, 10, 21)),
                                            _bar(date(2026, 10, 22))], clock)] == [date(2026, 10, 21)]


def test_post_close_accepts_completed_daily_bar():
    clock = analysis_clock(now=datetime(2026, 10, 22, 22, tzinfo=timezone.utc))
    assert clock.price_session_limit == date(2026, 10, 22)


def test_intraday_observation_cannot_add_even_with_passing_valuation():
    raw = AnalysisResult(generated_at="2026-10-22", market_summary="test", signals=[
        TickerSignal(ticker="NVDA", action=Action.ACCUMULATE, confidence=.9, reason="test")])
    data = {"NVDA": {"observation_only": True,
                     "valuation": {"status": "passed", "allows_add": True, "reason": "reviewed"}}}
    signal = enforce(raw, raw, {}, data).signals[0]
    assert signal.action == Action.WATCH and signal.position_cap == 0


def test_company_event_does_not_spread_to_unrelated_stock():
    event = _event(EventScope.COMPANY, ["NVDA"])
    assert exposure_for(event, "NVDA") is not None
    assert exposure_for(event, "AMD") is None


def test_industry_event_requires_explicit_link_and_macro_is_shared():
    event = _event(EventScope.INDUSTRY, ["NVDA"])
    assert exposure_for(event, "AMD", "gpu") is None
    assert exposure_for(_event(EventScope.MACRO_POLICY, []), "AMD").route == "market"


def test_new_run_records_keep_same_day_revisions(monkeypatch):
    from storage import repository
    payload = {"version": "1.6-a", "analysis_clock": {"decision_at": "2026-10-22T21:35:00+00:00"},
               "bars": {"NVDA": [{"date": "2026-10-22", "close": 100}]},
               "ticker_context": {"NVDA": {"band": "积极"}},
               "context": {"result_source": "rule", "regime_gate": False}}
    runs = [{"run_id": n, "input": payload, "result": {"signals": [
        {"ticker": "NVDA", "action": "watch", "confidence": .5}]}} for n in (1, 2)]
    monkeypatch.setattr(repository, "list_analysis_runs", lambda since: runs)
    records = evaluation.load_signal_records(since=date(2026, 10, 22))
    assert [r["run_id"] for r in records] == [1, 2]
    assert all(r["execution_policy"] == "next_open" for r in records)


def test_post_close_signal_uses_next_open_not_signal_close():
    from tests.test_evaluation import FakeMarket
    monday = date(2026, 1, 5)
    bars = []
    day = monday
    for n in range(30):
        while day.weekday() >= 5:
            day = day.fromordinal(day.toordinal() + 1)
        close = 100 + n
        open_price = 200 if n == 4 else close
        bars.append(DailyBar(date=day, open=open_price, high=max(open_price, close),
                             low=min(open_price, close), close=close))
        day = day.fromordinal(day.toordinal() + 1)
    record = {"run_id": 4, "ticker": "NVDA", "date": bars[3].date,
              "decision_at": "2026-01-08T21:35:00+00:00", "execution_policy": "next_open",
              "action": "watch", "band": "中性偏空", "confidence": .5,
              "close": bars[3].close, "regime_gate": False, "source": "rule"}
    assert evaluation.attach_forward_returns([record], FakeMarket({"NVDA": bars})) == 0
    assert record["entry_date"] == bars[4].date
    assert record["entry_price"] == 200
    assert record["fwd_5d"] == (bars[8].close / 200 - 1) * 100


def test_pipeline_records_only_verified_current_event_exposure(monkeypatch):
    from analyzer import pipeline
    from collectors.mock import MockMarket, MockMacro
    from domain.stock import StockConfig

    monkeypatch.setattr(pipeline.settings, "mock_mode", True)
    monkeypatch.setattr(pipeline, "load_stocks", lambda: [StockConfig(symbol="NVDA"),
                                                           StockConfig(symbol="AMD")])
    monkeypatch.setattr(pipeline, "get_market", MockMarket)
    monkeypatch.setattr(pipeline, "get_macro", MockMacro)
    monkeypatch.setattr(pipeline, "_active_current_events", lambda **kw: [
        _event(EventScope.COMPANY, ["NVDA"]).model_copy(update={"occurred_date": pipeline.market_today()})])
    monkeypatch.setattr(pipeline.llm, "llm_available", lambda: False)
    outcome = pipeline.run_analysis()
    ctx = outcome["audit_input"]["ticker_context"]
    assert ctx["NVDA"]["event_exposures"][0]["route"] == "direct"
    assert ctx["AMD"]["event_exposures"] == []
