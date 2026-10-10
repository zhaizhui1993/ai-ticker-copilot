"""events 路由：当前事件流、增量轮询、经济日历、历史事件库。"""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from events_lib.calendar import market_today

from config.settings import settings

router = APIRouter()

MACRO_RELEASE_RULE = "CPI/PPI/非农 惯例美东 8:30 发布（月中/月初）"


def _db_unavailable() -> HTTPException | None:
    return None


@router.get("/api/events")
def list_events(scope: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> dict:
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
        since_date = date.fromisoformat(since) if since else market_today()
        events = repository.list_current_events(limit=50)
        fresh = [e for e in events if e.reference_date and e.reference_date >= since_date]
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


class StatusChange(BaseModel):
    status: Literal["active", "resolved", "retracted"]
    reason: str = Field(min_length=1, max_length=2000)


class EventMerge(BaseModel):
    target_event_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


def _change(event_id: str, **kwargs) -> dict:
    from storage import repository
    try:
        return {"event": repository.change_event(event_id, **kwargs).model_dump(mode="json")}
    except KeyError as exc:
        raise HTTPException(404, "事件不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "事件变更未保存，数据库不可用") from exc


@router.patch("/api/events/{event_id}/status")
def change_status(event_id: str, body: StatusChange) -> dict:
    return _change(event_id, status=body.status, reason=body.reason)


@router.post("/api/events/{event_id}/merge")
def merge_event(event_id: str, body: EventMerge) -> dict:
    return _change(event_id, merge_into=body.target_event_id, reason=body.reason)


@router.get("/api/events/{event_id}/changes")
def event_changes(event_id: str) -> dict:
    from storage import repository
    try:
        return {"changes": repository.list_event_changes(event_id)}
    except Exception as exc:
        raise HTTPException(503, "事件变更记录读取失败") from exc
