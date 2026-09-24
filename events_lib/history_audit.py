"""Coverage audit and reproducible, non-causal event-window observations."""
from collections import Counter
from datetime import date

from events_lib.pre_state import compute_pre_state
from events_lib.linkage import compute_linkage

DEFAULT_TICKERS = ("NVDA", "LITE", "MRVL", "INTC", "COHR", "AMD", "GOOGL", "BE")
PRE_FIELDS = ("pre_drawdown_52w", "pre_bias_ma200", "pre_runup_20d", "pre_rsi14")


def audit(events, tickers=DEFAULT_TICKERS):
    rows = []
    for ticker in tickers:
        aliases = {"GOOG", "GOOGL"} if ticker in {"GOOG", "GOOGL"} else {ticker}
        pairs = [(e, t) for e in events for t in e.tickers_affected if t.ticker in aliases]
        rows.append({"ticker": ticker, "events": len({e.event_id for e, _ in pairs}),
                     "pre_state_complete": sum(all(getattr(t, f) is not None for f in PRE_FIELDS) for _, t in pairs),
                     "drawdown_known": sum(t.drawdown is not None for _, t in pairs),
                     "recovery_known": sum(t.recovery_days is not None for _, t in pairs),
                     "fizzled": len({e.event_id for e, _ in pairs if e.fizzled})})
    return {"event_count": len(events), "categories": dict(Counter(e.category.value for e in events)),
            "fizzled": sum(e.fizzled for e in events), "tickers": rows,
            "conclusion": "可作案例检索；条数不证明统计充分，需独立机制、周期与对照覆盖。",
            "limitations": ["GOOG/GOOGL 在覆盖统计中合并，行情不混用", "恢复天数为空不等于尚未恢复，可能尚未回填",
                            "缺少历史财务和估值时点证据，禁止以今日财务值回填历史"]}


def observations(events, ticker, bars, as_of: date):
    bars = sorted((b for b in bars if b.date <= as_of), key=lambda b: b.date)
    result = []
    for event in events:
        if event.start_date > as_of:
            continue
        pre = [b for b in bars if b.date < event.start_date]
        post = [b for b in bars if b.date >= event.start_date]
        state = compute_pre_state(bars, event.start_date)
        link = compute_linkage(bars, event.start_date) if len(pre) >= 30 and post else None
        # Require an observation just before the event; do not align a pre-IPO event to IPO day.
        valid = bool(pre and post and (event.start_date - pre[-1].date).days <= 7
                     and (post[0].date - event.start_date).days <= 7)
        forwards = {}
        for h in (1, 5, 20, 60):
            forwards[f"return_{h}d"] = (post[h - 1].close / pre[-1].close - 1) * 100 if valid and len(post) >= h else None
        result.append({"event_id": event.event_id, "ticker": ticker,
                       "role": "observed_window_not_causal_attribution", "event_date": str(event.start_date),
                       "pre_date": str(pre[-1].date) if valid else None,
                       "pre_state": state if valid else None,
                       "outcome": link if valid else None, "returns": forwards,
                       "post_sessions": min(len(post), 181) if valid else 0,
                       "outcome_window_complete": valid and len(post) >= 181,
                       "status": "observed" if valid else "insufficient_or_not_listed",
                       "fundamentals_status": "requires_point_in_time_filings"})
    return result


def enrich_from_initialized_history(events, root=None):
    """Fill missing metrics only for existing causal labels; never add ticker associations."""
    import json
    from pathlib import Path
    root = Path(root) if root else Path(__file__).resolve().parents[1] / "data/history"
    enriched = [e.model_copy(deep=True) for e in events]
    cache = {}
    for event in enriched:
        for impact in event.tickers_affected:
            ticker = impact.ticker
            if ticker not in cache:
                try:
                    payload = json.loads((root / f"{ticker}.json").read_text())
                    if payload.get("version") != "1.4" or payload.get("source") != "yfinance auto_adjust=True":
                        raise ValueError("unverified source")
                    cache[ticker] = {r["event_id"]: r for r in payload["events"] if r["ticker"] == ticker}
                except (OSError, ValueError, KeyError, TypeError):
                    cache[ticker] = {}
            row = cache[ticker].get(event.event_id)
            if not row or row.get("event_date") != str(event.start_date) or row.get("status") != "observed":
                continue
            fields = dict(row.get("pre_state") or {})
            if row.get("outcome_window_complete"):
                fields.update({k: v for k, v in (row.get("outcome") or {}).items()
                               if k in {"drawdown", "drawdown_days", "recovery_days"}})
            changed = False
            for key, value in fields.items():
                if key in {*PRE_FIELDS, "drawdown", "drawdown_days", "recovery_days"} and getattr(impact, key) is None and value is not None:
                    setattr(impact, key, value)
                    changed = True
            if changed:
                impact.metric_source = "data/history: yfinance adjusted daily; v1.4; existing values preserved"
    return enriched
