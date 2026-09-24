"""Shared research calendar. Dates are decision dates, not inferred macro releases."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
# Verified 2026-09-24: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DATES = tuple(date.fromisoformat(f"2026-{d}") for d in
                   ("01-28", "03-18", "04-29", "06-17", "07-29", "09-16", "10-28", "12-09"))


def market_today() -> date:
    return datetime.now(ET).date()


def event_calendar(market, ticker: str, today: date, days: int = 3) -> dict:
    end = today + timedelta(days=days)
    events = [{"date": str(d), "type": "FOMC", "name": "美联储议息会议"}
              for d in FOMC_DATES if today <= d <= end]
    notes = []
    if today.year != 2026 or end.year != 2026:
        notes.append("FOMC 日历年份未覆盖，需更新官方日程")
    try:
        earnings = [d for d in market.get_earnings_dates(ticker) if d >= today]
        if not earnings:
            notes.append("财报日期未知")
        events.extend({"date": str(d), "type": "earnings", "name": f"{ticker} 财报"}
                      for d in earnings if d <= end)
    except Exception:
        notes.append("财报日期获取失败")
    return {"events": sorted(events, key=lambda e: e["date"]), "unknown": bool(notes),
            "note": "；".join(notes)}
