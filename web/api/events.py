"""events 路由：当前事件流、增量轮询、经济日历、历史事件库。"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import settings

router = APIRouter()

MACRO_RELEASE_RULE = "CPI/PPI/非农 惯例美东 8:30 发布（月中/月初）"


def _db_unavailable() -> HTTPException | None:
    return None


@router.get("/api/events")
def list_events(scope: str | None = None, limit: int = 100) -> dict:
    try:
        from storage import repository
        events = repository.list_current_events(scope=scope, limit=limit)
        return {"events": [e.model_dump() for e in events], "db_ok": True}
    except Exception as exc:
        return {"events": [], "db_ok": False, "message": f"当前事件读取失败（DB）：{exc}"}


@router.get("/api/events/poll")
def poll_events(since: str | None = None) -> dict:
    try:
        from storage import repository
        since_date = date.fromisoformat(since) if since else date.today()
        events = repository.list_current_events(limit=50)
        fresh = [e for e in events if e.occurred_date >= since_date]
        return {"events": [e.model_dump() for e in fresh], "count": len(fresh)}
    except Exception as exc:
        return {"events": [], "count": 0, "message": str(exc)}


@router.get("/api/calendar")
def calendar() -> dict:
    from events_lib.calendar import market_today, event_calendar
    from collectors import get_market
    from config.loader import load_stocks
    today = market_today()
    market = get_market()
    upcoming, notes = [], []
    for stock in load_stocks():
        result = event_calendar(market, stock.symbol, today, days=7)
        upcoming.extend(result["events"])
        if result["note"]:
            notes.append(f"{stock.symbol}: {result['note']}")
    unique = {(e["date"], e["name"]): e for e in upcoming}
    return {"today": str(today), "upcoming": sorted(unique.values(), key=lambda e: e["date"]),
            "note": "；".join(notes + [MACRO_RELEASE_RULE])}


@router.get("/api/events/lib")
def lib_list(source: str | None = None) -> dict:
    try:
        from storage import repository
        events = repository.list_events(source=source)
        return {"events": [e.model_dump() for e in events]}
    except Exception as exc:
        from events_lib.loader import load_seed_events
        return {"events": [e.model_dump() for e in load_seed_events()],
                "message": f"MySQL 不可用，展示种子文件（DB）：{exc}"}


class EventIn(BaseModel):
    event_id: str
    name: str
    start_date: date
    category: str
    summary: str = ""
    mechanism: str = ""
    keywords: list[str] = []
    tickers: list[str] = []


@router.put("/api/events/lib")
def lib_put(body: EventIn) -> dict:
    from domain.events import EventCategory, HistoricalEvent, TickerImpact
    from storage import repository
    try:
        event = HistoricalEvent(
            event_id=body.event_id, name=body.name, start_date=body.start_date,
            category=EventCategory(body.category), summary=body.summary[:200],
            mechanism=body.mechanism,
            keywords=body.keywords,
            tickers_affected=[TickerImpact(ticker=t, direction=-1, magnitude=0.5)
                              for t in body.tickers],
        )
        repository.put_event(event, source="user")
        return {"saved": event.event_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"保存失败（DB 或字段非法）：{exc}")
