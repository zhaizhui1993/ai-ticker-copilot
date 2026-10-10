"""P0 regression: article provenance, active risk coverage, valuation admission."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from analyzer import llm, pipeline
from analyzer.rule_extract import extract_events
from analyzer.schemas import EventBatch, ExtractedEvent
from domain.events import CurrentEvent, EventMatchResult, RawArticle
from domain.signal import AnalysisResult, TickerSignal
from domain.stock import DailyBar, StockConfig
from domain.valuation import ValuationEvidence
from events_lib.identity import article_hash
from scoring.valuation import assess_valuation

TODAY = date(2026, 10, 9)


def article(title="NVDA earnings beat", **kwargs):
    return RawArticle(source="original", raw_url="https://example.com/" + title,
                      title=title, fetched_at=datetime(2026, 10, 9, 2, tzinfo=timezone.utc), **kwargs)


def valuation(**kwargs):
    values = dict(method="scenario", conservative_value=100, as_of=TODAY - timedelta(days=2),
                  valid_until=TODAY + timedelta(days=30), minimum_margin=.2,
                  assumptions=["测试假设：收入增长与股本摊薄"], sources=["测试财报页码"],
                  rationale="测试熊市情景的每股价值", reviewed=True)
    return ValuationEvidence(**{**values, **kwargs})


def bars(price=75, day=TODAY):
    return [DailyBar(date=day, open=price, high=price, low=price, close=price)]


class Chat:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, *args, **kwargs):
        return self.result


def use_llm(monkeypatch, result):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_chat", lambda: Chat(result))


def test_ids_distinct_between_polls_stable_on_restart_and_unknown_date():
    a, b = article(), article("AMD earnings beat")
    first = extract_events([a], ["NVDA"], today=TODAY)[0]
    later = extract_events([b], ["AMD"], today=TODAY)[0]
    repeated = extract_events([a], ["NVDA"], seq_start=99, today=TODAY + timedelta(days=2))[0]
    assert first.event_id != later.event_id
    assert repeated.event_id == first.event_id
    assert first.article_id == article_hash(a.raw_url, a.title)
    assert first.occurred_date is None
    assert first.date_basis == "fetched" and first.reference_date == date(2026, 10, 8)


def test_published_and_fetched_dates_use_eastern_calendar():
    a = article(published_at=datetime(2026, 10, 8, 1, tzinfo=timezone.utc))
    event = extract_events([a], ["NVDA"])[0]
    assert event.reference_date == date(2026, 10, 7)
    assert event.date_basis == "published"
    assert event.published_at != event.fetched_at
    restored = CurrentEvent.model_validate_json(event.model_dump_json())
    assert restored.evidence == [a]
    assert restored.reference_date == event.reference_date


def test_rss_keeps_publication_timestamp(monkeypatch):
    from collectors import news
    now = datetime.now(timezone.utc)
    entry = SimpleNamespace(title="NVDA earnings", summary="data center", link="https://example.com/rss",
                            published_parsed=now.utctimetuple())
    monkeypatch.setattr(news.feedparser, "parse", lambda _: SimpleNamespace(entries=[entry]))
    a = news._fetch_feed("source", "feed")[0]
    assert a.published_at == now.replace(microsecond=0)
    assert a.fetched_at >= a.published_at


def test_llm_rewritten_title_keeps_original_identity_and_correct_source(monkeypatch):
    a, b = article(), article("AMD earnings beat")
    b.source = "second source"
    fake = EventBatch(events=[ExtractedEvent(article_index=2, title="改写标题", scope="company", category="tech",
                                            raw_url="https://forged.example", occurred_date=TODAY)])
    use_llm(monkeypatch, fake)
    result = llm.extract_events([a, b], ["NVDA", "AMD"])
    event = next(e for e in result if e.title == "改写标题")
    assert event.source == b.source and event.raw_url == b.raw_url
    assert event.article_id == article_hash(b.raw_url, b.title)
    assert event.event_id == extract_events([b], ["AMD"])[0].event_id
    assert event.occurred_date is None  # A model date without an exact source quote is not evidence.
    assert len(result) == 2  # The omitted rule-relevant article survives.


@pytest.mark.parametrize("indices", [[3], [1, 1]])
def test_invalid_llm_article_references_fall_back(monkeypatch, indices):
    articles = [article(), article("AMD earnings beat")]
    use_llm(monkeypatch, EventBatch(events=[ExtractedEvent(article_index=i, title="rewritten", scope="company",
                                                         category="tech") for i in indices]))
    assert llm.extract_events(articles, []) == extract_events(articles, [])


def test_llm_actual_date_requires_verbatim_date_context(monkeypatch):
    a = article(summary="NVDA reported earnings on 2026-10-07.")
    use_llm(monkeypatch, EventBatch(events=[ExtractedEvent(
        article_index=1, title="earnings", scope="company", category="tech", occurred_date=date(2026, 10, 7),
        occurred_date_quote=a.summary)]))
    event = llm.extract_events([a], ["NVDA"])[0]
    assert event.occurred_date == date(2026, 10, 7)
    assert event.date_basis == "occurred" and event.occurred_date_quote == a.summary


def test_scheduled_date_is_not_treated_as_actual_occurrence(monkeypatch):
    a = article(summary="NVDA will report earnings on 2026-10-20.")
    use_llm(monkeypatch, EventBatch(events=[ExtractedEvent(
        article_index=1, title="earnings", scope="company", category="tech", occurred_date=date(2026, 10, 20),
        occurred_date_quote=a.summary)]))
    event = llm.extract_events([a], ["NVDA"], today=TODAY)[0]
    assert event.occurred_date is None and event.date_basis == "fetched"


def test_old_event_payload_remains_readable():
    old = CurrentEvent(event_id="2026-09-01-001", title="old policy", occurred_date=date(2026, 9, 1),
                       scope="geopolitical", category="regulation", summary="legacy", source="legacy")
    assert old.status == "active" and old.impact_date == old.occurred_date


def test_decay_uses_current_policy_type_not_short_lived_historical_analog():
    from scoring.event_score import EventScorer
    match = EventMatchResult(event_id="tech-analog", current_event_id="policy", current_category="regulation",
                             similarity=1, direction=-1, magnitude=.5, affected_tickers=["NVDA"])
    scorer = EventScorer()
    actual = scorer.score("NVDA", [(match, 90)], category_by_event={"tech-analog": "tech"})
    reference = scorer.score("NVDA", [(match.model_copy(update={"current_category": None}), 90)],
                             category_by_event={"tech-analog": "regulation"})
    assert actual.score == reference.score < 50


def test_unknown_date_skips_automatic_historical_sedimentation(monkeypatch):
    from events_lib import auto_sediment
    from storage import repository
    monkeypatch.setattr(repository, "list_current_events", lambda **kw: extract_events([article()], []))
    monkeypatch.setattr(repository, "list_events", lambda: [])
    monkeypatch.setattr(auto_sediment, "_pool_tickers", lambda: [])
    assert auto_sediment.sediment_due_events(TODAY + timedelta(days=60)) == []


@pytest.mark.parametrize("overrides,status", [
    ({"reviewed": False}, "unreviewed"),
    ({"valid_until": TODAY - timedelta(days=1)}, "expired"),
    ({"as_of": TODAY + timedelta(days=1)}, "future"),
    ({"conservative_value": 80}, "insufficient_margin"),
])
def test_valuation_failures_are_closed(overrides, status):
    result = assess_valuation(valuation(**overrides), bars(), TODAY)
    assert result.status == status and not result.allows_add


@pytest.mark.parametrize("price,day", [(0, TODAY), (-1, TODAY), (float("nan"), TODAY),
                                      (float("inf"), TODAY), (75, TODAY - timedelta(days=6)),
                                      (75, TODAY + timedelta(days=1))])
def test_invalid_prices_never_unlock(price, day):
    result = assess_valuation(valuation(), bars(price, day), TODAY)
    assert result.status == "invalid_price" and not result.allows_add
    result.model_dump_json()  # No NaN / infinity escapes through JSON output.


@pytest.mark.parametrize("overrides", [{"conservative_value": 0}, {"conservative_value": float("inf")},
                                       {"minimum_margin": -1}, {"minimum_margin": 1},
                                       {"minimum_margin": float("nan")}, {"assumptions": ["  "]},
                                       {"sources": []}, {"rationale": "  "},
                                       {"valid_until": TODAY - timedelta(days=3)}])
def test_malformed_valuation_rejected_before_analysis(overrides):
    with pytest.raises(ValidationError):
        valuation(**overrides)


def test_safety_margin_boundary_alternative_methods_and_no_default_threshold():
    for method in ("dcf", "multiples", "scenario", "sotp"):
        result = assess_valuation(valuation(method=method), bars(80), TODAY)
        assert result.allows_add and result.margin == .2
    assert not assess_valuation(valuation(), bars(80.01), TODAY).allows_add
    assert assess_valuation(None, bars(), TODAY).status == "missing"
    values = valuation().model_dump()
    values.pop("minimum_margin")
    with pytest.raises(ValidationError):
        ValuationEvidence(**values)


def ticker_data(evidence=None):
    return {"NVDA": {"total": 90, "band": "积极", "scores": dict(macro=90, event=90, industry=90, company=90),
                     "valuation": assess_valuation(evidence, bars(), TODAY).model_dump(mode="json")}}


@pytest.mark.parametrize("action", ["accumulate", "watch_add", "reduce"])
def test_llm_cannot_forge_valuation_and_reduce_is_preserved(monkeypatch, action):
    raw = AnalysisResult(generated_at=str(TODAY), market_summary="test", signals=[TickerSignal(
        ticker="NVDA", action=action, confidence=.99, reason="应该立即增加风险", price_target_hint="买入",
        valuation=assess_valuation(valuation(), bars(), TODAY))])
    use_llm(monkeypatch, raw)
    from prompts import analysis
    monkeypatch.setattr(analysis, "build_analysis_prompt", lambda _: "test")
    ctx = {}
    result = llm.judge(ctx, ticker_data()).signals[0]
    assert result.action.value == ("reduce" if action == "reduce" else "watch")
    assert result.position_cap == 0 and result.valuation.status == "missing"
    if action != "reduce":
        assert "应该立即增加风险" not in result.reason and result.price_target_hint is None
    assert "估值" in result.reason
    assert ctx["raw_result"]["signals"][0]["action"] == action


def test_rule_path_positive_pe_and_score_cannot_replace_valuation():
    assert llm.rule_judge({}, ticker_data()).signals[0].action.value == "watch"
    data = ticker_data(valuation(method="scenario"))
    # A loss-making company can provide scenario evidence without a positive PE.
    data["NVDA"]["pe_ttm"] = -10
    assert llm.rule_judge({}, data).signals[0].action.value == "accumulate"
    for gate in ("regime_unknown", "event_data_unknown"):
        assert llm.rule_judge({gate: True}, data).signals[0].position_cap == 0


def test_pipeline_retains_old_policy_and_blocks_event_read_failure(monkeypatch):
    from collectors.mock import MockMarket, MockMacro
    from events_lib.calendar import market_today
    today = market_today()
    class Market(MockMarket):
        def get_daily_bars(self, ticker, days):
            values = super().get_daily_bars(ticker, days)
            delta = today - values[-1].date
            return [b.model_copy(update={"date": b.date + delta}) for b in values]
    monkeypatch.setattr(pipeline.settings, "mock_mode", True)
    monkeypatch.setattr(pipeline, "load_stocks", lambda: [StockConfig(symbol="NVDA", valuation=valuation(
        conservative_value=10000, as_of=today - timedelta(days=10), valid_until=today + timedelta(days=30)))])
    monkeypatch.setattr(pipeline, "get_market", Market)
    monkeypatch.setattr(pipeline, "get_macro", MockMacro)
    monkeypatch.setattr(pipeline.llm, "llm_available", lambda: False)
    monkeypatch.setattr(pipeline, "event_calendar", lambda *a: {"unknown": False, "events": []})
    policy = extract_events([article("Chip export control")], ["NVDA"])[0]
    policy.occurred_date = today - timedelta(days=90)
    monkeypatch.setattr(pipeline, "_active_current_events", lambda **kw: [policy])
    result = pipeline.run_analysis()
    assert result["audit_input"]["matches"][0]["event_id"] == policy.event_id
    assert not result["audit_input"]["context"]["event_data_unknown"]
    assert result["result"].signals[0].valuation.allows_add
    assert "估值证据" in result["audit_input"]["prompt"]["user"]

    def unavailable(**kw):
        raise RuntimeError("DB unavailable")
    monkeypatch.setattr(pipeline, "_active_current_events", unavailable)
    result = pipeline.run_analysis()
    assert result["audit_input"]["context"]["event_data_unknown"]
    assert result["result"].signals[0].position_cap == 0
    assert result["outputs"]["NVDA"].position_cap == 0
