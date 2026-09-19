"""dashboard 路由：股票池卡片聚合 + 体制层 + 数据源状态。

行情默认读快照/缓存（防限频）；?refresh=1 才实时拉报价。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from collectors import get_market
from config.loader import EMPTY_POOL_MESSAGE, load_stocks
from config.settings import settings
from collectors.x_crawler import state_path

router = APIRouter()


class StockCard(BaseModel):
    symbol: str
    segment: str
    position: str
    cost_basis: float | None = None
    price: float | None = None
    change_pct: float | None = None
    signal: str | None = None
    total: float | None = None
    scores: dict | None = None


@router.get("/api/dashboard")
def dashboard(refresh: bool = False) -> dict:
    stocks = load_stocks()
    if not stocks:
        return {"empty": True, "message": EMPTY_POOL_MESSAGE, "cards": [],
                "regime": None, "sources": _sources()}

    # 快照（DB）优先；无 DB 时降级为无信号卡片
    snapshot_by_symbol: dict = {}
    try:
        from storage import repository
        from datetime import date
        for stock in stocks:
            rows = repository.get_snapshots(stock.symbol, since=date.today() - __import__("datetime").timedelta(days=30))
            if rows:
                last = rows[-1]
                snapshot_by_symbol[stock.symbol] = {
                    "close": last.close, "signal": last.signal,
                    "scores": None, "total": None,
                }
    except Exception:
        pass

    market = get_market()
    cards = []
    for stock in stocks:
        price = change = None
        if refresh or settings.mock_mode:
            try:
                quote = market.get_quote(stock.symbol)
                price, change = quote.price, quote.change_pct
            except Exception:
                pass
        snap = snapshot_by_symbol.get(stock.symbol, {})
        cards.append(StockCard(
            symbol=stock.symbol, segment=stock.segment.value,
            position=stock.position.value, cost_basis=stock.cost_basis,
            price=price if price is not None else snap.get("close"),
            change_pct=change,
            signal=snap.get("signal"),
        ).model_dump())

    regime = None
    try:
        r = market.get_index_regime()
        regime = {
            "broken": r.regime_broken(),
            "vix": r.vix,
            "sox_atr14": r.sox_atr14,
            "indexes": [
                {"symbol": i.symbol, "close": i.close, "ma200": i.ma200,
                 "below": i.below_ma200} for i in r.indexes
            ],
        }
    except Exception as exc:
        regime = {"error": f"指数数据获取失败：{exc}"}

    return {"empty": False, "cards": cards, "regime": regime, "sources": _sources()}


def _sources() -> dict:
    return {
        "market": {"name": "yfinance", "mode": "mock" if settings.mock_mode else "real"},
        "macro": {"name": "FRED", "configured": bool(settings.fred_api_key)},
        "llm": {"name": "LLM", "configured": bool(settings.llm_api_key and settings.llm_model),
                "model": settings.llm_model or None},
        "x": {"name": "X 爬虫", "cookie_ready": state_path().exists()},
        "scheduler": {"enabled": settings.scheduler_enabled},
    }
