# 04 ｜ 历史事件库与类比（events_lib/）

> **职责**：历史事件的 schema 与种子库、事实层/联动层初始化、当前事件自动沉淀（滚雪球）、两级类比匹配（硬检索 + LLM 精排）、破位×事件分级规则、经济日历（预告 + 交易约束）。
> **对应代码**：events_lib/（seed_events.yaml / loader.py / matcher.py）、scripts/build_events.py、scripts/backfill_events.py ｜ **依赖模块**：02（模型）、03（news 管道与 backfill 行情）、05（体制层判定，用于分级规则） ｜ **实施阶段**：P2（loader 入库）、P4（事件库主体）、P9（日历）
> **内容来源**：原方案 §5.3、§5.3.1、§6.2、§6.2.1、§6.5

## 成分文档

| 文档 | 对应代码 | 内容 | 阶段 |
|---|---|---|---|
| [schema.md](schema.md) | domain/events.py | EventCategory / TickerImpact / MarketMetrics / HistoricalEvent | P1/P4 |
| [seed-events.md](seed-events.md) | events_lib/seed_events.yaml + loader.py | 10 条种子事件清单与入库约定 | P2/P4 |
| [initialization.md](initialization.md) | scripts/build_events.py + backfill_events.py | 事实层/联动层初始化、人工核对、多轮事件约定 | P4 |
| [auto-sedimentation.md](auto-sedimentation.md) | 调度任务 | 当前事件自动沉淀（v1.1 滚雪球机制） | P9 |
| [matcher.md](matcher.md) | events_lib/matcher.py | 硬检索 + LLM 精排两级匹配与降级 | P4 |
| [breach-classification.md](breach-classification.md) | matcher/规则 | 破位×事件分级规则（v1.1） | P5/P9 |
| [calendar.md](calendar.md) | 事件中心 | 经济日历：预告 + 交易约束 | P9 |
