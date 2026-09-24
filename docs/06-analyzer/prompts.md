# 06-LLM ｜ prompt 设计要点

> **v1.4 修订优先**：当前契约见 [AI 产业链研究方案修订](../11-ai-investment-revision.md)；下文保留早期设计背景，冲突处以修订为准。

> 模块：06 LLM 研判层 ｜ 成分：prompt 设计 ｜ 对应代码：prompts/analysis.py、prompts/event_match.py、prompts/chat.py ｜ 实施阶段：P6（对话为增补）
> 来源：原方案 §9.3

## 综合研判（prompts/analysis.py）

- 角色："资深美股分析师，擅长将宏观、事件、基本面结合历史案例进行研判"。
- 输入：每只股票的四维分数与 rationale、各维 indicators 原始值、历史类比结论、X 博主观点摘要、当前持仓状态（holding/watchlist）。
- 输出规则：① 信号四选一；② 理由必须引用具体分数或类比数据；③ **偏离分档必须说明原因，且点名支撑偏离的具体输入字段名与数值**（防"综合考虑"式无出处偏离，v1.2）；④ 风险列表至少一条；⑤ 结尾必须附固定免责声明"本报告仅供个人研究参考，不构成投资建议"。
- 约束：不输出投资金额、不做个股推荐表述（"建议买入"→"信号为加仓倾向"），保持辅助定位；**仓位上限系数 position_cap 为体制层风险参数，LLM 照抄不得调高**（v1.2）。
- 体制层分级约束生效时（[05-scoring/engine.md](../05-scoring/engine.md)）：prompt 附加环境警示，信号上限=watch_add（观望偏加仓·小仓）、仓位系数 0.3，LLM 上偏须额外援引事件类比依据。

## 事件精排（prompts/event_match.py）

- 输入当前事件 + top-5 候选（summary/mechanism/量化影响/**事件前状态**），输出 similarity/direction/magnitude/notes/**difference**；
- 要求给出**可核对的匹配理由**而非只给分值（相似度无校准，防自欺）；**difference 必填且覆盖两层**（v1.3）：① 事件差异（利率/产业阶段/量级/传导路径）② 状态差异（当前标的位置 vs 历史样本乖离/回撤深度是否可比）；
- **magnitude 状态调节**（v1.3）：当前标的明显比历史样本更拥挤（乖离更高/更贴前高）→ 上调；更超卖 → 下调；候选为 fizzled 对照（预期冲击未兑现）时显式标注参与判断；
- 供给 [04-events/matcher.md](../04-events/matcher.md) 的精排环节使用（经 analyzer/llm.rerank_matches 调用）。

## 研究助理对话（prompts/chat.py，实施期增补）

与一次性报告 prompt 的定位不同：报告是"系统给结论"，对话是"用户带上下文追问"，因此规则重心从输出纪律转向**研究纪律**：

- SYSTEM_PROMPT 七条规则：只依据系统提供的数据上下文作答；未采集的数据直说没有（不编造）；不迎合用户持仓立场；情景推演必须标注假设；保持研究纪律；中文简洁；LLM 降级信息如实转述。
- CONTEXT_TEMPLATE 六块：股票池 / 最新信号与四维分 / 指数体制层 / 当前事件（含个股价格反应五指标）/ 历史事件库摘要 / 降级说明——由 `analyzer/chat.build_chat_context()` 组装，各块独立降级（某块数据缺失标注后继续），`build_context_block(ctx)` 渲染为上下文文本。
- 会话历史由客户端持有，服务端每次截最近 20 轮（`MAX_HISTORY=20`）拼接。
