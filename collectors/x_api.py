"""X 第三方 API 采集器（twitterapi.io，X_MODE=api）。规格：docs/03-collectors/x-api.md

与 Playwright 爬虫（x_crawler.py）实现同一 crawl() 接口，可互换：
- 一个接口同时覆盖发帖+回复：GET /twitter/user/last_tweets?includeReplies=true
- userName → userId 解析：GET /twitter/user/info（进程内缓存，userId 比.handle 稳定）
- 引用推文：quoted_tweet 嵌套对象拼进 content（「引用 @xx：…」），被引原文不丢失
- 翻页成本控制：next_cursor 翻页，早于 X_POST_HOURS_BACK 时间窗即停 + 页数硬上限
- 计价：$0.15/千条推文；节流沿用 crawl_state（每博主每天 1 次，与爬虫模式共用）

接口文档：https://docs.twitterapi.io（认证：X-API-Key 请求头，非 OAuth）
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from collectors.base import network_retry
from collectors.x_crawler import filter_posts
from config.settings import settings
from domain.events import XPost
from domain.stock import InfluencerConfig

# 时间格式样例："Tue Dec 10 07:00:30 +0000 2024"
_CREATED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"

# 翻页硬上限（20 条/页 × 5 页 = 单博主单次最多读 100 条，成本封顶 ~$0.015）
MAX_PAGES = 5

# 引用推文拼接进 content 时保留的原文长度上限
_QUOTE_SNIPPET_LEN = 120

# handle → userId 进程内缓存（跨重启丢失无妨：每博主每天多花一次 $0.00018 的 info 调用）
_USER_ID_CACHE: dict[str, str] = {}


class XApiKeyError(Exception):
    """API key 未配置/无效或额度用尽（提示去 twitterapi.io 控制台检查）。"""


def parse_created_at(raw: str) -> datetime | None:
    """解析 API 的 createdAt（"Tue Dec 10 07:00:30 +0000 2024"）；失败返回 None。"""
    try:
        return datetime.strptime(raw, _CREATED_AT_FORMAT)
    except (ValueError, TypeError):
        return None


def format_quote(quoted: dict[str, Any] | None) -> str:
    """quoted_tweet 嵌套对象 → 「引用 @handle：原文片段」；无引用返回空串。"""
    if not isinstance(quoted, dict):
        return ""
    handle = quoted.get("author", {}).get("userName") or "unknown"
    text = " ".join((quoted.get("text") or "").split())  # 压平换行
    if len(text) > _QUOTE_SNIPPET_LEN:
        text = text[:_QUOTE_SNIPPET_LEN] + "…"
    return f"「引用 @{handle}：{text}」"


def map_tweet(tweet: dict[str, Any], author: str,
              collected_at: datetime | None = None) -> XPost | None:
    """API 推文对象 → XPost；无 id 视为脏数据返回 None。纯函数，可独立测试。

    - reply_to：仅"回复别人"时填 handle；自回复（楼主续帖）视为原创 → None
      （与爬虫 pick_reply_handle 的语义一致）
    - 引用推文：quoted_tweet 拼在正文后，保证 LLM 情绪打标能看到被引语境
    """
    post_id = str(tweet.get("id") or "")
    if not post_id:
        return None
    content = " ".join((tweet.get("text") or "").split())
    quote = format_quote(tweet.get("quoted_tweet"))
    if quote:
        content = f"{content} {quote}".strip()

    reply_to = None
    if tweet.get("isReply"):
        target = tweet.get("inReplyToUsername") or ""
        if target and target.lower() != author.lower():
            reply_to = target

    posted_at = parse_created_at(tweet.get("createdAt") or "")
    return XPost(
        post_id=post_id, author=author, content=content,
        url=tweet.get("url") or f"https://x.com/{author}/status/{post_id}",
        likes=tweet.get("likeCount"),
        posted_at=posted_at,
        collected_at=collected_at or datetime.now(timezone.utc),
        reply_to=reply_to,
    )


class XApiCollector:
    """twitterapi.io 采集器；transport 可注入（测试用），默认 httpx 实现。"""

    name = "x-api"

    def __init__(self, transport: Callable[[str, dict], dict] | None = None):
        self._transport = transport or self._http_get

    @staticmethod
    @network_retry
    def _http_get(path: str, params: dict) -> dict:
        if not settings.x_api_key:
            raise XApiKeyError("X_API_KEY 未配置：在 twitterapi.io 控制台获取后写入 .env")
        url = f"{settings.x_api_base}{path}"
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params,
                              headers={"X-API-Key": settings.x_api_key})
        if resp.status_code in (401, 403):
            raise XApiKeyError(
                f"API key 无效或额度用尽（HTTP {resp.status_code}）：检查 twitterapi.io 控制台")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == "error":
            raise XApiKeyError(payload.get("message") or "twitterapi.io 返回 error")
        return payload

    def user_id(self, handle: str) -> str:
        """handle → userId（进程内缓存）。官方建议 last_tweets 传 userId（更稳定更快）。"""
        if handle not in _USER_ID_CACHE:
            data = self._transport("/twitter/user/info", {"userName": handle})
            user = data.get("data") or {}
            user_id = str(user.get("id") or "")
            if not user_id:
                raise XApiKeyError(f"未解析到用户：@{handle}（改名/封号？）")
            _USER_ID_CACHE[handle] = user_id
        return _USER_ID_CACHE[handle]

    def fetch_timeline(self, handle: str, hours_back: int) -> list[XPost]:
        """拉单个博主时间线（帖+回复），翻页到时间窗外或页数上限。"""
        user_id = self.user_id(handle)
        collected_at = datetime.now(timezone.utc)
        cutoff = collected_at - timedelta(hours=hours_back)

        posts: list[XPost] = []
        cursor = ""
        for _ in range(MAX_PAGES):
            params = {"userId": user_id, "includeReplies": "true"}
            if cursor:
                params["cursor"] = cursor
            payload = self._transport("/twitter/user/last_tweets", params)
            tweets = payload.get("tweets") or []
            page_posts = [p for p in (map_tweet(t, handle, collected_at)
                                      for t in tweets) if p]
            posts.extend(page_posts)
            if not tweets or not payload.get("has_next_page") \
                    or not payload.get("next_cursor"):
                break
            # 时间线新→旧：本页最老的帖子已早于时间窗 → 增量取完，停止翻页（成本控制）
            page_times = [p.posted_at for p in page_posts if p.posted_at]
            if page_times and min(page_times) < cutoff:
                break
            cursor = payload["next_cursor"]
        return posts

    def crawl(self, influencers: list[InfluencerConfig],
              pool_tickers: list[str]) -> dict:
        """抓取一轮。返回与 XCollector.crawl 同构：
        {"posts": [...], "skipped": ["handle: 原因", ...], "error": str|None}
        key 级错误（key 无效/额度尽）立即终止整轮，单博主异常跳过继续。
        """
        posts: list[XPost] = []
        skipped: list[str] = []
        error: str | None = None
        for influencer in influencers:
            try:
                timeline = self.fetch_timeline(influencer.handle,
                                               settings.x_post_hours_back)
                posts.extend(filter_posts(timeline, pool_tickers,
                                          hours=settings.x_post_hours_back))
            except XApiKeyError as exc:
                error = str(exc)
                break
            except Exception as exc:
                skipped.append(f"{influencer.handle}: {exc}")
        return {"posts": posts, "skipped": skipped, "error": error}
