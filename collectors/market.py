"""行情采集（yfinance）。

规格：docs/03-collectors/market.md
- 采集层只返原始 OHLCV；MA/RSI/ATR 由消费方经 domain/technicals 自算
- 指数体制层 get_index_regime() 是唯一例外：直接产出算好的 IndexRegime
  （契约 §10.2①：^GSPC/^NDX/^SOX close 与 MA200、^VIX、^SOX ATR14）
- 防限频：串行 + 0.5~1s 随机 sleep + network_retry 退避；避免高频调 .info
- TTL 15min；版本钉死 yfinance==1.5.2 + curl-cffi 0.15.x
"""

import math
import random
import time
from datetime import date, datetime, timezone, timedelta

import yfinance as yf

from collectors.base import network_retry, ttl_cache
from domain import technicals
from domain.scoring import IndexLevel, IndexRegime
from domain.stock import DailyBar, Financials, MarketQuote

INDEX_SYMBOLS = ("^GSPC", "^NDX", "^SOX")
VIX_SYMBOL = "^VIX"


def _sleep() -> None:
    time.sleep(random.uniform(0.5, 1.0))


class MarketCollector:
    name = "yfinance"

    @ttl_cache("market_bars_v14", ttl_seconds=15 * 60)
    @network_retry
    def _history(self, symbol: str, window: int) -> list[DailyBar]:
        df = yf.Ticker(symbol).history(start=(date.today() - timedelta(days=window * 2 + 15)).isoformat(), interval="1d", auto_adjust=True)
        if df is not None:
            df = df.tail(window)
        if df is None or df.empty:
            raise RuntimeError(f"yfinance 未返回数据：{symbol}（window={window}d）")
        bars = [
            DailyBar(
                date=idx.date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume") or 0),
            )
            for idx, row in df.iterrows()
        ]
        _sleep()
        return bars

    def get_daily_bars(self, symbol: str, window: int = 300) -> list[DailyBar]:
        return self._history(symbol, window)

    @ttl_cache("market_bars_range", ttl_seconds=24 * 3600)
    @network_retry
    def _history_range(self, symbol: str, start: str, end: str) -> list[DailyBar]:
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=True)
        if df is None or df.empty:
            raise RuntimeError(f"yfinance 未返回数据：{symbol}（{start}~{end}）")
        _sleep()
        return [
            DailyBar(
                date=idx.date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume") or 0),
            )
            for idx, row in df.iterrows()
        ]

    def get_daily_bars_between(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        """事件窗口取数（backfill 用：T0 前后足够算前高与 180 交易日恢复期）。"""
        return self._history_range(symbol, start.isoformat(), end.isoformat())

    def get_quote(self, symbol: str) -> MarketQuote:
        bars = self._history(symbol, 10)
        last, prev = bars[-1], bars[-2]
        return MarketQuote(
            symbol=symbol,
            price=last.close,
            change_pct=(last.close / prev.close - 1) * 100 if prev.close else None,
            volume=last.volume or None,
        )

    @ttl_cache("market_regime_v14", ttl_seconds=15 * 60)
    def get_index_regime(self) -> IndexRegime:
        """指数体制层（v1.1）：三大指数 vs MA200 + VIX + 费半 ATR14。"""
        levels: list[IndexLevel] = []
        sox_bars: list[DailyBar] | None = None
        for symbol in INDEX_SYMBOLS:
            bars = self._history(symbol, 300)
            if technicals.sma(bars, 200) is None:
                raise ValueError(f"{symbol}: MA200 数据不足")
            levels.append(IndexLevel(
                symbol=symbol,
                close=bars[-1].close,
                ma200=technicals.sma(bars, 200) or 0.0,
            ))
            if symbol == "^SOX":
                sox_bars = bars
        vix = self._history(VIX_SYMBOL, 30)[-1].close
        return IndexRegime(
            indexes=levels,
            vix=vix,
            sox_atr14=technicals.atr_pct(sox_bars) if sox_bars else None,
        )

    @ttl_cache("market_financials_v14", ttl_seconds=12 * 3600)
    def get_financials(self, symbol: str) -> Financials:
        """财报基本面（best-effort：字段缺失返回 None，由评分侧降级标注）。"""
        result = Financials(source="yfinance", collected_at=datetime.now(timezone.utc))
        try:
            tk = yf.Ticker(symbol)
            quarterly = tk.quarterly_financials
            if quarterly is not None and not quarterly.empty and "Total Revenue" in quarterly.index:
                revenues = quarterly.loc["Total Revenue"].dropna()
                if len(revenues) >= 5:  # 去年同季（4 期前）与最近期
                    result.revenue_yoy = (revenues.iloc[0] / revenues.iloc[4] - 1) * 100
            _sleep()
        except Exception:
            pass
        try:
            info = yf.Ticker(symbol).info
            result.gross_margin = info.get("grossMargins", None)
            if result.gross_margin is not None:
                result.gross_margin *= 100
            result.roe = info.get("returnOnEquity", None)
            if result.roe is not None:
                result.roe *= 100
            result.pe_ttm = info.get("trailingPE", None)
            result.shares_outstanding = info.get("sharesOutstanding")
            if info.get("totalDebt") is not None and info.get("totalCash") is not None:
                result.net_debt = info["totalDebt"] - info["totalCash"]
            _sleep()
        except Exception:
            pass
        try:
            cash = yf.Ticker(symbol).cashflow
            if cash is not None and not cash.empty:
                col = cash.columns[0]
                def value(row):
                    if row not in cash.index:
                        return None
                    v = float(cash.loc[row, col])
                    return v if math.isfinite(v) else None
                result.period_end = col.date()
                result.operating_cash_flow = value("Operating Cash Flow")
                capex = value("Capital Expenditure")
                result.capital_expenditure = abs(capex) if capex is not None else None
                result.free_cash_flow = value("Free Cash Flow")
                if result.operating_cash_flow is not None and result.capital_expenditure is not None:
                    result.free_cash_flow = result.operating_cash_flow - result.capital_expenditure
                if result.free_cash_flow is not None:
                    result.fcf_positive = result.free_cash_flow > 0
            _sleep()
        except Exception:
            pass
        return result

    @ttl_cache("market_earnings", ttl_seconds=12 * 3600)
    def get_earnings_dates(self, symbol: str, limit: int = 4) -> list[date]:
        """未来财报日期（经济日历用；失败返回空列表降级）。"""
        try:
            tk = yf.Ticker(symbol)
            df = tk.earnings_dates
            if df is None or df.empty:
                return []
            future = [
                idx.date() for idx in df.index if idx.date() >= date.today()
            ]
            _sleep()
            return sorted(future)[:limit]
        except Exception:
            return []
