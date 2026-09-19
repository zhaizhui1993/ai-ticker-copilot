"""新闻事件增量管道（news.py）。

规格：docs/03-collectors/news-pipeline.md

轮询触发 ──► 各源抓取（RSS / Google News 关键词流）
        ──► 去重：raw_url + 标题 hash，已入库直接跳过
        ──► 规则预过滤：命中四类事件关键词库，或提及股票池 ticker
        ──► 事件抽取（P3 为规则版占位，P6 换 LLM 批量单次调用，签名不变）
        ──► 新事件入库 → 变化检测（未读徽章 / 可选 macOS 通知）

约定：本管道不触发完整分析、不写 snapshots；单源失败只跳过该源并记录。
"""

import random
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser

from analyzer import llm
from config.settings import settings
from domain.events import RawArticle
from storage import repository

# 内置默认源（NEWS_RSS_FEEDS 可追加；Reuters 公开 RSS 已停服不列入）
DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("YahooFinance", "https://finance.yahoo.com/news/rssindex"),
]

# Google News 主题流（免 key，企业事件的主要来源）
GOOGLE_NEWS_THEMES = [
    "AI chip", "semiconductor", "chip export controls",
    "Fed interest rate", "data center capex", "Nvidia",
]

# 四类事件预过滤关键词（中英混合，小写匹配）
PREFILTER_KEYWORDS = [
    # 宏观政策
    "加息", "降息", "利率", "美联储", "通胀", "非农", "国债", "收益率", "财政", "关税",
    "rate hike", "rate cut", "fed", "fomc", "cpi", "inflation", "payroll", "treasury", "tariff",
    # 国际热点
    "制裁", "出口管制", "贸易", "地缘",
    "sanction", "export control", "trade war",
    # 行业（AI 产业链）
    "芯片", "半导体", "算力", "光模块", "数据中心", "代工",
    "ai ", "chip", "semiconductor", "gpu", "capex", "data center", "foundry",
    # 企业
    "财报", "指引", "营收", "订单", "管理层",
    "earnings", "guidance", "revenue", "order", "ceo",
]

_ARTICLE_MAX_AGE_HOURS = 48
_TAG_RE = re.compile(r"<[^>]+>")


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"


def _clean(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _fetch_feed(source: str, url: str) -> list[RawArticle]:
    """单源抓取；失败返回空（单源失败不影响整体管道）。"""
    try:
        feed = feedparser.parse(url)
        now = datetime.now(timezone.utc)
        articles: list[RawArticle] = []
        for entry in feed.entries[:30]:
            published = None
            struct = getattr(entry, "published_parsed", None)
            if struct:
                published = datetime(*struct[:6], tzinfo=timezone.utc)
                if now - published > timedelta(hours=_ARTICLE_MAX_AGE_HOURS):
                    continue  # 超过 48h 的旧文不进管道
            articles.append(RawArticle(
                source=source,
                raw_url=getattr(entry, "link", "") or "",
                title=_clean(getattr(entry, "title", "")),
                summary=_clean(getattr(entry, "summary", ""))[:500],
                fetched_at=now,
            ))
        return articles
    except Exception as exc:
        print(f"[news] 源 {source} 抓取失败，跳过：{exc}")
        return []


def fetch_all_articles(pool_tickers: list[str]) -> list[RawArticle]:
    """全部源抓取：内置 RSS + NEWS_RSS_FEEDS 追加 + Google News 主题流与股票池关键词流。"""
    feeds = list(DEFAULT_FEEDS)
    if settings.news_rss_feeds:
        for url in settings.news_rss_feeds.split(","):
            url = url.strip()
            if url:
                feeds.append(("Custom", url))
    themes = list(GOOGLE_NEWS_THEMES) + [f"{t} stock" for t in pool_tickers]

    articles: list[RawArticle] = []
    for source, url in feeds:
        articles.extend(_fetch_feed(source, url))
        time.sleep(random.uniform(0.5, 1.0))
    for theme in themes:
        articles.extend(_fetch_feed("GoogleNews", google_news_url(theme)))
        time.sleep(random.uniform(0.5, 1.0))
    return articles


def prefilter(articles: list[RawArticle], pool_tickers: list[str]) -> list[RawArticle]:
    """规则预过滤：命中四类关键词，或提及股票池 ticker。"""
    result = []
    for article in articles:
        text = f"{article.title} {article.summary}".lower()
        hit = any(k in text for k in PREFILTER_KEYWORDS)
        if not hit and pool_tickers:
            padded = f" {text} "
            hit = any(f" {t.lower()} " in padded for t in pool_tickers)
        if hit:
            result.append(article)
    return result


def _notify_macos(new_count: int) -> None:
    """可选 macOS 系统通知（osascript，零依赖；NEW_EVENT_NOTIFY=true 时启用）。"""
    if not settings.new_event_notify:
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "新增 {new_count} 条事件，请查看事件中心" with title "ai-ticker-copilot"'],
            timeout=5, check=False,
        )
    except Exception:
        pass  # 通知失败绝不影响主流程


def poll_once(pool_tickers: list[str]) -> dict:
    """事件管道单轮：抓取→去重→预过滤→抽取→入库。返回本轮摘要（不触发分析）。"""
    articles = fetch_all_articles(pool_tickers)
    hashes = [repository.article_hash(a.raw_url, a.title) for a in articles]

    try:
        existing = repository.has_title_hashes(hashes)
        db_ok = True
    except Exception as exc:
        print(f"[news] 去重查询失败（DB 不可用？）：{exc}")
        return {"fetched": len(articles), "new": 0, "filtered": 0,
                "stored": 0, "db_error": str(exc), "events": []}

    new_articles = [a for a, h in zip(articles, hashes) if h not in existing]
    filtered = prefilter(new_articles, pool_tickers)
    events = llm.extract_events(filtered, pool_tickers)

    stored = 0
    if events:
        event_hashes = [repository.article_hash(e.raw_url, e.title) for e in events]
        try:
            stored = repository.put_current_events(events, event_hashes)
            _notify_macos(stored)
        except Exception as exc:
            print(f"[news] 事件入库失败：{exc}")
            return {"fetched": len(articles), "new": len(new_articles),
                    "filtered": len(filtered), "stored": 0,
                    "db_error": str(exc), "events": events}

    return {
        "fetched": len(articles),
        "new": len(new_articles),
        "filtered": len(filtered),
        "stored": stored,
        "events": events,
    }


class NewsCollector:
    """DataSource 形态的事件管道入口（调度器/工厂用）。"""

    name = "news-rss"

    def poll_once(self, pool_tickers: list[str]) -> dict:
        return poll_once(pool_tickers)

    async def poll_once_async(self, pool_tickers: list[str]) -> dict:
        return poll_once(pool_tickers)
