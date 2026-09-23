"""MySQL 唯一读写口：五张表的 repository。

规格：docs/10-module-contracts.md §10.2⑤（签名）+ docs/07-storage/transactions.md（事务约定）
- 快照 UPSERT：ON DUPLICATE KEY UPDATE 单条语句幂等，同日重复分析覆盖旧值
- 帖子批量入库 / 情绪打标回填：各自一个 executemany，单批原子
- analysis_runs 只 INSERT 不 UPDATE
- 调用方不手写 SQL、不管理连接
"""

import hashlib
import json
from datetime import date, datetime, timezone

from pydantic import BaseModel

from domain.events import HistoricalEvent, SentimentLabel, XPost
from domain.scoring import FourDimScores
from storage.db import get_conn


def article_hash(raw_url: str, title: str) -> str:
    """文章去重键：sha256(raw_url + | + title)。"""
    return hashlib.sha256(f"{raw_url}|{title}".encode()).hexdigest()

# 时间戳统一存 UTC（docs/03-collectors/scheduler.md 时区约定）


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SnapshotRow(BaseModel):
    """snapshots 表的行形态（快照 UPSERT 的输入）"""

    snapshot_date: date
    ticker: str
    close: float | None = None
    change_pct: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    rsi14: float | None = None
    scores: FourDimScores | None = None
    signal: str | None = None
    confidence: float | None = None
    analysis: dict | None = None


# ---------- 快照 ----------


def upsert_snapshot(row: SnapshotRow) -> None:
    scores_json = row.scores.model_dump_json() if row.scores else "{}"
    analysis_json = json.dumps(row.analysis, ensure_ascii=False) if row.analysis else None
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO snapshots
              (snapshot_date, ticker, close, change_pct, ma20, ma50, rsi14,
               scores_json, signal, confidence, analysis_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              close=VALUES(close), change_pct=VALUES(change_pct),
              ma20=VALUES(ma20), ma50=VALUES(ma50), rsi14=VALUES(rsi14),
              scores_json=VALUES(scores_json), signal=VALUES(signal),
              confidence=VALUES(confidence), analysis_json=VALUES(analysis_json)
            """,
            (row.snapshot_date, row.ticker, row.close, row.change_pct,
             row.ma20, row.ma50, row.rsi14, scores_json,
             row.signal, row.confidence, analysis_json),
        )


def list_snapshot_tickers() -> list[str]:
    """快照表里出现过的全部 ticker（回测脚本遍历用）。"""
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT DISTINCT ticker FROM snapshots ORDER BY ticker")
        return [r["ticker"] for r in cursor.fetchall()]


def get_snapshots(ticker: str, since: date) -> list[SnapshotRow]:
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM snapshots WHERE ticker=%s AND snapshot_date >= %s "
            "ORDER BY snapshot_date",
            (ticker, since),
        )
        rows = cursor.fetchall()
    result = []
    for r in rows:
        result.append(SnapshotRow(
            snapshot_date=r["snapshot_date"],
            ticker=r["ticker"],
            close=float(r["close"]) if r["close"] is not None else None,
            change_pct=float(r["change_pct"]) if r["change_pct"] is not None else None,
            ma20=float(r["ma20"]) if r["ma20"] is not None else None,
            ma50=float(r["ma50"]) if r["ma50"] is not None else None,
            rsi14=float(r["rsi14"]) if r["rsi14"] is not None else None,
            scores=FourDimScores.model_validate_json(r["scores_json"]) if r["scores_json"] else None,
            signal=r["signal"],
            confidence=float(r["confidence"]) if r["confidence"] is not None else None,
            analysis=json.loads(r["analysis_json"]) if r["analysis_json"] else None,
        ))
    return result


# ---------- 历史事件库 ----------


def put_event(event: HistoricalEvent, source: str = "seed") -> None:
    """幂等 upsert（seed 重载更新 payload；source 保留首次来源）。"""
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO events (event_id, payload_json, source) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json), source=VALUES(source)
            """,
            (event.event_id, event.model_dump_json(), source),
        )


def list_events(source: str | None = None) -> list[HistoricalEvent]:
    query = "SELECT payload_json FROM events"
    params: tuple = ()
    if source:
        query += " WHERE source=%s"
        params = (source,)
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return [HistoricalEvent.model_validate_json(r["payload_json"]) for r in rows]


# ---------- X 帖子 ----------


