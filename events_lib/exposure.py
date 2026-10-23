"""Explicit current-event exposure before applying historical analogies."""

from pydantic import BaseModel

from domain.events import CurrentEvent, EventScope


class EventExposure(BaseModel):
    event_id: str
    ticker: str
    route: str
    evidence: str


def exposure_for(event: CurrentEvent, ticker: str, segment: str | None = None) -> EventExposure | None:
    """Unknown company and industry links are not inferred from past cases."""
    ticker = ticker.upper()
    mentioned = {t.upper() for t in event.tickers_mentioned}
    if event.scope == EventScope.COMPANY:
        if ticker not in mentioned:
            return None
        return EventExposure(event_id=event.event_id, ticker=ticker, route="direct",
                             evidence="原始报道明确关联当前标的")
    if event.scope == EventScope.INDUSTRY:
        if ticker not in mentioned:
            return None
        return EventExposure(event_id=event.event_id, ticker=ticker, route="direct",
                             evidence="原始报道明确关联当前标的；产业扩散尚未核实")
    if event.scope in (EventScope.MACRO_POLICY, EventScope.GEOPOLITICAL):
        return EventExposure(event_id=event.event_id, ticker=ticker, route="market",
                             evidence="宏观或地缘事件共同风险")
    return None
