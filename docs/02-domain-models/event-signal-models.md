# 02-数据模型 ｜ 当前事件与信号模型

> 模块：02 数据模型 ｜ 成分：事件模型 + 信号模型 ｜ 对应代码：domain/events.py、domain/signal.py ｜ 实施阶段：P1
> 来源：原方案 §5.4 / §5.5

## 5.4 当前事件模型（新闻抽取产物）

```python
class EventScope(str, Enum):
    """事件层级（用户的四类跟进视角，与 category 性质正交）"""
    MACRO_POLICY = "macro_policy"   # 宏观经济政策（利率/财政/关税）
    GEOPOLITICAL = "geopolitical"   # 国际热点（地缘/贸易摩擦/制裁）
    INDUSTRY = "industry"           # 行业事件（AI 产业链）
    COMPANY = "company"             # 企业事件（财报/订单/事故/管理层）

class CurrentEvent(BaseModel):
    event_id: str              # "2026-09-17-001"
    title: str
    occurred_date: date
    scope: EventScope          # 事件层级（宏观政策/国际热点/行业/企业）
    category: EventCategory    # 事件性质（用于历史库类比匹配，定义见 04-events/schema.md）
    summary: str               # ≤300 字
    keywords: list[str]
    tickers_mentioned: list[str]
    source: str                # 新闻来源
    raw_url: str = ""          # 原文链接（去重键之一）
```

scope 与 category 正交：例如"对华芯片管制升级"scope=GEOPOLITICAL、category=REGULATION；"NVDA 财报"scope=COMPANY、category=TECH。前端按 scope 四类展示，类比匹配用 category。

抽取策略：RSS/WebSearch 抓取当日标题摘要 → 规则预过滤（命中宏观/贸易/管制/AI 关键词）→ **LLM 批量一次调用**（10~20 条一批）抽取结构化事件，控制成本（管道细节见 [03-collectors/news-pipeline.md](../03-collectors/news-pipeline.md)）。

## 5.5 信号模型（LLM 结构化输出）

```python
class Action(str, Enum):
    ACCUMULATE = "accumulate"  # 建仓/加仓
    WATCH_ADD = "watch_add"    # 观望偏加仓
    WATCH = "watch"            # 观望
    REDUCE = "reduce"          # 减仓/回避

class TickerSignal(BaseModel):
    ticker: str
    action: Action
    confidence: float          # 0~1
    reason: str                # 须引用四维分数与事件类比
    risks: list[str]
    price_target_hint: str | None  # 软提示，如"等回踩 MA50 再考虑"

class AnalysisResult(BaseModel):
    generated_at: str
    signals: list[TickerSignal]
    market_summary: str        # 宏观与事件面总述（中文 2~3 句）
    disclaimer: str = "本报告仅供个人研究参考，不构成投资建议。"
```
