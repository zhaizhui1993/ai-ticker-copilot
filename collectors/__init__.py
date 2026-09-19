"""采集器工厂：MOCK_MODE 路由（docs/09-delivery/testing.md §12.1）。

mock 与真实采集器实现同一组接口，切换零成本。
"""

from config.settings import settings


def get_market():
    if settings.mock_mode:
        from collectors.mock import MockMarket
        return MockMarket()
    from collectors.market import MarketCollector
    return MarketCollector()


def get_macro():
    if settings.mock_mode:
        from collectors.mock import MockMacro
        return MockMacro()
    from collectors.macro import MacroCollector
    return MacroCollector()


def get_news():
    if settings.mock_mode:
        from collectors.mock import MockNews
        return MockNews()
    from collectors.news import NewsCollector
    return NewsCollector()
