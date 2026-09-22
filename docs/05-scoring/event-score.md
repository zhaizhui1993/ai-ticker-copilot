# 05-评分 ｜ 事件面（event_score.py）

> 模块：05 评分引擎 ｜ 成分：事件 scorer ｜ 权重 25%（= 历史类比 80% + X 情绪 20%） ｜ 实施阶段：P5
> 来源：原方案 §6.1②

```
对每个 ticker：
事件影响分 = Σ 命中事件 ( TickerImpact.direction × magnitude × similarity × 新鲜度衰减 )
新鲜度衰减 = 0.5 ^ (事件距今天数 / 7)      # 半衰期 7 天
```

- 历史事件未直接列出该标的时一律乘 0.5 折扣（不做 segment 匹配，当前为简化口径）。
- **新鲜度加权在 pipeline 层完成**：每事件只取精排结果 **top-3**，匹配对携带 `(事件距今天数)` 一并传入（见 [10-module-contracts §10.2③](../10-module-contracts.md)）。
- X 情绪分：设计为"已打标帖子按 ticker 聚合，正帖占比线性映射 0-100"；**打标函数 label_sentiment 尚未实现**，pipeline 当前恒传 `x_sentiment=None` → 情绪腿计 50（中性）并标注"X 数据缺失"（存储侧 `get_unlabeled_posts`/`mark_sentiment` 已就绪，见 [03-collectors/x-crawler.md](../03-collectors/x-crawler.md)）。
- 总分 = 50 + 类比分×40 + (情绪分-50)×0.2，截断 [0,100]。
- 输入来源：类比匹配结果由 [04-events/matcher.md](../04-events/matcher.md)（经 analyzer/llm.rerank_matches 精排）产出。
