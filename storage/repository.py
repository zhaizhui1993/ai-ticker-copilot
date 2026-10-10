"""MySQL 唯一读写口：五张表的 repository。

规格：docs/10-module-contracts.md §10.2⑤（签名）+ docs/07-storage/transactions.md（事务约定）
- 快照 UPSERT：ON DUPLICATE KEY UPDATE 单条语句幂等，同日重复分析覆盖旧值
- 帖子批量入库 / 情绪打标回填：各自一个 executemany，单批原子
- analysis_runs 只 INSERT 不 UPDATE
- 调用方不手写 SQL、不管理连接
"""

import json
from datetime import date, datetime, timezone

from pydantic import BaseModel
from pymysql.err import IntegrityError

from domain.events import CurrentEvent, HistoricalEvent, RawArticle, SentimentLabel, XPost
from domain.scoring import FourDimScores
from events_lib.identity import article_hash
from storage.db import get_conn


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


def _insert_current_event(cursor, event: CurrentEvent, identity: str) -> int:
    try:
        cursor.execute(
            "INSERT INTO current_events "
            "(event_id, payload_json, title_hash, raw_url, fetched_at, occurred_date, scope) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (event.event_id, event.model_dump_json(), identity, event.raw_url[:512] or None,
             _utc_naive(event.fetched_at), event.occurred_date, event.scope.value),
        )
        return 1
    except IntegrityError as exc:
        if exc.args[0] != 1062:
            raise
        cursor.execute("SELECT event_id, title_hash FROM current_events "
                       "WHERE event_id=%s OR title_hash=%s", (event.event_id, identity))
        rows = cursor.fetchall()
        if not rows or any(r["title_hash"] != identity for r in rows):
            raise ValueError(f"事件 ID 冲突，拒绝丢弃报道：{event.event_id}") from exc
        return 0  # Only an identical original report is an idempotent duplicate.


def _utc_naive(timestamp: datetime | None) -> datetime:
    timestamp = timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).replace(tzinfo=None)


def put_current_events(events: list[CurrentEvent], title_hashes: list[str] | None = None) -> int:
    """Atomic batch; preserve legacy IDs but reject collisions between different reports."""
    hashes = title_hashes if title_hashes is not None else [
        e.article_id or article_hash(e.raw_url, e.title) for e in events]
    if len(hashes) != len(events):
        raise ValueError("事件与原文 hash 数量不一致")
    if any(e.article_id and e.article_id != h for e, h in zip(events, hashes)):
        raise ValueError("事件去重键必须使用原文身份")
    with get_conn() as conn, conn.cursor() as cursor:
        conn.begin()
        try:
            count = sum(_insert_current_event(cursor, e, h) for e, h in zip(events, hashes))
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise


def store_raw_articles(articles: list[RawArticle]) -> int:
    """Persist original text and first fetch time before extraction; never overwrite on retry."""
    count = 0
    with get_conn() as conn, conn.cursor() as cursor:
        for article in articles:
            identity = article_hash(article.raw_url, article.title)
            try:
                cursor.execute("INSERT INTO raw_news_articles (article_id, payload_json, fetched_at) "
                               "VALUES (%s, %s, %s)",
                               (identity, article.model_dump_json(), _utc_naive(article.fetched_at)))
                count += 1
            except IntegrityError as exc:
                if exc.args[0] != 1062:
                    raise
    return count


def pending_raw_articles(limit: int = 100) -> list[RawArticle]:
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT payload_json FROM raw_news_articles WHERE processed_at IS NULL "
                       "ORDER BY fetched_at, article_id LIMIT %s", (limit,))
        return [RawArticle.model_validate_json(r["payload_json"]) for r in cursor.fetchall()]


def complete_news_batch(articles: list[RawArticle], events: list[CurrentEvent]) -> int:
    """Commit extraction and processed state together; rollback leaves reports retryable."""
    identities = sorted({article_hash(a.raw_url, a.title) for a in articles})
    if any(e.article_id not in identities for e in events):
        raise ValueError("事件没有对应的原始报道")
    if not identities:
        return 0
    with get_conn() as conn, conn.cursor() as cursor:
        conn.begin()
        try:
            # Lock in stable order so overlapping polls cannot resurrect manual lifecycle changes.
            for identity in identities:
                cursor.execute("SELECT article_id FROM raw_news_articles WHERE article_id=%s FOR UPDATE",
                               (identity,))
                if cursor.fetchone() is None:
                    raise ValueError("原始报道尚未入库")
            count = sum(_insert_current_event(cursor, e, e.article_id) for e in events)
            cursor.executemany("UPDATE raw_news_articles SET processed_at=COALESCE(processed_at, %s) "
                               "WHERE article_id=%s", [(_utcnow(), h) for h in identities])
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise


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


