# 06-LLM ｜ 综合研判 prompt 设计要点

> 模块：06 LLM 研判层 ｜ 成分：prompt 设计 ｜ 对应代码：prompts/analysis.py、prompts/event_match.py ｜ 实施阶段：P6
> 来源：原方案 §9.3

## 综合研判（prompts/analysis.py）

- 角色："资深美股分析师，擅长将宏观、事件、基本面结合历史案例进行研判"。
- 输入：每只股票的四维分数与 rationale、各维 indicators 原始值、历史类比结论、X 博主观点摘要、当前持仓状态（holding/watchlist）。
- 输出规则：① 信号四选一；② 理由必须引用具体分数或类比数据；③ **偏离分档必须说明原因**；④ 风险列表至少一条；⑤ 结尾必须附固定免责声明"本报告仅供个人研究参考，不构成投资建议"。
- 约束：不输出投资金额、不做个股推荐表述（"建议买入"→"信号为加仓倾向"），保持辅助定位。
- 体制层硬约束生效时（[05-scoring/engine.md](../05-scoring/engine.md)）：prompt 附加环境警示，LLM 上偏须额外援引事件类比依据。

## 事件精排（prompts/event_match.py）

- 输入当前事件 + top-5 候选（summary/mechanism/量化影响），输出 similarity/direction/magnitude/notes；
- 要求给出**可核对的匹配理由**而非只给分值（相似度无校准，防自欺）；
- 供给 [04-events/matcher.md](../04-events/matcher.md) 的精排环节使用。
