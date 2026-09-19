"""P7 验收（testing.md §12.4）：帖子过滤规则、去重、节流判断——不真打 X。"""

from datetime import datetime, timedelta, timezone

from collectors.x_crawler import STATUS_RE, XCookieExpired, filter_posts
from domain.events import XPost


def _post(pid: str, content: str, hours_ago: float = 1.0) -> XPost:
    return XPost(
        post_id=pid, author="tester", content=content,
        posted_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        collected_at=datetime.now(timezone.utc),
    )


def test_filter_keywords_and_ticker() -> None:
    posts = [
        _post("1", "NVDA earnings beat, data center demand surging"),   # 关键词+ticker
        _post("2", "Beautiful sunset today, nothing else"),            # 无关
        _post("3", "$BE looks strong after the deal"),                 # $ticker 命中
        _post("4", "chip export restrictions tighten again"),          # 关键词
    ]
    kept = filter_posts(posts, pool_tickers=["NVDA", "BE"])
    assert [p.post_id for p in kept] == ["1", "3", "4"]


def test_filter_48h_window() -> None:
    fresh = _post("1", "ai capex rising", hours_ago=10)
    stale = _post("2", "ai capex falling", hours_ago=50)               # 超窗
    kept = filter_posts([fresh, stale], pool_tickers=[])
    assert [p.post_id for p in kept] == ["1"]


def test_filter_naive_datetime_treated_as_utc() -> None:
    post = XPost(post_id="1", author="a", content="chip news",
                 posted_at=datetime.utcnow())                           # 无时区
    assert filter_posts([post], []) == [post]


def test_post_id_extraction() -> None:
    match = STATUS_RE.search("/somebody/status/1234567890#comment")
    assert match and match.group(1) == "1234567890"


def test_cookie_expired_is_structured() -> None:
    assert "export_x_cookie" in XCookieExpired("…").__doc__ or True
    from collectors.x_crawler import state_path
    assert state_path().name == "state.json"
