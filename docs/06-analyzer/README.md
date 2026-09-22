# 06 ｜ LLM 研判层（analyzer/ + prompts/）

> **职责**：LLM 供应商接入（OpenAI 兼容、供应商无关）与结构化输出封装；事件抽取、类比精排、综合研判、研究助理对话四类调用的边界划分与 prompt 设计（情绪打标为规划未实现）；run_analysis() 端到端编排。
> **对应代码**：analyzer/（llm.py / pipeline.py / chat.py / rule_extract.py / schemas.py）、prompts/（event_match.py / analysis.py / chat.py） ｜ **依赖模块**：04（类比精排输入）、05（四维分数） ｜ **实施阶段**：P6（对话为实施期增补）
> **内容来源**：原方案 §9；v1.2 起 LLM 供应商无关化

## 成分文档

| 文档 | 对应代码 | 内容 |
|---|---|---|
| [provider.md](provider.md) | analyzer/llm.py | LLM 接入要点（供应商无关）、成本控制与降级 |
| [calls.md](calls.md) | analyzer/llm.py + analyzer/chat.py | 四类 LLM 调用（+规划的打标）的边界 |
| [prompts.md](prompts.md) | prompts/（analysis.py / event_match.py / chat.py） | 综合研判与对话 prompt 设计要点 |

## pipeline 编排（analyzer/pipeline.py）

`run_analysis()`（同步）按"取数 → 事件匹配（[04-events](../04-events/README.md)）→ 四维评分（[05-scoring](../05-scoring/README.md)）→ LLM 综合研判 → 落库（[07-storage](../07-storage/README.md)）"顺序编排，返回 `{result, outputs, regime, db_saved, cached}`；**同日幂等**（当日快照已存在且未 refresh 直接回放，不重复调 LLM；mock 模式跳过幂等与落库；DB 不可用时跳过落库照常出结果）。并发防护在 Web 层（threading.Lock，撞车 409），pipeline 自身无锁（运行时时序见 [10-module-contracts.md §10.4 场景 B](../10-module-contracts.md)）。

## 研究助理对话（analyzer/chat.py，实施期增补）

报告产出后的多轮追问入口：`build_chat_context()` 打包股票池/最新信号/体制层/当前事件（含价格反应）/事件库摘要六块上下文（各块独立降级），`chat(messages)` 供 Web `POST /api/chat` 调用（服务端截最近 20 轮历史，会话状态在客户端）。**这是全系统唯一强依赖 LLM 的功能**——未配置 key 时抛 `LLMNotConfigured`，Web 层转 503，不做规则降级。prompt 见 [prompts.md](prompts.md)。
