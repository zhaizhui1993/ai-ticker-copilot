# 04 ｜ 历史事件库与类比（events_lib/）

> **职责**：历史事件的 schema 与种子库（31 条）、事实层/联动层初始化、**回调波段挖掘**、**当前事件价格反应富化**、当前事件自动沉淀（滚雪球）、两级类比匹配（硬检索 + LLM 精排）、破位×事件分级规则、经济日历（预告 + 交易约束）。
> **对应代码**：events_lib/（seed_events.yaml / loader.py / matcher.py / mine.py / reaction.py / linkage.py / auto_sediment.py）、scripts/build_events.py、scripts/backfill_events.py、scripts/mine_events.py ｜ **依赖模块**：02（模型）、03（news 管道与行情）、05（体制层判定，用于分级规则） ｜ **实施阶段**：P2（loader 入库）、P4（事件库主体）、P9（日历）、实施期增补（挖掘器/反应富化）
> **内容来源**：原方案 §5.3、§5.3.1、§6.2、§6.2.1、§6.5 + 实施期增补

## 成分文档

| 文档 | 对应代码 | 内容 | 阶段 |
|---|---|---|---|
| [schema.md](schema.md) | domain/events.py | EventCategory / TickerImpact / MarketMetrics / HistoricalEvent（PriceReaction 交叉引用） | P1/P4 |
| [seed-events.md](seed-events.md) | events_lib/seed_events.yaml + loader.py | 31 条种子事件清单、入库约定与数据纪律 | P2/P4 |
| [initialization.md](initialization.md) | scripts/build_events.py + backfill_events.py + events_lib/linkage.py | 事实层/联动层初始化、人工核对、多轮事件约定 | P4 |
| [mine.md](mine.md) | events_lib/mine.py + scripts/mine_events.py | 回调波段挖掘器：从日线自动检出回调→事件草稿（实施期增补） | 增补 |
| [reaction.md](reaction.md) | events_lib/reaction.py | 当前事件价格反应富化：事件日/前趋势/回撤/量比（实施期增补） | 增补 |
| [auto-sedimentation.md](auto-sedimentation.md) | events_lib/auto_sediment.py + scheduler.py（每日 ET 08:00） | 当前事件自动沉淀（v1.1 滚雪球机制） | P9 |
| [matcher.md](matcher.md) | events_lib/matcher.py（LLM 出口在 analyzer/llm.rerank_matches） | 硬检索 + 精排两级匹配与降级 | P4/P6 |
| [breach-classification.md](breach-classification.md) | 05 Engine 体制层硬约束 + prompts 规则 | 破位×事件分级规则（v1.1） | P5/P9 |
| [calendar.md](calendar.md) | web/api/events.py + market.get_earnings_dates | 经济日历：预告 + 交易约束 | P9 |
