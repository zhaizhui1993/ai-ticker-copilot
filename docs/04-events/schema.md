# 04-事件库 ｜ 数据模型（HistoricalEvent 系列）

> 模块：04 历史事件库 ｜ 成分：schema ｜ 对应代码：domain/events.py ｜ 实施阶段：P1 定义 / P4 使用
> 来源：原方案 §5.3（schema 部分）

```python
class EventCategory(str, Enum):
    MACRO = "macro"            # 宏观政策/贸易摩擦
    MONETARY = "monetary"      # 货币政策
    REGULATION = "regulation"  # 监管/出口管制
    TECH = "tech"              # 技术冲击
    CRISIS = "crisis"          # 危机事件

class TickerImpact(BaseModel):
    ticker: str                     # 标的（个股/ETF/指数，如 NVDA、SMH、SPX、IXIC）
    direction: Literal[-1, 0, 1]    # -1 负 / 0 中性 / +1 正
    magnitude: float                # 影响强度 0~1（ge=0, le=1 约束）
    drawdown: float | None          # 最大回撤 %（如 -20.3）
    drawdown_days: int | None       # 达底自然天数
    recovery_days: int | None       # 收复前高天数（None=至今未收复）
    # ---- 事件前状态（v1.3；T0 前一日收盘口径，scripts/backfill_pre_state.py 回填）----
    pre_drawdown_52w: float | None  # 事件前距 52 周高点回撤 %（≤0）
    pre_bias_ma200: float | None    # 事件前收盘/MA200 乖离 %（拥挤度代理）
    pre_runup_20d: float | None     # 事件前 20 交易日涨幅 %
    pre_rsi14: float | None         # 事件前 RSI14

class MarketMetrics(BaseModel):
    sp500_1w: float | None          # 事件后 1 周 SPX 涨跌 %
    sp500_1m: float | None
    nasdaq_1w: float | None
    nasdaq_1m: float | None
    vix_peak: float | None
    fed_rate_change_bps: int | None # 若涉及利率变动（基点）

class HistoricalEvent(BaseModel):
    event_id: str                   # 如 "2025-01-deepseek-shock"
    name: str                       # 如 "DeepSeek 发布冲击算力叙事"
    start_date: date
    end_date: date | None
    category: EventCategory
    summary: str                    # ≤200 字背景（供 LLM 类比，务必精炼）
    mechanism: str                  # 传导机制一句话，如"低成本模型动摇算力需求叙事，估值下杀"
    keywords: list[str]             # 检索词，如 ["deepseek","开源模型","capex"]
    tickers_affected: list[TickerImpact]
    market: MarketMetrics
    tags: list[str]
    fizzled: bool = False           # 对照事件（v1.3）：预期冲击未兑现，浅回撤参与 base-rate 修正
```

> 配套的当前事件模型（EventScope / PriceReaction / CurrentEvent）与信号模型见 [02-domain-models/event-signal-models.md](../02-domain-models/event-signal-models.md)——**PriceReaction**（事件关联个股的价格反应五指标，入库时由 events_lib/reaction.py 富化，详见 [reaction.md](reaction.md)）挂在 CurrentEvent.price_reactions 上；匹配产物 EventMatchResult / AnalogyConclusion 的契约见 [10-module-contracts.md §10.2②](../10-module-contracts.md)。
