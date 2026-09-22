# 06-LLM ｜ 调用的边界

> 模块：06 LLM 研判层 ｜ 成分：调用边界 ｜ 对应代码：analyzer/llm.py、analyzer/chat.py ｜ 实施阶段：P6（对话为增补）
> 来源：原方案 §9.2

| 调用 | 时机 | 输入 | 输出 |
|---|---|---|---|
| 事件抽取 extract_events | 事件管道轮询时 | 预过滤后的新闻标题+摘要一批 + 股票池 | CurrentEvent 列表（结构化；无 key 降级 rule_extract 规则版） |
| 事件类比精排 rerank_matches | 每次分析、每个当前事件 | 当前事件 + 硬检索 top-5 | EventMatchResult 列表（similarity/direction/magnitude/affected_tickers/analogy_notes）；失败返回 None 走规则版 |
| 综合研判 judge / rule_judge | 每次分析 | 四维分 + 事件匹配上下文 + 股票池 | signals 列表 + market_summary（LLM 可偏离分数但须说明理由；无 key 用 rule_judge 规则版） |
| 研究助理对话 chat（实施期增补） | 用户在对话页追问 | 系统数据上下文 + 最近 20 轮历史 | 纯文本回复（**不走结构化输出**；无 key 直接 503，不降级） |
| 情绪打标 label_sentiment（规划未实现） | 全量分析时（设计） | 未打标帖子一批 | 每条 sentiment/tickers/note（存储侧接口已就绪） |

**边界约定**：所有 LLM 请求经 analyzer/llm.py 的 `_chat()` 统一发起（对话调用也经此出口，发起方在 chat.py）——换供应商只改 .env 三项（`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`），代码零改动；**结构化调用**输出必为 pydantic 模型（`with_structured_output(method="function_calling")`，见 [provider.md](provider.md)），对话调用返回纯文本为例外；签名见 [10-module-contracts.md §10.2④](../10-module-contracts.md)。

**注意**：综合研判的"X 观点摘要"当前为占位文案（"X 数据缺失"），待情绪打标管线接入后替换。
