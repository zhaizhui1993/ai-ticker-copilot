"""P2 验收：快照 UPSERT 覆盖、事件 CRUD、帖子去重、日志追加。

约定（docs/09-delivery/testing.md §12.4）：需可用 MySQL 实例，无实例时自动 skip；
其余测试不依赖 DB。使用独立测试库 ticker_copilot_test，不污染业务库。
"""

from datetime import date, datetime, timezone

import pytest

from config.settings import settings
from domain.events import HistoricalEvent, SentimentLabel, XPost
from domain.scoring import FourDimScores, ScoreBreakdown
from events_lib.loader import load_seed_events, upsert_seed_events
from storage import db, repository

TEST_DB = "ticker_copilot_test"

# ---------- 可用性探测：连不上即整体 skip ----------

try:
    _probe = pymysql = __import__("pymysql").connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        connect_timeout=2,
    )
    _probe.close()
    HAS_DB = True
except Exception:
    HAS_DB = False

pytestmark = pytest.mark.skipif(
    not HAS_DB,
    reason=f"无可用 MySQL 实例（{settings.db_host}:{settings.db_port}，"
            f"user={settings.db_user}）——按 testing.md §12.4 自动 skip，"
            "填好 .env 的 DB_* 后重跑",
)


@pytest.fixture(scope="session", autouse=True)
def database():
    """独立测试库：建库建表 → 全部测试 → 会话结束删库。"""
    db.init_schema(database=TEST_DB)
    db.init_pool(database=TEST_DB)
    yield TEST_DB
    with db._connect() as conn, conn.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
    db.reset_pool()


# ---------- 快照 UPSERT ----------


def _make_scores() -> FourDimScores:
    return FourDimScores(
        macro=ScoreBreakdown(score=60, rationale="测试"),
        event=ScoreBreakdown(score=55, rationale="测试"),
        industry=ScoreBreakdown(score=70, rationale="测试"),
        company=ScoreBreakdown(score=65, rationale="测试"),
    )


def test_snapshot_upsert_same_day_overwrites(database) -> None:
    day = date(2026, 9, 18)
    repository.upsert_snapshot(repository.SnapshotRow(
        snapshot_date=day, ticker="NVDA", close=210.0, signal="watch", scores=_make_scores(),
    ))
    repository.upsert_snapshot(repository.SnapshotRow(
        snapshot_date=day, ticker="NVDA", close=219.34, signal="accumulate",
        confidence=0.7, scores=_make_scores(),
    ))
    rows = repository.get_snapshots("NVDA", since=day)
    assert len(rows) == 1                      # 同日覆盖，不产生第二行
    assert rows[0].close == 219.34
    assert rows[0].signal == "accumulate"
    assert rows[0].scores.company.score == 65  # scores_json 往返无损


# ---------- 事件 CRUD 与种子 loader ----------


def test_seed_events_load_and_upsert(database) -> None:
    events = load_seed_events()
    assert len(events) == 10                                  # 种子清单 10 条
    assert any(e.event_id == "2026-07-ai-valuation-pullback" for e in events)

    count = upsert_seed_events()
    assert count == 10
    assert count == upsert_seed_events()                      # 幂等：重复入库不增不减

    stored = repository.list_events(source="seed")
    assert len(stored) == 10
    sox = next(e for e in stored if e.event_id == "2026-07-ai-valuation-pullback")
    assert sox.market.vix_peak == 20.7                        # 实测数据往返无损


def test_put_and_list_user_event(database) -> None:
    ev = HistoricalEvent(
        event_id="test-user-event", name="测试用户事件",
        start_date=date(2026, 1, 1), category="tech",
        summary="测试", mechanism="测试", keywords=["测试"],
    )
    repository.put_event(ev, source="user")
    assert ev.event_id in [e.event_id for e in repository.list_events(source="user")]


# ---------- 帖子去重与情绪回填 ----------


def test_x_posts_dedupe_and_sentiment_roundtrip(database) -> None:
    posts = [
        XPost(post_id="p1", author="a", content="NVDA looks strong",
              posted_at=datetime(2026, 9, 17, tzinfo=timezone.utc)),
        XPost(post_id="p2", author="b", content="chip tariff worry",
              posted_at=datetime(2026, 9, 17, tzinfo=timezone.utc)),
    ]
    assert repository.put_x_posts(posts) == 2
    assert repository.put_x_posts(posts) == 0                 # post_id 去重，二次入库 0 新增

    unlabeled = repository.get_unlabeled_posts(limit=10)
    assert {p.post_id for p in unlabeled} >= {"p1", "p2"}

    repository.mark_sentiment([
        SentimentLabel(post_id="p1", sentiment=1, tickers_mentioned=["NVDA"], note="看多"),
        SentimentLabel(post_id="p2", sentiment=-1, tickers_mentioned=["SMH"], note="担忧"),
    ])
    assert repository.get_unlabeled_posts(limit=10) == []     # 全部已打标


# ---------- 抓取节流 ----------


def test_crawl_lock_once_per_day(database) -> None:
    assert repository.try_crawl_lock("x:testuser") is True    # 当日首次：获得锁
    assert repository.try_crawl_lock("x:testuser") is False   # 当日再次：节流拒绝


# ---------- 分析日志 ----------


def test_analysis_run_append_only(database) -> None:
    run_id = repository.append_analysis_run({"input": 1}, {"result": 2})
    assert run_id >= 1                                        # 只追加，返回自增 id
