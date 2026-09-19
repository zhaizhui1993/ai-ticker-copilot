# 04-事件库 ｜ 两级类比匹配（matcher.py）

> 模块：04 历史事件库 ｜ 成分：匹配引擎 ｜ 对应代码：events_lib/matcher.py ｜ 实施阶段：P4
> 来源：原方案 §6.2

```
当日新闻 ──► 规则过滤 ──► LLM 批量抽取 CurrentEvent（一次调用一批）
                              │
                              ▼
                   ① 硬检索：对事件库全量打分排序（库小，O(N) 即可）
                      category 相同 +10；keywords 交集每词 +5；
                      tickers 交集每 +8；月份邻近（同月±1）+3
                      取 top-5
                              │
                              ▼
                   ② LLM 精排：当前事件 + top-5 候选（summary/mechanism/量化影响）
                      输出 EventMatch{event_id, similarity 0~1, direction,
                      magnitude, affected_tickers, analogy_notes}
                              │
                              ▼
                   ③ 合成类比结论：取 similarity≥0.6 的事件聚合
                      "历史上此类事件对 NVDA 的平均影响：
                       最大回撤 x%，达底 y 天，恢复 z 天"
                      → 输入事件面打分与最终 LLM prompt
```

## 约定

- **不用 embedding 的理由**：事件库几十条规模，硬检索 + LLM 精排性价比最高，省 embedding API 成本与一个依赖；库超 ~200 条再升级向量检索（演进路径见 [09-delivery/evolution.md](../09-delivery/evolution.md)）。
- **降级路径**：LLM 不可用时直接用硬检索 top-2 输出类比，标注"低置信类比（未过 LLM 校验）"，`confidence='low'`。
- **样本量保护（v1.1）**：同类事件 n<3 时输出"样本不足，仅供参考"而非平均值。
- **正向事件必须入种子库**（2023-05 AI 行情启动），否则类比永远偏空——这是种子库设计的硬约束。
- 接口签名（hard_retrieve / llm_rerank / synthesize_analogy）见 [10-module-contracts.md §10.2②](../10-module-contracts.md)；LLM 精排 prompt 见 [06-analyzer/prompts.md](../06-analyzer/prompts.md)。
