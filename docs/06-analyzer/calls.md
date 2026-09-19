# 06-LLM ｜ 四类调用的边界

> 模块：06 LLM 研判层 ｜ 成分：调用边界 ｜ 对应代码：analyzer/llm.py ｜ 实施阶段：P6
> 来源：原方案 §9.2

| 调用 | 时机 | 输入 | 输出 |
|---|---|---|---|
| 事件抽取 | 刷新 news 时 | 当日新闻标题+摘要一批 | CurrentEvent 列表（结构化） |
| 事件类比精排 | 每个当前事件 | 当前事件 + 硬检索 top-5 | similarity/direction/magnitude/affected_tickers/analogy_notes |
| 情绪打标 | 全量分析时 | 未打标帖子一批 | 每条 sentiment/tickers/note |
| 综合研判 | 每次分析 | 四维分 + 类比结论 + X 观点摘要 + 股票池 | signals 列表 + market_summary |

**边界约定**：LLM 层是**全系统唯一的 LLM 出口**（04 的精排也经此处函数）——换供应商只改 .env 三项（`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`），代码零改动；输出必为 pydantic 模型（`with_structured_output(method="function_calling")`，见 [provider.md](provider.md)）；签名见 [10-module-contracts.md §10.2④](../10-module-contracts.md)。