def list_current_events(since_date=None, scope: str | None = None, limit: int | None = 100) -> list:
    """当前事件列表（事件中心/API 用；按抓取时间倒序）。"""
    from domain.events import CurrentEvent  # 局部导入避免循环

    query = "SELECT payload_json FROM current_events WHERE 1=1"
    params: list = []
    if scope:
        query += " AND scope = %s"
        params.append(scope)
    query += " ORDER BY fetched_at DESC, event_id"
    if limit is not None and since_date is None:
        query += " LIMIT %s"
        params.append(limit)
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    events = [CurrentEvent.model_validate_json(r["payload_json"]) for r in rows]
    if since_date is not None:
        events = [e for e in events if e.reference_date and e.reference_date >= since_date]
    return events[:limit] if limit is not None else events


def list_active_current_events(as_of: date) -> list[CurrentEvent]:
    """No seven-day cutoff: unresolved policy influence can span months."""
    return [e for e in list_current_events(limit=None)
            if e.status == "active" and (e.reference_date is None or e.reference_date <= as_of)]


def _save_event_change(cursor, before: CurrentEvent, after: CurrentEvent, reason: str):
    cursor.execute("UPDATE current_events SET payload_json=%s WHERE event_id=%s",
                   (after.model_dump_json(), after.event_id))
    cursor.execute("INSERT INTO event_changes (event_id, before_json, after_json, reason, changed_at) "
                   "VALUES (%s, %s, %s, %s, %s)",
                   (after.event_id, before.model_dump_json(), after.model_dump_json(), reason, _utcnow()))


def change_event(event_id: str, *, reason: str, status: str | None = None,
                 merge_into: str | None = None) -> CurrentEvent:
    """Manual lifecycle change or merge, with locked before/after audit in one transaction."""
    if not reason.strip() or bool(status) == bool(merge_into):
        raise ValueError("需提供变更理由，以及状态或合并目标之一")
    if status and status not in {"active", "resolved", "retracted"}:
        raise ValueError("非法事件状态")
    if merge_into == event_id:
        raise ValueError("不能合并到自身")
    with get_conn() as conn, conn.cursor() as cursor:
        conn.begin()
        try:
            found = {}
            for key in sorted({event_id, merge_into} - {None}):
                cursor.execute("SELECT payload_json FROM current_events WHERE event_id=%s FOR UPDATE", (key,))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(key)
                found[key] = CurrentEvent.model_validate_json(row["payload_json"])
            original = found[event_id]
            if original.status == "merged":
                raise ValueError("已合并的事件不可再次变更；请操作目标事件")
            updated = original.model_copy(deep=True)
            if merge_into:
                target = found[merge_into]
                if target.status == "merged":
                    raise ValueError("合并目标不能是已合并事件")
                merged = target.model_copy(deep=True)
                refs = target.evidence + original.evidence
                # Legacy events have no article ledger: preserve their known provenance too.
                for e in (target, original):
                    if not e.evidence:
                        refs.append(RawArticle(source=e.source, raw_url=e.raw_url, title=e.title,
                                               summary=e.summary, published_at=e.published_at,
                                               fetched_at=e.fetched_at))
                merged.evidence = list({article_hash(a.raw_url, a.title): a for a in refs}.values())
                dates = [e.impact_date for e in (target, original) if e.impact_date]
                merged.influence_start_date = min(dates) if dates else None
                merged.tickers_mentioned = sorted(set(target.tickers_mentioned + original.tickers_mentioned))
                _save_event_change(cursor, target, merged, reason)
                updated.status, updated.merged_into = "merged", merge_into
            else:
                updated.status = status
            _save_event_change(cursor, original, updated, reason)
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise


def list_event_changes(event_id: str) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT change_id, before_json, after_json, reason, changed_at "
                       "FROM event_changes WHERE event_id=%s ORDER BY change_id", (event_id,))
        return [{**r, "before_json": json.loads(r["before_json"]),
                 "after_json": json.loads(r["after_json"])} for r in cursor.fetchall()]


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
