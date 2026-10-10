"""Exercise repository transactions offline using SQLite's real rollback/unique constraints.

The adapter translates placeholders and drops FOR UPDATE, so it does NOT validate
MySQL DDL or concurrent row locking. Native MySQL checks live in test_storage.py.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import sqlite3

import pytest
from pymysql.err import IntegrityError

from analyzer.rule_extract import extract_events
from domain.events import RawArticle
from storage import repository


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, query, args=()):
        try:
            return self.cursor.execute(query.replace("%s", "?").replace(" FOR UPDATE", ""), args)
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode in {sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY, sqlite3.SQLITE_CONSTRAINT_UNIQUE}:
                raise IntegrityError(1062, str(exc)) from exc
            raise

    def executemany(self, query, rows):
        for row in rows:
            self.execute(query, row)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self.cursor.fetchall()]


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return Cursor(self.connection)

    def begin(self):
        self.connection.execute("BEGIN")

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()


@pytest.fixture
def ledger(monkeypatch):
    # Serialize datetimes explicitly; avoid SQLite's deprecated implicit adapter.
    sqlite3.register_adapter(datetime, lambda value: value.isoformat())
    sqlite3.register_adapter(date, lambda value: value.isoformat())
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE raw_news_articles (article_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                                       fetched_at TEXT NOT NULL, processed_at TEXT);
        CREATE TABLE current_events (event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                                     title_hash TEXT UNIQUE NOT NULL, raw_url TEXT,
                                     fetched_at TEXT NOT NULL, occurred_date TEXT, scope TEXT);
        CREATE TABLE event_changes (change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    event_id TEXT NOT NULL, before_json TEXT NOT NULL,
                                    after_json TEXT NOT NULL, reason TEXT NOT NULL, changed_at TEXT NOT NULL);
    """)

    @contextmanager
    def get_conn():
        yield Connection(connection)
    monkeypatch.setattr(repository, "get_conn", get_conn)
    yield connection
    connection.close()


def articles():
    return [RawArticle(source=ticker, raw_url=f"https://example.com/{ticker}", title=f"{ticker} earnings beat",
                       published_at=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                       fetched_at=datetime(2026, 7, 1, 13, tzinfo=timezone.utc)) for ticker in ("NVDA", "AMD")]


def seed():
    reports = articles()
    events = extract_events(reports, ["NVDA", "AMD"])
    repository.store_raw_articles(reports)
    repository.complete_news_batch(reports, events)
    return reports, events


def test_multiple_polls_and_rewritten_titles_preserve_original_identity(ledger):
    reports = articles()
    for a in reports:
        assert repository.store_raw_articles([a]) == 1
        events = extract_events([a], ["NVDA", "AMD"])
        events[0].title = "LLM 重写标题"
        assert repository.complete_news_batch([a], events) == 1
    assert len(repository.list_current_events()) == 2
    assert not repository.pending_raw_articles()
    assert repository.store_raw_articles([reports[0].model_copy(update={"fetched_at": datetime.now(timezone.utc)})]) == 0
    assert repository.complete_news_batch(reports, extract_events(reports, [])) == 0
    assert {e.article_id for e in repository.list_current_events()} == {
        repository.article_hash(a.raw_url, a.title) for a in reports}
    assert all(e.fetched_at == reports[0].fetched_at for e in repository.list_current_events())


def test_partial_batch_failure_rolls_back_then_retries_from_archived_articles(ledger, monkeypatch):
    reports = articles()
    events = extract_events(reports, [])
    repository.store_raw_articles(reports)
    original = repository._insert_current_event

    def fail_second(cursor, event, identity):
        if event.event_id == events[1].event_id:
            raise RuntimeError("simulated write failure")
        return original(cursor, event, identity)
    monkeypatch.setattr(repository, "_insert_current_event", fail_second)
    with pytest.raises(RuntimeError):
        repository.complete_news_batch(reports, events)
    assert not repository.list_current_events()
    pending = repository.pending_raw_articles()
    assert len(pending) == 2
    monkeypatch.setattr(repository, "_insert_current_event", original)
    assert repository.complete_news_batch(pending, extract_events(pending, [])) == 2
    assert not repository.pending_raw_articles()


