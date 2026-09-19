"""MOCK_MODE 静态数据源：与真实采集器同接口，无网无 key 验证全链路。

规格：docs/09-delivery/testing.md §12.1（Mock 路径）
数据为确定性生成（固定随机种子），图表渲染可反复对照。
"""

import random
from datetime import date, datetime, timedelta, timezone

from domain.events import RawArticle
from domain.scoring import IndexLevel, IndexRegime, MacroPoint
from domain.stock import DailyBar, Financials, MarketQuote


def _fake_bars(n: int = 300, start: float = 100.0, daily_drift: float = 0.10,
               daily_vol: float = 1.8, seed: int = 7) -> list[DailyBar]:
    rng = random.Random(seed)
    bars: list[DailyBar] = []
    price = start
    day = date.today() - timedelta(days=int(n * 1.45))
    while len(bars) < n:
        day += timedelta(days=1)
        if day.weekday() >= 5:  # 跳过周末，近似交易日
            continue
        change = price * (daily_drift + rng.gauss(0, daily_vol)) / 100
        open_ = price
        close = max(price + change, 1.0)
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.4)) / 100)
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.4)) / 100)
        bars.append(DailyBar(date=day, open=open_, high=high, low=low,
                             close=close, volume=rng.uniform(1e7, 6e7)))
        price = close
    return bars


class MockMarket:
    name = "mock-market"

    def get_daily_bars(self, symbol: str, window: int = 300) -> list[DailyBar]:
        seed = abs(hash(symbol)) % 1000
        return _fake_bars(n=window, start=80 + seed % 60, seed=seed)

    def get_daily_bars_between(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        bars = self.get_daily_bars(symbol, 600)
        return [b for b in bars if start <= b.date <= end]

    def get_quote(self, symbol: str) -> MarketQuote:
        bars = self.get_daily_bars(symbol, 10)
        last, prev = bars[-1], bars[-2]
        return MarketQuote(symbol=symbol, price=last.close,
                           change_pct=(last.close / prev.close - 1) * 100,
                           volume=last.volume,
                           quoted_at=datetime.now(timezone.utc))

    def get_index_regime(self) -> IndexRegime:
        # 健康体制：三大指数均在 MA200 上方，VIX 温和（牛市内深回调原型）
        return IndexRegime(
            indexes=[
                IndexLevel(symbol="^GSPC", close=7316.0, ma200=7050.0),
                IndexLevel(symbol="^NDX", close=27192.0, ma200=26480.0),
                IndexLevel(symbol="^SOX", close=10447.0, ma200=9190.0),
            ],
            vix=20.7,
            sox_atr14=5.7,
        )

    def get_financials(self, symbol: str) -> Financials:
        return Financials(revenue_yoy=55.0, net_income_yoy=60.0, gross_margin=72.0,
                          fcf_positive=True, roe=90.0, pe_ttm=45.0)

    def get_earnings_dates(self, symbol: str, limit: int = 4) -> list[date]:
        today = date.today()
        return [today + timedelta(days=12), today + timedelta(days=100)]


class MockMacro:
    name = "mock-macro"

    def get_series(self, series_id: str) -> MacroPoint:
        fixed = {
            "FEDFUNDS": (4.25, 4.50), "DGS10": (4.10, 4.18), "T10Y2Y": (0.15, 0.05),
            "CPIAUCSL": (320.0, 319.5), "UNRATE": (4.2, 4.1), "PCEPILFE": (2.6, 2.7),
            "BAMLH0A0HYM2": (3.20, 3.05),
        }
        value, prev = fixed.get(series_id, (1.0, 1.0))
        return MacroPoint(series_id=series_id, as_of="2026-09-01",
                          value=value, prev_value=prev)

    def get_all(self) -> dict:
        from collectors.macro import FRED_SERIES
        return {s: self.get_series(s) for s in FRED_SERIES}


class MockNews:
    name = "mock-news"

    def poll_once(self, pool_tickers: list[str]) -> dict:
        """无网版管道：固定文章 → 预过滤 → 规则抽取 → 尽力入库（DB 不可用则降级）。"""
        from analyzer import llm
        from collectors.news import prefilter

        articles = self.get_articles()
        filtered = prefilter(articles, pool_tickers)
        events = llm.extract_events(filtered, pool_tickers)

        stored, db_error = 0, None
        try:
            from storage import repository
            hashes = [repository.article_hash(e.raw_url, e.title) for e in events]
            stored = repository.put_current_events(events, hashes)
        except Exception as exc:
            db_error = str(exc)
        return {"fetched": len(articles), "new": len(articles), "filtered": len(filtered),
                "stored": stored, "db_error": db_error, "events": events}

    def get_articles(self) -> list[RawArticle]:
        now = datetime.now(timezone.utc)
        return [
            RawArticle(source="MockWSJ", raw_url="https://example.com/1",
                       title="US tightens chip export controls on China",
                       summary="New export restrictions target advanced AI chips.", fetched_at=now),
            RawArticle(source="MockBBG", raw_url="https://example.com/2",
                       title="NVDA earnings beat as data center revenue surges",
                       summary="Data center revenue up 80% YoY; guidance raised.", fetched_at=now),
            RawArticle(source="MockABC", raw_url="https://example.com/3",
                       title="Local sports team wins championship",
                       summary="Unrelated filler article for prefilter test.", fetched_at=now),
        ]
