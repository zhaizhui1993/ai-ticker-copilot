"""Decision clock and completed-session filtering for daily market evidence."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

ET = ZoneInfo("America/New_York")


class AnalysisClock(BaseModel):
    decision_at: datetime
    mode: Literal["eod", "intraday_observe"]
    price_session_limit: date


def analysis_clock(mode: Literal["eod", "intraday_observe"] = "eod",
                   now: datetime | None = None) -> AnalysisClock:
    """Use 17:00 ET as a conservative cutoff for finalized daily bars.

    The bar provider determines actual holiday/early-close availability; this
    date is only an upper bound, never proof that a session has finalized.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("decision_at must be timezone-aware")
    et = current.astimezone(ET)
    if mode == "eod" and et.weekday() < 5 and time(9, 30) <= et.time() < time(17, 0):
        mode = "intraday_observe"
    limit = et.date() if et.time() >= time(17, 0) else et.date() - timedelta(days=1)
    return AnalysisClock(decision_at=current.astimezone(timezone.utc), mode=mode,
                         price_session_limit=limit)


def completed_bars(bars: list, clock: AnalysisClock) -> list:
    """Exclude the current partial daily bar without changing OHLCV models."""
    return [bar for bar in bars if bar.date <= clock.price_session_limit]
