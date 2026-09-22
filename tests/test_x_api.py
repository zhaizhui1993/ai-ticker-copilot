"""X_MODE=api 通道验收（docs/03-collectors/x-api.md）：映射规则、翻页成本控制、
key 错误语义、路由编排——不真调 twitterapi.io。"""

from datetime import datetime, timedelta, timezone

import pytest

from collectors import x_api
from collectors.x_api import (
    XApiCollector,
    XApiKeyError,
    format_quote,
    map_tweet,
    parse_created_at,
)
from domain.stock import InfluencerConfig

_NOW = datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    """datetime → API 的 createdAt 格式（"Tue Dec 10 07:00:30 +0000 2024"）。"""
    return dt.strftime("%a %b %d %H:%M:%S %z %Y")


def _tweet(tid: str, text: str, hours_ago: float = 1.0, *,
           is_reply: bool = False, in_reply_to: str | None = None,
           quoted: dict | None = None, likes: int = 10,
           url: str = "") -> dict:
    return {
        "id": tid, "text": text, "likeCount": likes, "url": url,
        "createdAt": _fmt(_NOW - timedelta(hours=hours_ago)),
        "isReply": is_reply, "inReplyToUsername": in_reply_to,
        "quoted_tweet": quoted,
    }


@pytest.fixture(autouse=True)
def _clear_user_id_cache():
    x_api._USER_ID_CACHE.clear()
    yield
    x_api._USER_ID_CACHE.clear()


class FakeTransport:
    """预置页序列的假 transport：user/info + last_tweets 翻页，记录调用。"""

    def __init__(self, users: dict[str, str], pages: dict[str, list[dict]]):
        self.users = users        # handle -> user_id
        self.pages = pages        # user_id -> [第1页payload, 第2页payload, ...]
        self.counters: dict[str, int] = {}
        self.info_calls = 0
        self.page_calls = 0
        self.last_params: dict = {}

    def __call__(self, path: str, params: dict) -> dict:
        self.last_params = dict(params)
        if path == "/twitter/user/info":
            self.info_calls += 1
            uid = self.users.get(params["userName"])
            return {"status": "success", "data": {"id": uid} if uid else {}}
        self.page_calls += 1
        uid = params["userId"]
        idx = self.counters.get(uid, 0)
        self.counters[uid] = idx + 1
        seq = self.pages[uid]
        return {"status": "success", **seq[min(idx, len(seq) - 1)]}  # 越界重复最后一页


# ---------- 纯函数：字段映射 ----------


def test_parse_created_at_roundtrip_and_garbage() -> None:
    parsed = parse_created_at("Tue Dec 10 07:00:30 +0000 2024")
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2024, 12, 10, 7)
    assert parsed.tzinfo is not None
    assert parse_created_at("not a date") is None
    assert parse_created_at("") is None


def test_map_tweet_original_post() -> None:
    post = map_tweet(_tweet("100", "NVDA earnings beat", likes=88), author="blogger")
    assert post is not None
    assert post.post_id == "100"
    assert post.reply_to is None                     # 原创帖
    assert post.likes == 88
    assert post.url.endswith("/blogger/status/100")  # 无 url 字段时回退拼接
    assert post.posted_at is not None


def test_map_tweet_reply_to_other_and_self() -> None:
    reply = map_tweet(
        _tweet("101", "学会了", is_reply=True, in_reply_to="target"),
        author="blogger")
    assert reply is not None and reply.reply_to == "target"

    # 自回复（楼主续帖）视为原创，与爬虫 pick_reply_handle 语义一致
    self_reply = map_tweet(
        _tweet("102", "续帖", is_reply=True, in_reply_to="Blogger"),
        author="blogger")
    assert self_reply is not None and self_reply.reply_to is None

    # isReply 但缺被回复人（防御）：不填 reply_to
    missing = map_tweet(_tweet("103", "嗯", is_reply=True), author="blogger")
    assert missing is not None and missing.reply_to is None


def test_map_tweet_quote_appends_context() -> None:
    quoted = {"author": {"userName": "Angel"}, "text": "费半库存周期见顶 " * 30}
    post = map_tweet(
        _tweet("104", "完全同意！", quoted=quoted, url="https://x.com/a/status/104"),
        author="blogger")
    assert post is not None
    assert post.content.startswith("完全同意！")
    assert "「引用 @Angel：" in post.content
    assert post.content.endswith("…」")               # 原文截断
    assert len(post.content) < 200                    # 控制情绪打标的输入长度
    assert post.url == "https://x.com/a/status/104"   # 有 url 字段时优先用


def test_format_quote_edge_cases() -> None:
    assert format_quote(None) == ""
    assert format_quote("garbage") == ""
    # 缺 author 的脏数据不崩溃，回退 @unknown
    assert format_quote({"text": "hi"}) == "「引用 @unknown：hi」"


def test_map_tweet_without_id_is_dropped() -> None:
    assert map_tweet({"text": "no id"}, author="a") is None


# ---------- XApiCollector：翻页与缓存 ----------


def _pages(items: list[dict], *, next_cursor: str | None = None) -> dict:
    return {"tweets": items, "has_next_page": bool(next_cursor),
            "next_cursor": next_cursor or ""}


def test_fetch_timeline_pages_until_window_edge() -> None:
    fresh = [_tweet("1", "chip supply tight", hours_ago=2),
             _tweet("2", "$NVDA momentum", hours_ago=5)]
    stale = [_tweet("3", "ai capex old", hours_ago=100)]
    transport = FakeTransport(
        users={"blogger": "u1"},
        pages={"u1": [
            _pages(fresh, next_cursor="c2"),
            _pages(stale),                       # 第二页最老已出窗 → 停止翻页
        ]})
    collector = XApiCollector(transport=transport)

    posts = collector.fetch_timeline("blogger", hours_back=48)

    assert transport.page_calls == 2             # 第二页后不再请求第三页
    assert transport.info_calls == 1
    assert transport.last_params["includeReplies"] == "true"   # 帖+回复一次拿全
    assert transport.last_params["userId"] == "u1"
    assert {p.post_id for p in posts} == {"1", "2", "3"}       # 出窗页仍并入（过滤在 crawl 层）


