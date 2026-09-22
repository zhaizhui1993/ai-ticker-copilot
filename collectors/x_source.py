"""X 数据源路由（X_MODE=api|crawl|off）+ 抓取编排。

调度器与 CLI 统一从这里进入；两个通道实现同一 crawl() 接口：
- api：collectors/x_api.py（twitterapi.io 第三方接口，推荐）
- crawl：collectors/x_crawler.py（Playwright 本地爬虫，需登录态）
节流（crawl_state 每博主每天 1 次）与入库（put_x_posts）两通道共用。
"""

from config.settings import settings
from domain.events import XPost
from domain.stock import InfluencerConfig


def _crawl_with(influencers: list[InfluencerConfig],
                pool_tickers: list[str]) -> dict:
    """按 X_MODE 选择通道执行 crawl()（不做节流/入库）。"""
    if settings.x_mode == "api":
        from collectors.x_api import XApiCollector
        return XApiCollector().crawl(influencers, pool_tickers)
    from collectors.x_crawler import XCollector
    return XCollector().crawl(influencers, pool_tickers)


def crawl_and_store(influencers: list[InfluencerConfig],
                    pool_tickers: list[str]) -> dict:
    """CLI/调度入口：X_MODE 路由 → 节流 → 抓取 → 入库（post_id 去重）。

    off 模式直接返回空结果（带 mode 标记，调用方据此打印"已关闭"）。
    """
    if settings.x_mode == "off":
        return {"posts": [], "stored": 0, "throttled": [], "skipped": [],
                "error": None, "mode": "off"}

    from storage import repository

    to_crawl = [inf for inf in influencers
                if repository.try_crawl_lock(f"x:{inf.handle}")]
    throttled = [inf.handle for inf in influencers if inf not in to_crawl]
    if not to_crawl:
        return {"posts": [], "stored": 0, "throttled": throttled,
                "skipped": [], "error": None, "mode": settings.x_mode}

    outcome = _crawl_with(to_crawl, pool_tickers)
    stored = repository.put_x_posts(outcome["posts"]) if outcome["posts"] else 0
    return {**outcome, "stored": stored, "throttled": throttled,
            "mode": settings.x_mode}