def put_x_posts(posts: list[XPost]) -> int:
    """批量入库（post_id 主键去重，INSERT IGNORE），返回新增条数。"""
    if not posts:
        return 0
    data = [
        (p.post_id, p.author, p.content, p.url, p.likes,
         p.posted_at, p.collected_at or _utcnow(), p.reply_to)
        for p in posts
    ]
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT IGNORE INTO x_posts
              (post_id, author, content, url, likes, posted_at, collected_at, reply_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            data,
        )
        return cursor.rowcount


def mark_sentiment(labels: list[SentimentLabel]) -> int:
    """情绪打标回填（批量 UPDATE），返回更新条数。"""
    if not labels:
        return 0
    data = [
        (l.sentiment, l.note[:500], ",".join(l.tickers_mentioned)[:255], l.post_id)
        for l in labels
    ]
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.executemany(
            """
            UPDATE x_posts
            SET sentiment=%s, sentiment_note=%s, tickers_mentioned=%s
            WHERE post_id=%s
            """,
            data,
        )
        return cursor.rowcount


def get_unlabeled_posts(limit: int = 100) -> list[XPost]:
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT post_id, author, content, url, likes, posted_at, collected_at
            FROM x_posts WHERE sentiment IS NULL
            ORDER BY posted_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    return [XPost(**r) for r in rows]


# ---------- 抓取节流 ----------


def try_crawl_lock(state_key: str) -> bool:
    """每博主每天最多一次的节流：美东当日已抓返回 False，否则记录并返回 True。

    crawl_state.last_crawl_at 存 UTC（表内 DATETIME 无时区，读取后按 UTC 解释）。
    """
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    now_utc = _utcnow()
    today_et = now_utc.replace(tzinfo=timezone.utc).astimezone(eastern).date()

    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT last_crawl_at FROM crawl_state WHERE state_key=%s", (state_key,)
        )
        row = cursor.fetchone()
        if row is not None:
            last = row["last_crawl_at"].replace(tzinfo=timezone.utc).astimezone(eastern)
            if last.date() == today_et:
                return False
        cursor.execute(
            "REPLACE INTO crawl_state (state_key, last_crawl_at) VALUES (%s, %s)",
            (state_key, now_utc),
        )
        return True


# ---------- 当前事件（新闻管道产物） ----------


def put_current_events(events: list, title_hashes: list[str] | None = None) -> int:
    """当前事件批量入库（event_id 主键 + title_hash 唯一键双去重），返回新增条数。

    title_hashes 与 events 等长对位（调用方在 news 管道生成）。
    """
    from domain.events import CurrentEvent  # 局部导入避免循环

    if not events:
        return 0
    hashes = title_hashes or [article_hash(e.raw_url, e.title) for e in events]
    data = [
        (e.event_id, e.model_dump_json(), h, e.raw_url[:512] or None,
         _utcnow(), e.occurred_date, e.scope.value)
        for e, h in zip(events, hashes)
    ]
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT IGNORE INTO current_events
              (event_id, payload_json, title_hash, raw_url, fetched_at, occurred_date, scope)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            data,
        )
        return cursor.rowcount


def has_title_hashes(hashes: list[str]) -> set[str]:
    """已入库的文章 hash 集合（管道去重依据）。"""
    if not hashes:
        return set()
    placeholders = ",".join(["%s"] * len(hashes))
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"SELECT title_hash FROM current_events WHERE title_hash IN ({placeholders})",
            tuple(hashes),
        )
        return {r["title_hash"] for r in cursor.fetchall()}


def list_current_events(since_date=None, scope: str | None = None, limit: int = 100) -> list:
    """当前事件列表（事件中心/API 用；按抓取时间倒序）。"""
    from domain.events import CurrentEvent  # 局部导入避免循环

    query = "SELECT payload_json FROM current_events WHERE 1=1"
    params: list = []
    if since_date is not None:
        query += " AND occurred_date >= %s"
        params.append(since_date)
    if scope:
        query += " AND scope = %s"
        params.append(scope)
    query += " ORDER BY fetched_at DESC LIMIT %s"
    params.append(limit)
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    return [CurrentEvent.model_validate_json(r["payload_json"]) for r in rows]


# ---------- 分析日志 ----------


def append_analysis_run(input_json: dict, result_json: dict) -> int:
    """只追加，不更新（保留全量历史，供回放）。"""
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO analysis_runs (created_at, input_json, result_json)
            VALUES (%s, %s, %s)
            """,
            (_utcnow(),
             json.dumps(input_json, ensure_ascii=False),
             json.dumps(result_json, ensure_ascii=False)),
        )
        return cursor.lastrowid
