"""Stable identity is derived only from the original article, never LLM output."""
import hashlib

from domain.events import RawArticle


def article_hash(raw_url: str, title: str) -> str:
    return hashlib.sha256(f"{raw_url}|{title}".encode("utf-8")).hexdigest()


def event_provenance(article: RawArticle) -> dict:
    identity = article_hash(article.raw_url, article.title)
    return {"event_id": "evt_" + identity[:40], "article_id": identity,
            "source": article.source, "raw_url": article.raw_url,
            "evidence": [article], "published_at": article.published_at,
            "fetched_at": article.fetched_at}
