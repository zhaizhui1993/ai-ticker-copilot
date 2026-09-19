# 06 ｜ LLM 研判层（analyzer/ + prompts/）

> **职责**：LLM 供应商接入（OpenAI 兼容、供应商无关）与结构化输出封装；事件抽取、类比精排、情绪打标、综合研判四类调用的边界划分与 prompt 设计；run_analysis() 端到端编排。
> **对应代码**：analyzer/（llm.py / pipeline.py）、prompts/（event_match.py / analysis.py） ｜ **依赖模块**：04（类比精排输入）、05（四维分数） ｜ **实施阶段**：P6
> **内容来源**：原方案 §9；v1.2 起 LLM 供应商无关化

## 成分文档

| 文档 | 对应代码 | 内容 |
|---|---|---|
| [provider.md](provider.md) | analyzer/llm.py | LLM 接入要点（供应商无关）与成本控制 |
| [calls.md](calls.md) | analyzer/llm.py | 四类 LLM 调用的边界 |
| [prompts.md](prompts.md) | prompts/ | 综合研判 prompt 设计要点 |

## pipeline 编排（analyzer/pipeline.py）

`run_analysis()` 按"取数 → 事件匹配（[04-events](../04-events/README.md)）→ 四维评分（[05-scoring](../05-scoring/README.md)）→ LLM 综合研判 → 落库（[07-storage](../07-storage/README.md)）"顺序编排；全局 asyncio.Lock 串行化，同日重复分析直接返回已存快照（运行时时序见 [10-module-contracts.md §10.4 场景 B](../10-module-contracts.md)）。
