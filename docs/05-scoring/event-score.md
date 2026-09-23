# 05-评分 ｜ 事件面（event_score.py）

> 模块：05 评分引擎 ｜ 成分：事件 scorer ｜ 权重 25%（= 历史类比 80% + X 情绪 20%） ｜ 实施阶段：P5
> 来源：原方案 §6.1②

```
对每个 ticker：
事件影响分 = Σ 命中事件 ( TickerImpact.direction × magnitude × similarity × 新鲜度衰减 )
新鲜度衰减 = 0.5 ^ (事件距今天数 / 半衰期)   # 半衰期按事件性质分类型（v1.2）
```

- **分类型半衰期（v1.2 / P1-1）**：默认（企业类/未分类）7 天；macro/monetary 30 天、regulation 45 天、crisis 60 天、tech 14 天——芯片管制这类季度级影响按 7 天衰减会系统性低估（2022-10 管制影响持续一年以上）。查表由 pipeline 传入 `category_by_event`（event_id → 历史事件 category）。
- 历史事件未直接列出该标的时一律乘 0.5 折扣（不做 segment 匹配，当前为简化口径）。
- **新鲜度加权在 pipeline 层完成**：每事件只取精排结果 **top-3**，匹配对携带 `(事件距今天数)` 一并传入（见 [10-module-contracts §10.2③](../10-module-contracts.md)）。
- X 情绪分：设计为"已打标帖子按 ticker 聚合，正帖占比线性映射 0-100"；**打标函数 label_sentiment 尚未实现**，pipeline 当前恒传 `x_sentiment=None` → **情绪腿剔除、类比权重显式重归一化 0.8→1.0**（v1.2 / P1-4，不再塞中性 50——保证分档校准不建立在残缺维度上；存储侧 `get_unlabeled_posts`/`mark_sentiment` 已就绪，见 [03-collectors/x-crawler.md](../03-collectors/x-crawler.md)）。
- 总分 = 50 + 类比分×40 + (情绪分-50)×0.2（两腿齐备）；情绪缺失时 = 50 + 类比分×50。均截断 [0,100]。
- 精排结果携带 `difference`（"这次哪里不一样"，v1.2 / P1-2 防过拟合推断），最强类比差异写入 rationale。
- **状态缺口调节（v1.3）**：匹配携带历史样本事件前状态（`pre_bias_ma200`，`events_lib/pre_state.py` 附加）且 pipeline 传入当前标的状态（`current_state`）时，按乖离缺口调节 magnitude——`factor = clamp(1 + (当前乖离 − 历史乖离)/100 × 0.5, 0.5, 1.5)`；任一侧状态缺失不调节。依据：2026-07 实证，回调深度主要由事件前 +40%~120% 乖离率决定——同样的管制打在"乖离 +80% 新高"与"已跌 30%"位置冲击不同。
- 输入来源：类比匹配结果由 [04-events/matcher.md](../04-events/matcher.md)（经 analyzer/llm.rerank_matches 精排）产出。