def test_fetch_timeline_single_page_no_cursor() -> None:
    transport = FakeTransport(
        users={"blogger": "u1"},
        pages={"u1": [_pages([_tweet("1", "fed rate cut odds")])]})
    posts = XApiCollector(transport=transport).fetch_timeline("blogger", 48)
    assert [p.post_id for p in posts] == ["1"]
    assert transport.page_calls == 1


def test_user_id_cached_within_process() -> None:
    transport = FakeTransport(
        users={"blogger": "u1"},
        pages={"u1": [_pages([_tweet("1", "gpu shortage")])]})
    collector = XApiCollector(transport=transport)
    collector.fetch_timeline("blogger", 48)
    XApiCollector(transport=transport).fetch_timeline("blogger", 48)
    assert transport.info_calls == 1             # 第二次命中进程内缓存


def test_unknown_handle_raises_key_error_semantics() -> None:
    transport = FakeTransport(users={}, pages={})
    with pytest.raises(XApiKeyError):
        XApiCollector(transport=transport).fetch_timeline("ghost", 48)


# ---------- crawl()：整轮语义（错误处理 + 过滤复用） ----------


def test_crawl_filters_and_maps_reply() -> None:
    transport = FakeTransport(
        users={"blogger": "u1"},
        pages={"u1": [_pages([
            _tweet("1", "beautiful sunset, nothing else"),            # 无关 → 过滤
            _tweet("2", "NVDA earnings beat", hours_ago=3),
            _tweet("3", "学会了，下次我也劝卖 $NVDA", hours_ago=4,
                   is_reply=True, in_reply_to="TalkKing"),            # 回复命中 ticker → 保留
            _tweet("4", "学会了，下次我也劝卖", hours_ago=4,
                   is_reply=True, in_reply_to="TalkKing"),            # 回复无关键词 → 过滤（与帖子同规则）
        ])]})
    outcome = XApiCollector(transport=transport).crawl(
        [InfluencerConfig(handle="blogger")], pool_tickers=["NVDA"])

    assert outcome["error"] is None and outcome["skipped"] == []
    kept = {p.post_id: p for p in outcome["posts"]}
    assert set(kept) == {"2", "3"}
    assert kept["3"].reply_to == "TalkKing"      # 回复对象进入结构化字段


def test_crawl_key_error_terminates_round() -> None:
    def broken(path, params):
        raise XApiKeyError("API key 无效或额度用尽（HTTP 401）")

    outcome = XApiCollector(transport=broken).crawl(
        [InfluencerConfig(handle="a"), InfluencerConfig(handle="b")], [])
    assert outcome["posts"] == []
    assert "401" in outcome["error"]
    assert outcome["skipped"] == []              # key 级错误不逐博主报，直接终止


def test_crawl_single_blogger_failure_skips_and_continues() -> None:
    transport = FakeTransport(
        users={"good": "u1"}, pages={"u1": [_pages([_tweet("1", "tariff news")])]})

    class HalfBroken:
        def __init__(self, inner):
            self.inner = inner

        def __call__(self, path, params):
            if path == "/twitter/user/info" and params["userName"] == "bad":
                raise RuntimeError("timeout")
            return self.inner(path, params)

    outcome = XApiCollector(transport=HalfBroken(transport)).crawl(
        [InfluencerConfig(handle="bad"), InfluencerConfig(handle="good")], [])
    assert outcome["error"] is None
    assert outcome["skipped"] == ["bad: timeout"]
    assert [p.post_id for p in outcome["posts"]] == ["1"]


# ---------- x_source 路由与编排 ----------


def test_route_off_skips_everything(monkeypatch) -> None:
    from config.settings import settings
    from storage import repository

    def _must_not_touch(key: str) -> bool:
        raise AssertionError("off 模式不应触达 DB")

    monkeypatch.setattr(settings, "x_mode", "off")
    monkeypatch.setattr(repository, "try_crawl_lock", _must_not_touch)

    from collectors.x_source import crawl_and_store
    outcome = crawl_and_store([InfluencerConfig(handle="a")], [])
    assert outcome == {"posts": [], "stored": 0, "throttled": [], "skipped": [],
                       "error": None, "mode": "off"}


def test_route_orchestration_throttles_and_stores(monkeypatch) -> None:
    from config.settings import settings
    from storage import repository

    monkeypatch.setattr(settings, "x_mode", "api")
    monkeypatch.setattr(repository, "try_crawl_lock", lambda key: "a" in key)
    stored_posts = []

    def _fake_put(posts):
        stored_posts.extend(posts)
        return len(posts)

    monkeypatch.setattr(repository, "put_x_posts", _fake_put)

    from collectors import x_source
    from domain.events import XPost

    def _fake_crawl(influencers, pool_tickers):
        return {"posts": [XPost(post_id="1", author="a", content="chip news")],
                "skipped": [], "error": None}

    monkeypatch.setattr(x_source, "_crawl_with", _fake_crawl)

    outcome = x_source.crawl_and_store(
        [InfluencerConfig(handle="a"), InfluencerConfig(handle="b")], [])
    assert outcome["mode"] == "api"
    assert outcome["throttled"] == ["b"]          # try_crawl_lock 只放行 a
    assert outcome["stored"] == 1 and stored_posts[0].post_id == "1"
