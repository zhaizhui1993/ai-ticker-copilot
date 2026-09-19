"""X 爬虫（Playwright）。规格：docs/03-collectors/x-crawler.md

- 登录态：storage_state 注入（scripts/export_x_cookie.py 导出）；失效抛 XCookieExpired
- 抓取：串行每博主，等 tweet 元素 → 滚动 3~5 次 → 提取正文/时间/链接；抓取时不调 LLM
- 防风控：每博主每天最多 1 次（crawl_state 节流）、博主间随机 30~90s、
  异常（登录墙/Something went wrong）立即终止本轮不硬刚
- 过滤：48h 内且命中关注词（股票池 ticker / $ / AI/chip/Fed/tariff 等）
"""

import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import settings
from domain.events import XPost
from domain.stock import InfluencerConfig

STATUS_RE = re.compile(r"/status/(\d+)")

# 帖子关注词（与 news 预过滤语义对齐，帖子语境更口语化）
POST_KEYWORDS = [
    "ai", "chip", "semiconductor", "gpu", "capex", "fed", "rate", "tariff",
    "earnings", "guidance", "data center", "算力", "芯片", "半导体", "财报", "关税", "利率",
]


class XCookieExpired(Exception):
    """登录态失效（Web 端应提示重跑 export_x_cookie.py）。"""


def filter_posts(
    posts: list[XPost],
    pool_tickers: list[str],
    hours: int = 48,
    now: datetime | None = None,
) -> list[XPost]:
    """48h 内且正文命中关注词（ticker 词边界或关键词）。纯函数，可独立测试。"""
    now = now or datetime.now(timezone.utc)
    window = timedelta(hours=hours)
    kept = []
    for post in posts:
        if post.posted_at is not None:
            posted = post.posted_at if post.posted_at.tzinfo else post.posted_at.replace(tzinfo=timezone.utc)
            if now - posted > window:
                continue
        text = post.content.lower()
        padded = f" {text} "
        hit = any(k in text for k in POST_KEYWORDS)
        if not hit:
            hit = any(f" ${t.lower()} " in padded or f" {t.lower()} " in padded
                      for t in pool_tickers)
        if hit:
            kept.append(post)
    return kept


def state_path() -> Path:
    return Path(settings.x_storage_state_path)


class XCollector:
    name = "x-crawler"

    def crawl(self, influencers: list[InfluencerConfig], pool_tickers: list[str]) -> dict:
        """抓取一轮。返回 {"posts": [...], "skipped": [...], "error": str|None}。

        需要 playwright 与已导出的登录态；本方法不依赖 DB（节流由调用方先查）。
        """
        from playwright.sync_api import sync_playwright

        state = state_path()
        if not state.exists():
            raise XCookieExpired(
                f"登录态不存在：{state}（先运行 scripts/export_x_cookie.py）"
            )

        posts: list[XPost] = []
        skipped: list[str] = []
        error: str | None = None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for influencer in influencers:
                    context = browser.new_context(storage_state=str(state))
                    try:
                        page_posts = self._crawl_profile(context, influencer.handle)
                        posts.extend(filter_posts(page_posts, pool_tickers,
                                                  hours=settings.x_post_hours_back))
                    except XCookieExpired:
                        raise
                    except Exception as exc:
                        skipped.append(f"{influencer.handle}: {exc}")
                        context.close()
                        continue
                    context.close()
                    if influencer is not influencers[-1]:
                        time.sleep(random.uniform(30, 90))  # 博主间随机间隔
            except XCookieExpired as exc:
                error = str(exc)
            finally:
                browser.close()
        return {"posts": posts, "skipped": skipped, "error": error}

    def _crawl_profile(self, context, handle: str) -> list[XPost]:
        page = context.new_page()
        page.goto(f"https://x.com/{handle}", timeout=30000)
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)

        if self._blocked(page):
            raise XCookieExpired("页面出现登录墙/异常提示：cookie 已失效")

        for _ in range(random.randint(3, 5)):  # 滚动 3~5 次，不深挖历史
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(random.randint(2000, 4000))
        if self._blocked(page):
            raise XCookieExpired("滚动后出现异常提示：cookie 已失效")

        collected_at = datetime.now(timezone.utc)
        posts = []
        for article in page.locator('article[data-testid="tweet"]').all():
            try:
                text_loc = article.locator('[data-testid="tweetText"]')
                content = text_loc.first.inner_text() if text_loc.count() else ""
                posted_at = None
                time_loc = article.locator("time")
                if time_loc.count():
                    raw = time_loc.first.get_attribute("datetime")
                    if raw:
                        posted_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                post_id, url = "", ""
                for link in article.locator('a[href*="/status/"]').all():
                    href = link.get_attribute("href") or ""
                    match = STATUS_RE.search(href)
                    if match:
                        post_id = match.group(1)
                        url = f"https://x.com{href}" if href.startswith("/") else href
                        break
                if not content or not post_id:
                    continue
                posts.append(XPost(
                    post_id=post_id, author=handle, content=content,
                    url=url, posted_at=posted_at, collected_at=collected_at,
                ))
            except Exception:
                continue  # 单条解析失败不影响整轮
        page.close()
        return posts

    @staticmethod
    def _blocked(page) -> bool:
        try:
            content = page.content().lower()
        except Exception:
            return False
        return ("something went wrong" in content or "try again" in content
                or 'action="https://x.com/login"' in content
                or "log in to x" in content)


def crawl_and_store(influencers: list[InfluencerConfig], pool_tickers: list[str]) -> dict:
    """CLI/调度入口：节流 → 抓取 → 入库（post_id 去重）。"""
    from storage import repository

    to_crawl = [inf for inf in influencers
                if repository.try_crawl_lock(f"x:{inf.handle}")]
    throttled = [inf.handle for inf in influencers if inf not in to_crawl]
    if not to_crawl:
        return {"posts": [], "stored": 0, "throttled": throttled,
                "skipped": [], "error": None}

    outcome = XCollector().crawl(to_crawl, pool_tickers)
    stored = repository.put_x_posts(outcome["posts"]) if outcome["posts"] else 0
    return {**outcome, "stored": stored, "throttled": throttled}
