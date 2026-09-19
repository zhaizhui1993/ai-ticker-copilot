"""信号模型（LLM 结构化输出）。

规格：docs/02-domain-models/event-signal-models.md §5.5
     docs/06-analyzer/prompts.md（输出规则与免责声明约束）
"""

from enum import Enum

from pydantic import BaseModel, Field

DISCLAIMER = "本报告仅供个人研究参考，不构成投资建议。"


class Action(str, Enum):
    ACCUMULATE = "accumulate"  # 建仓/加仓
    WATCH_ADD = "watch_add"    # 观望偏加仓
    WATCH = "watch"            # 观望
    REDUCE = "reduce"          # 减仓/回避


class TickerSignal(BaseModel):
    ticker: str
    action: Action
    confidence: float = Field(ge=0, le=1)
    reason: str                # 须引用四维分数与事件类比；偏离分档必须说明
    risks: list[str] = Field(default_factory=list, min_length=0)
    price_target_hint: str | None = None  # 软提示，如"等回踩 MA50 再考虑"


class AnalysisResult(BaseModel):
    generated_at: str          # ISO 时间戳
    signals: list[TickerSignal] = Field(default_factory=list)
    market_summary: str        # 宏观与事件面总述（中文 2~3 句）
    disclaimer: str = DISCLAIMER
