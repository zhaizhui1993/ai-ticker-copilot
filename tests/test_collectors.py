"""采集基座与管道规则测试（不真打外网）。"""

import time
from datetime import datetime, timezone

from collectors.base import ttl_cache
from collectors.news import google_news_url, prefilter
from domain.events import RawArticle
from storage.repository import article_hash


def test_ttl_cache_memory_and_expiry(tmp_path, monkeypatch) -> None:
    from config import settings as settings_module
    monkeypatch.setattr(settings_module.Settings, "model_config",
                        settings_module.Settings.model_config, raising=False)
    # 缓存目录指到临时目录
    import collectors.base as base
    monkeypatch.setattr(base.settings, "cache_dir", str(tmp_path))

    calls = {"n": 0}

    @ttl_cache("test", ttl_seconds=60, disk=True)
    def fetch(key: str) -> str:
        calls["n"] += 1
        return f"value-{key}"

    assert fetch("a") == "value-a"
    assert fetch("a") == "value-a"
    assert calls["n"] == 1                    # 内存命中
    assert fetch("b") == "value-b"
    assert calls["n"] == 2

    # 清空内存层 → 磁盘层命中
    fetch.memory.clear()
    assert fetch("a") == "value-a"
    assert calls["n"] == 2                    # 磁盘命中，不再调用


def test_ttl_cache_expires(tmp_path, monkeypatch) -> None:
    import collectors.base as base
    monkeypatch.setattr(base.settings, "cache_dir", str(tmp_path))

    calls = {"n": 0}

    @ttl_cache("test_short", ttl_seconds=0.1, disk=True)
    def fetch(key: str) -> str:
        calls["n"] += 1
        return f"v{key}"

    fetch("x")
    time.sleep(0.15)
    fetch("x")
    assert calls["n"] == 2                    # TTL 过期后重新调用


def _article(title: str, url: str = "") -> RawArticle:
    return RawArticle(source="t", raw_url=url or f"https://x/{title[:8]}",
                       title=title, summary="",
                       fetched_at=datetime.now(timezone.utc))


def test_prefilter_keywords_and_tickers() -> None:
    articles = [
        _article("Fed signals rate cut ahead"),            # 宏观关键词
        _article("US tightens chip export controls"),      # 行业/地缘关键词
        _article("Local team wins championship"),          # 无关
        _article("Strong earnings report lifts chipmakers"),  # 企业关键词
    ]
    kept = prefilter(articles, pool_tickers=[])
    assert [a.title for a in kept] == [a.title for a in articles[:2] + [articles[3]]]

    ticker_hit = [_article("Big day for ACME Corp")]
    assert prefilter(ticker_hit, pool_tickers=["ACME"])    # ticker 命中


def test_article_hash_stable_and_distinct() -> None:
    h1 = article_hash("https://a/1", "Title")
    h2 = article_hash("https://a/1", "Title")
    h3 = article_hash("https://a/1", "Different Title")
    assert h1 == h2 and h1 != h3 and len(h1) == 64


def test_google_news_url() -> None:
    url = google_news_url("AI chip")
    assert "news.google.com/rss/search" in url and "AI%20chip" in url


def test_mock_routing(monkeypatch) -> None:
    import collectors
    monkeypatch.setattr(collectors.settings, "mock_mode", True)
    market = collectors.get_market()
    assert market.name == "mock-market"

    regime = market.get_index_regime()
    assert regime.vix == 20.7
    assert regime.regime_broken() is False                  # 健康体制样本
    assert len(regime.indexes) == 3

    bars = market.get_daily_bars("NVDA", 300)
    assert len(bars) == 300
    from domain import technicals
    assert technicals.sma(bars, 200) is not None            # 300 根足以算 MA200

    macro = collectors.get_macro()
    points = macro.get_all()
    assert set(points) == {"FEDFUNDS", "DGS10", "T10Y2Y", "CPIAUCSL",
                           "UNRATE", "PCEPILFE", "BAMLH0A0HYM2"}
