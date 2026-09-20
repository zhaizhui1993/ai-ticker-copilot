"""事件域模型：历史事件库、当前事件、类比产物、新闻与 X 原始载体。

规格：docs/04-events/schema.md（HistoricalEvent 系列）
     docs/02-domain-models/event-signal-models.md（CurrentEvent）
     docs/10-module-contracts.md §10.2②（EventMatchResult / AnalogyConclusion / RawArticle）
"""

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    """事件性质（历史库类比匹配用）"""

    MACRO = "macro"            # 宏观政策/贸易摩擦
    MONETARY = "monetary"      # 货币政策
    REGULATION = "regulation"  # 监管/出口管制
    TECH = "tech"              # 技术冲击
    CRISIS = "crisis"          # 危机事件


class EventScope(str, Enum):
    """事件层级（四类跟进视角，与 category 正交）"""

    MACRO_POLICY = "macro_policy"   # 宏观经济政策
    GEOPOLITICAL = "geopolitical"   # 国际热点
    INDUSTRY = "industry"           # 行业事件（AI 产业链）
    COMPANY = "company"             # 企业事件


# ---------- 历史事件库 ----------


class TickerImpact(BaseModel):
    ticker: str                        # 个股/ETF/指数，如 NVDA、SMH、SPX
    direction: Literal[-1, 0, 1]       # -1 负 / 0 中性 / +1 正
    magnitude: float = Field(ge=0, le=1)
    drawdown: float | None = None      # 最大回撤 %（如 -20.3）
    drawdown_days: int | None = None   # 达底自然天数
    recovery_days: int | None = None   # 收复前高天数（None=至今未收复）


class MarketMetrics(BaseModel):
    sp500_1w: float | None = None
    sp500_1m: float | None = None
    nasdaq_1w: float | None = None
    nasdaq_1m: float | None = None
    vix_peak: float | None = None
    fed_rate_change_bps: int | None = None  # 利率事件填，非利率事件留空


class HistoricalEvent(BaseModel):
    event_id: str                      # 如 "2025-01-deepseek-shock"
    name: str
    start_date: date
    end_date: date | None = None
    category: EventCategory
    summary: str = Field(max_length=200)   # ≤200 字背景（供 LLM 类比，务必精炼）
    mechanism: str                     # 传导机制一句话
    keywords: list[str] = Field(default_factory=list)
    tickers_affected: list[TickerImpact] = Field(default_factory=list)
    market: MarketMetrics = Field(default_factory=MarketMetrics)
    tags: list[str] = Field(default_factory=list)


# ---------- 当前事件（新闻抽取产物） ----------


class PriceReaction(BaseModel):
    """事件关联个股的价格反应（入库时富化；口径见 events_lib/reaction.py）"""

    ticker: str
    event_day_pct: float | None = None    # 事件日（或最近已收交易日）涨跌 %
    prior_5d_pct: float | None = None     # 事件前 5 日累计 %（背景趋势）
    prior_20d_pct: float | None = None    # 事件前 20 日累计 %
    drawdown_52w: float | None = None     # 事件时点距 52 周高点回撤 %（≤0）
    volume_ratio: float | None = None     # 事件日量比（vs 前 20 日均量）
    as_of: date | None = None             # 反应计算所用的最后交易日
    note: str = ""                        # 如"事件日未收盘，取最近交易日"


class CurrentEvent(BaseModel):
    event_id: str                      # "2026-09-20-001"
    title: str
    occurred_date: date
    scope: EventScope
    category: EventCategory
    summary: str = Field(max_length=300)
    keywords: list[str] = Field(default_factory=list)
    tickers_mentioned: list[str] = Field(default_factory=list)
    source: str
    raw_url: str = ""                  # 去重键之一
    price_reactions: list[PriceReaction] = Field(default_factory=list)  # 入库时富化


class RawArticle(BaseModel):
    """新闻管道的原始文章（去重键 = raw_url + 标题 hash）"""

    source: str
    raw_url: str
    title: str
    summary: str = ""
    fetched_at: datetime | None = None


# ---------- 类比产物（matcher 输出） ----------


class EventMatchResult(BaseModel):
    """LLM 精排的 single 匹配结果（docs/04-events/matcher.md）"""

    event_id: str
    similarity: float = Field(ge=0, le=1)  # ≥0.6 才进入类比聚合
    direction: Literal[-1, 0, 1]
    magnitude: float = Field(ge=0, le=1, default=0.5)
    affected_tickers: list[str] = Field(default_factory=list)
    analogy_notes: str = ""                # 必须给出可核对的匹配理由


class AnalogyConclusion(BaseModel):
    """synthesize_analogy 的聚合结论（契约 §10.2②）"""

    matched_event_ids: list[str] = Field(default_factory=list)
    avg_drawdown: float | None = None       # 平均最大回撤 %
    avg_drawdown_days: int | None = None    # 平均价底天数
    avg_recovery_days: int | None = None    # 平均收复天数
    sample_size: int = 0                    # n<3 时消费方须标注"样本不足"
    confidence: Literal["high", "low"] = "low"  # low = 硬检索/规则降级产物
    note: str = ""                          # 样本不足/降级原因等标注（v1.1 防自欺）


# ---------- X 帖子（爬虫产物 + 情绪打标回填） ----------


class XPost(BaseModel):
    post_id: str                      # status URL 取 post_id，去重唯一键
    author: str
    content: str = ""
    url: str = ""
    likes: int | None = None
    posted_at: datetime | None = None
    collected_at: datetime | None = None
    reply_to: str | None = None       # 回复对象 handle（不带 @）；原创帖为 None
    sentiment: int | None = None      # -1/0/1，打标后回填
    sentiment_note: str = ""
    tickers_mentioned: list[str] = Field(default_factory=list)


class SentimentLabel(BaseModel):
    """LLM 情绪打标的单条输出"""

    post_id: str
    sentiment: Literal[-1, 0, 1]
    tickers_mentioned: list[str] = Field(default_factory=list)
    note: str = ""
