"""P0 API integration: config preservation, lifecycle validation, safe persisted output."""
from datetime import timedelta
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from domain.stock import StockConfig
from storage import repository
from tests.test_p0_evidence import TODAY, valuation


def test_stock_api_preserves_evidence_for_old_clients_and_validates_before_write(tmp_path, monkeypatch):
    from config import loader
    from web.api import stocks
    monkeypatch.setattr(loader, "CONFIG_DIR", tmp_path)
    target = tmp_path / "stocks.yaml"
    original = StockConfig(symbol="NVDA", valuation=valuation()).model_dump(mode="json")
    target.write_text(yaml.safe_dump({"stocks": [original]}))
    app = FastAPI()
    app.include_router(stocks.router)
    client = TestClient(app)
    response = client.put("/api/stocks", json={"stocks": [{"symbol": "NVDA", "position": "holding"}]})
    assert response.status_code == 200
    assert loader.load_stocks()[0].valuation == valuation()
    assert client.get("/api/stocks").json()["stocks"][0]["valuation"]["as_of"] == str(valuation().as_of)

    before = target.read_text()
    response = client.put("/api/stocks", json={"stocks": [{"symbol": "NVDA", "valuation": {
        **original["valuation"], "conservative_value": -100}}]})
    assert response.status_code == 422 and target.read_text() == before
    response = client.put("/api/stocks", json={"stocks": [{"symbol": "NVDA", "valuation": None}]})
    assert response.status_code == 200 and loader.load_stocks()[0].valuation is None


def test_event_api_validation_and_failure_do_not_claim_success(monkeypatch):
    from web.api import events
    app = FastAPI()
    app.include_router(events.router)
    client = TestClient(app)
    called = []

    def missing(event_id, **kwargs):
        called.append((event_id, kwargs))
        raise KeyError(event_id)
    monkeypatch.setattr(repository, "change_event", missing)
    assert client.patch("/api/events/id/status", json={"status": "merged", "reason": "why"}).status_code == 422
    assert not called
    assert client.patch("/api/events/id/status", json={"status": "resolved", "reason": "review"}).status_code == 404
    assert called[-1] == ("id", {"status": "resolved", "reason": "review"})
    assert client.post("/api/events/id/merge", json={"target_event_id": "target", "reason": "duplicate"}).status_code == 404
    assert called[-1] == ("id", {"merge_into": "target", "reason": "duplicate"})

    def unavailable(*args, **kwargs):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(repository, "change_event", unavailable)
    assert client.patch("/api/events/id/status", json={"status": "active", "reason": "review"}).status_code == 503


@pytest.mark.parametrize("version,evidence", [("1.4", valuation()), ("1.5", None),
                                              ("1.5", valuation(valid_until=TODAY - timedelta(days=1)))])
def test_dashboard_does_not_republish_old_or_expired_add_signals(monkeypatch, version, evidence):
    from web.api import dashboard
    from collectors.mock import MockMarket
    stock = StockConfig(symbol="NVDA", valuation=evidence)
    monkeypatch.setattr(dashboard, "load_stocks", lambda: [stock])
    monkeypatch.setattr(dashboard, "market_today", lambda: TODAY)
    monkeypatch.setattr(dashboard, "get_market", MockMarket)
    monkeypatch.setattr(repository, "get_snapshots", lambda *a, **kw: [repository.SnapshotRow(
        snapshot_date=TODAY, ticker="NVDA", close=75, signal="accumulate", analysis={"version": version})])
    card = dashboard.dashboard()["cards"][0]
    assert card["signal"] == "watch" and card["signal_note"]


def test_pipeline_persists_serializable_valuation_and_audit(monkeypatch):
    from analyzer import pipeline
    from collectors.mock import MockMarket, MockMacro
    from events_lib.calendar import market_today
    from events_lib.loader import load_seed_events
    today = market_today()

    class Market(MockMarket):
        def get_daily_bars(self, ticker, days):
            values = super().get_daily_bars(ticker, days)
            delta = today - values[-1].date
            return [b.model_copy(update={"date": b.date + delta}) for b in values]
    monkeypatch.setattr(pipeline.settings, "mock_mode", False)
    monkeypatch.setattr(pipeline, "load_stocks", lambda: [StockConfig(symbol="NVDA", valuation=valuation(
        as_of=today - timedelta(days=1), valid_until=today + timedelta(days=7), conservative_value=10000))])
    monkeypatch.setattr(pipeline, "get_market", Market)
    monkeypatch.setattr(pipeline, "get_macro", MockMacro)
    monkeypatch.setattr(pipeline, "_load_lib", load_seed_events)
    monkeypatch.setattr(pipeline, "_active_current_events", lambda **kw: [])
    monkeypatch.setattr(pipeline, "event_calendar", lambda *a: {"unknown": False, "events": []})
    monkeypatch.setattr(pipeline.llm, "llm_available", lambda: False)
    snapshots, audit = [], []
    monkeypatch.setattr(repository, "upsert_snapshot", snapshots.append)
    monkeypatch.setattr(repository, "append_analysis_run", lambda i, r: audit.append((i, r)))
    result = pipeline.run_analysis()
    assert result["db_saved"] and snapshots[0].analysis["valuation"]["status"] == "passed"
    assert audit[0][1]["signals"][0]["valuation"]["evidence"]["as_of"] == str(today - timedelta(days=1))
    json.dumps(snapshots[0].analysis, allow_nan=False)
    json.dumps(audit, allow_nan=False)
