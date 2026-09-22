"""X 爬虫（Playwright，X_MODE=crawl 通道）。规格：docs/03-collectors/x-crawler.md

- 登录态：storage_state 注入（scripts/export_x_cookie.py 导出）；失效抛 XCookieExpired
- 抓取：串行每博主，等 tweet 元素 → 滚动 3~5 次 → 提取正文/时间/链接；抓取时不调 LLM
- 防风控：每博主每天最多 1 次（crawl_state 节流）、博主间随机 30~90s、
  异常（登录墙/Something went wrong）立即终止本轮不硬刚
- 过滤：48h 内且命中关注词（股票池 ticker / $ / AI/chip/Fed/tariff 等）
- 路由与节流/入库编排在 collectors/x_source.py（与 X_MODE=api 通道共用）；
  本模块的 filter_posts 等纯函数被 API 通道复用
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


def pick_reply_handle(candidates: list[tuple[str, str]], author: str) -> str | None:
    """纯函数：从候选 (文本, href) 中选出回复对象——@ 开头、非作者本人、非 status 链接。

    自回复（楼主续帖）视为原创（返回 None），与"回复别人"区分。
    """
    for text, href in candidates:
        handle = text.lstrip("@").strip().split("/")[0]
        if not handle or handle.lower() == author.lower():
            continue
        if "/status/" in href:
            continue
        return handle
    return None


class XCollector:
    name = "x-crawler"

    # 主页帖子页 + 帖子与回复合并页（with_replies 含原创+回复，双页抓取后按 post_id 去重）
    PROFILE_TABS = ("", "/with_replies")

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
        """抓主页帖 + 回复两页，post_id 去重合并。"""
        collected_at = datetime.now(timezone.utc)
        posts: list[XPost] = []
        seen: set[str] = set()

        for suffix in self.PROFILE_TABS:
            page = context.new_page()
            try:
                page.goto(f"https://x.com/{handle}{suffix}", timeout=30000)
                page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
                if self._blocked(page):
                    raise XCookieExpired("页面出现登录墙/异常提示：cookie 已失效")

                for _ in range(random.randint(3, 5)):  # 滚动 3~5 次，不深挖历史
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(random.randint(2000, 4000))
                if self._blocked(page):
                    raise XCookieExpired("滚动后出现异常提示：cookie 已失效")

                for article in page.locator('article[data-testid="tweet"]').all():
                    post = self._extract_post(article, handle, collected_at)
                    if post and post.post_id not in seen:
                        seen.add(post.post_id)
                        posts.append(post)
            finally:
                page.close()
            if suffix != self.PROFILE_TABS[-1]:
                time.sleep(random.uniform(2, 4))  # 页签间小间隔
        return posts

    def _extract_post(self, article, author: str, collected_at) -> XPost | None:
        """单条 article → XPost；解析失败返回 None（不影响整轮）。"""
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
                return None
            return XPost(
                post_id=post_id, author=author, content=content,
                url=url, posted_at=posted_at, collected_at=collected_at,
                reply_to=self._reply_to(article, author),
            )
        except Exception:
            return None

    @staticmethod
    def _reply_to(article, author: str) -> str | None:
        """从 "Replying to @x" 上下文提取回复对象（DOM 结构可能变化，防御式解析）。"""
        try:
            candidates: list[tuple[str, str]] = []
            for link in article.locator('a[role="link"][href^="/"]').all():
                text = (link.inner_text() or "").strip()
                href = link.get_attribute("href") or ""
                if text.startswith("@") and len(text) > 1:
                    candidates.append((text, href))
            return pick_reply_handle(candidates, author)
        except Exception:
            return None

    @staticmethod
    def _blocked(page) -> bool:
        try:
            content = page.content().lower()
        except Exception:
            return False
        return ("something went wrong" in content or "try again" in content
                or 'action="https://x.com/login"' in content
                or "log in to x" in content)
