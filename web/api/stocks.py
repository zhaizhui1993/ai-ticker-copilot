"""stocks 路由：股票池读写与个股详情。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.loader import ConfigError, load_stocks
from domain import technicals
from collectors import get_market

router = APIRouter()


class StockIn(BaseModel):
    symbol: str
    segment: str = "other"
    position: str = "watchlist"
    cost_basis: float | None = None


class PoolIn(BaseModel):
    stocks: list[StockIn]


@router.get("/api/stocks")
def get_pool() -> dict:
    return {"stocks": [s.model_dump() for s in load_stocks()]}


@router.put("/api/stocks")
def put_pool(body: PoolIn) -> dict:
    import yaml
    from config.loader import CONFIG_DIR

    data = {"stocks": [s.model_dump() for s in body.stocks]}
    target = CONFIG_DIR / "stocks.yaml"
    try:
        load_stocks.__wrapped__ if False else None
        target.write_text(
            yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        saved = load_stocks(target)  # 写后重读校验（非法 symbol 在此抛出）
        return {"saved": len(saved)}
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/stocks/{symbol}")
def stock_detail(symbol: str, window: str = "6M") -> dict:
    market = get_market()
    days = {"3M": 70, "6M": 140, "1Y": 260}.get(window, 140)
    try:
        bars = market.get_daily_bars(symbol.upper(), max(days + 200, 300))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"行情获取失败：{exc}")

    view = bars[-days:]
    return {
        "symbol": symbol.upper(),
        "window": window,
        "bars": [
            {"date": str(b.date), "open": b.open, "high": b.high,
             "low": b.low, "close": b.close, "volume": b.volume}
            for b in view
        ],
        "indicators": {
            "close": view[-1].close if view else None,
            "ma20": technicals.sma(view, 20),
            "ma50": technicals.sma(view, 50),
            "ma200": technicals.sma(bars, 200),
            "rsi14": technicals.rsi(view),
            "atr14_pct": technicals.atr_pct(view),
            "volume_ratio": technicals.volume_ratio(view),
            "drawdown_52w": technicals.drawdown_from_high_pct(bars),
            "bias_ma200": technicals.bias_vs_ma200_pct(bars),
        },
    }
