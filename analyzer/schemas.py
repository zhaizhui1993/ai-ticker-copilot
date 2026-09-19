"""LLM 结构化输出的批量包装模型。

with_structured_output 对顶层 list 支持不稳，统一包一层 Batch 模型。
单个条目模型复用 domain（CurrentEvent 字段子集 / EventMatchResult）。
"""

from pydantic import BaseModel, Field

from domain.events import EventCategory, EventMatchResult, EventScope


class ExtractedEvent(BaseModel):
    """LLM 事件抽取的单条产物（event_id 由调用方按日期序号补齐）"""

    title: str = Field(max_length=200)
    scope: EventScope
    category: EventCategory
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    tickers_mentioned: list[str] = Field(default_factory=list)
    raw_url: str = ""


class EventBatch(BaseModel):
    events: list[ExtractedEvent] = Field(default_factory=list)


class MatchBatch(BaseModel):
    matches: list[EventMatchResult] = Field(default_factory=list)
