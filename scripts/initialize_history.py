"""Audit seed + persisted events; optionally initialize real price history without altering seeds.

Default is offline audit. --include-db merges stored seed/user/auto events (drafts counted separately).
--initialize downloads adjusted daily prices once per ticker and writes checkpoint JSON files.
Re-run reuses successful ticker files for the same date; --refresh fetches them again.
Historical financial/valuation fields remain absent until point-in-time filings are available.
"""
import argparse
import json
import sys
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from events_lib.loader import load_seed_events
from events_lib.history_audit import DEFAULT_TICKERS, audit, observations
from domain.stock import DailyBar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--include-db", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--out", default="data/history")
    args = parser.parse_args()
    tickers = list(dict.fromkeys(t.strip().upper() for t in args.tickers.split(",") if t.strip()))
    import re
    if not tickers or any(not re.fullmatch(r"[A-Z0-9.\-]{1,5}", t) for t in tickers):
        parser.error("tickers 须为有效美股代码")
    events = {e.event_id: e for e in load_seed_events()}
    db_note = "仅审计仓库种子；未读取 DB 自定义事件或自动草稿"
    if args.include_db:
        try:
            from storage import repository
            for source in ("seed", "user"):
                for event in repository.list_events(source=source):
                    events[event.event_id] = event
            drafts = repository.list_events(source="auto")
            db_note = f"已合并 DB seed/user；auto 草稿 {len(drafts)} 条单独排除"
        except Exception as exc:
            db_note = f"DB 不可用（{type(exc).__name__}），审计仅覆盖种子"
    report = audit(list(events.values()), tickers)
    report["scope"] = db_note
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    (root / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = ["# 历史事件覆盖审计", "", db_note, "", f"事件 {report['event_count']} 条；未兑现对照 {report['fizzled']} 条。", "",
             "| 标的 | 事件 | 前状态完整 | 回撤已填 | 恢复已填 | 未兑现对照 |", "|---|---:|---:|---:|---:|---:|"]
    for r in report["tickers"]:
        lines.append("| " + " | ".join(str(r[k]) for k in ("ticker", "events", "pre_state_complete", "drawdown_known", "recovery_known", "fizzled")) + " |")
    lines += ["", report["conclusion"], ""] + ["- " + s for s in report["limitations"]]
    (root / "coverage.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not args.initialize:
        return 0
    from config.settings import settings
    if settings.mock_mode:
        print("拒绝初始化：MOCK_MODE 会污染历史证据")
        return 1
    from collectors import get_market
    market = get_market()
    today = date.today()
    start = min(e.start_date for e in events.values()) - timedelta(days=420)
    failures = []
    for ticker in tickers:
        path = root / f"{ticker}.json"
        try:
            cached = json.loads(path.read_text()) if path.exists() and not args.refresh else {}
            if cached.get("as_of") == str(today) and cached.get("start") == str(start):
                bars = [DailyBar.model_validate(b) for b in cached["bars"]]
            else:
                bars = market.get_daily_bars_between(ticker, start, today + timedelta(days=1))
            if not bars:
                raise ValueError("empty history")
            payload = {"version": "1.4", "source": "yfinance auto_adjust=True", "as_of": str(today),
                       "start": str(start), "collected_at": datetime.now(timezone.utc).isoformat(),
                       "bars": [b.model_dump(mode="json") for b in bars],
                       "events": observations(list(events.values()), ticker, bars, today)}
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            temp.replace(path)
            print(f"{ticker}: {len(bars)} 根日线，{len(payload['events'])} 个事件观察窗口")
        except Exception as exc:
            failures.append({"ticker": ticker, "error": type(exc).__name__})
            print(f"{ticker}: 初始化失败（{type(exc).__name__}），可重试")
    (root / "initialization-status.json").write_text(json.dumps({"as_of": str(today), "failed": failures}, indent=2))
    from events_lib.history_audit import enrich_from_initialized_history
    effective = audit(enrich_from_initialized_history(list(events.values()), root), tickers)
    (root / "effective-coverage.json").write_text(json.dumps(effective, ensure_ascii=False, indent=2))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
