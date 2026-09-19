# 05-评分 ｜ 事件面（event_score.py）

> 模块：05 评分引擎 ｜ 成分：事件 scorer ｜ 权重 25%（= 历史类比 80% + X 情绪 20%） ｜ 实施阶段：P5
> 来源：原方案 §6.1②

```
对每个 ticker：
事件影响分 = Σ 命中事件 ( TickerImpact.direction × magnitude × similarity × 新鲜度衰减 )
新鲜度衰减 = 0.5 ^ (事件距今天数 / 7)      # 半衰期 7 天
```

- 历史事件未直接列出该标的时，按同 segment 的历史影响取 0.5 折扣。
- X 情绪分：已打标帖子按 ticker 聚合，正帖占比 50% 映射为中性 50 分，线性映射至 0-100。
- 总分 = 50 + 类比分×40 + (情绪分-50)×0.2，截断 [0,100]。
- X 数据缺失时情绪分计 50（中性），rationale 标注"X 数据缺失"。
- 输入来源：类比结论由 [04-events/matcher.md](../04-events/matcher.md) 产出；情绪标签由 [06-analyzer/calls.md](../06-analyzer/calls.md) 的 label_sentiment 回填 x_posts。