def test_poll_retries_archived_articles_when_feed_is_now_empty(ledger, monkeypatch):
    from collectors import news
    from events_lib import reaction
    monkeypatch.setattr(news.llm, "llm_available", lambda: False)
    monkeypatch.setattr(reaction, "enrich_events", lambda events, market: events)
    monkeypatch.setattr(news, "_notify_macos", lambda _: None)
    original = repository.complete_news_batch

    def fail(*args):
        raise RuntimeError("temporary failure")
    monkeypatch.setattr(repository, "complete_news_batch", fail)
    first = news.process_articles(articles(), [])
    assert first["db_error"] and first["stored"] == 0
    assert len(repository.pending_raw_articles()) == 2
    monkeypatch.setattr(repository, "complete_news_batch", original)
    second = news.process_articles([], [])
    assert second["fetched"] == 0 and second["stored"] == 2


def test_legacy_primary_key_collision_raises_instead_of_dropping_article(ledger):
    events = extract_events(articles(), [])
    for event in events:
        event.event_id = "2026-10-10-001"
        event.article_id = None
    assert repository.put_current_events([events[0]]) == 1
    with pytest.raises(ValueError, match="ID 冲突"):
        repository.put_current_events([events[1]])
    assert repository.put_current_events([events[0]]) == 0
    assert len(repository.list_current_events()) == 1


def test_long_lived_events_lifecycle_merge_preserves_age_and_audit(ledger):
    reports = articles()
    reports[1].published_at += timedelta(days=30)
    events = extract_events(reports, [])
    repository.store_raw_articles(reports)
    repository.complete_news_batch(reports, events)
    today = date(2026, 10, 1)
    assert len(repository.list_active_current_events(today)) == 2
    repository.change_event(events[0].event_id, status="resolved", reason="政策结束")
    assert len(repository.list_active_current_events(today)) == 1
    repository.change_event(events[0].event_id, status="active", reason="复核确认继续有效")
    repository.change_event(events[0].event_id, merge_into=events[1].event_id, reason="人工确认同一政策报道")
    active = repository.list_active_current_events(today)
    assert len(active) == 1
    assert active[0].event_id == events[1].event_id
    assert active[0].impact_date == events[0].reference_date  # No age reset to target's newer article.
    assert len(active[0].evidence) == 2
    changes = repository.list_event_changes(events[0].event_id)
    assert len(changes) == 3
    assert changes[-1]["before_json"]["status"] == "active"
    assert changes[-1]["after_json"]["status"] == "merged"
    assert changes[-1]["reason"] == "人工确认同一政策报道"
    # A retry cannot overwrite manual lifecycle changes or reactivate the source.
    assert repository.complete_news_batch(reports, events) == 0
    assert len(repository.list_active_current_events(today)) == 1
    with pytest.raises(ValueError):
        repository.change_event(events[0].event_id, status="active", reason="undo")


def test_merge_does_not_reactivate_resolved_target_and_rejects_bad_changes(ledger):
    _, events = seed()
    repository.change_event(events[1].event_id, status="resolved", reason="已结束")
    repository.change_event(events[0].event_id, merge_into=events[1].event_id, reason="同一报道")
    assert not repository.list_active_current_events(date(2026, 10, 1))
    for kwargs in ({"status": "retracted", "reason": " "},
                   {"status": "merged", "reason": "invalid"},
                   {"merge_into": events[1].event_id, "reason": "self"}):
        with pytest.raises(ValueError):
            repository.change_event(events[1].event_id, **kwargs)


def test_audit_write_failure_rolls_back_lifecycle_change(ledger, monkeypatch):
    _, events = seed()
    original = Cursor.execute

    def fail_audit(self, query, args=()):
        if query.startswith("INSERT INTO event_changes"):
            raise RuntimeError("audit failed")
        return original(self, query, args)
    monkeypatch.setattr(Cursor, "execute", fail_audit)
    with pytest.raises(RuntimeError):
        repository.change_event(events[0].event_id, status="retracted", reason="source correction")
    assert len(repository.list_active_current_events(date(2026, 10, 1))) == 2
    assert repository.list_event_changes(events[0].event_id) == []


def test_nonduplicate_integrity_errors_are_not_suppressed(monkeypatch):
    class FailingCursor:
        def execute(self, *args):
            raise IntegrityError(1048, "column cannot be null")
    event = extract_events(articles(), [])[0]
    with pytest.raises(IntegrityError, match="cannot be null"):
        repository._insert_current_event(FailingCursor(), event, event.article_id)


def test_since_date_uses_eastern_publication_proxy_not_fetch_date(ledger):
    seed()
    assert repository.list_current_events(since_date=date(2026, 7, 2)) == []
    assert len(repository.list_current_events(since_date=date(2026, 7, 1), limit=1)) == 1
