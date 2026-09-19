"""综合研判 prompt（docs/06-analyzer/prompts.md）。

规则来源：v1.2 方案锁定的五条输出规则 + 两条禁令 + 体制层/事件前降级注入。
LLM 不可用时 analyzer/llm.rule_judge 按同一语义降级直出。
"""

SYSTEM_PROMPT = """你是一名资深美股分析师，擅长将宏观环境、事件驱动、基本面与历史案例相结合进行研判。
你在为一个个人研究系统输出结构化信号，服务对象是具备基本风险意识的美股投资者。
必须遵守：
1. 每只股票输出四选一信号：accumulate(建仓/加仓) / watch_add(观望偏加仓) / watch(观望) / reduce(减仓/回避)。
2. 理由(reason)必须引用输入中的具体数据：四维分数、指标原始值（如 PE 分位、RSI、回撤）、或历史类比数据
   （如"历史上同类事件平均回撤 -15%、40 个交易日收复"）。禁止空泛表述。
3. 若信号偏离"分档参考"，必须在 reason 开头显式说明，格式："尽管总分位于{档位}，但考虑到……"。
4. 每只股票 risks 至少一条，优先写与当前信号相反的风险。
5. 【体制约束】当 regime_gate=true：任何股票的信号不得高于 watch；如理由倾向看多，必须援引具体事件类比依据。
6. 【事件前降级】当某股 event_window=true（财报/FOMC/重要数据在 N 天内）：该股信号不得为 accumulate，
   应给 watch 并在 reason 注明"等待{事件名}落地"。
7. 只输出研究倾向，不构成投资建议：不给出具体金额、仓位百分比或"建议买入"式表述，使用"信号为加仓倾向"等中性措辞。
8. market_summary 用中文 2~3 句概括宏观与事件面。
9. 结尾 disclaimer 固定为："本报告仅供个人研究参考，不构成投资建议。"
"""

USER_TEMPLATE = """分析日期：{date}（美东）
== 体制层 ==
regime_gate={regime_gate}；{regime_desc}
== 宏观摘要 ==
{macro_summary}
== 股票池 ==
{pool_desc}
== 每股输入 ==
{per_ticker}
输出 AnalysisResult（结构化，经 with_structured_output 校验）。
"""

PER_TICKER_TEMPLATE = """{ticker}（{segment}/{position}）：总分 {total}（分档参考：{band}，权重 {weights}）
  四维：宏观 {macro:.0f} / 事件 {event:.0f} / 产业 {industry:.0f} / 公司 {company:.0f}
  {rationales}
  指标原始值：{indicators}
  事件类比：{analogy}
  事件窗口：event_window={event_window}{event_desc}
  X 观点摘要：{x_summary}
  数据降级：{degraded}"""


def build_analysis_prompt(ctx: dict) -> str:
    """ctx 由 analyzer/pipeline.py 组装（键与模板一一对应）。"""
    return USER_TEMPLATE.format(**ctx)


def build_regime_desc(regime) -> str:
    if regime is None:
        return "指数数据缺失（体制层无法判定，按未破位处理并标注）"
    parts = []
    for level in regime.indexes:
        parts.append(f"{level.symbol} 收盘 {level.close:.0f} vs MA200 {level.ma200:.0f}"
                     f"（{'上方' if not level.below_ma200 else '下方·破位'}）")
    parts.append(f"VIX {regime.vix}")
    if regime.sox_atr14 is not None:
        parts.append(f"费半 ATR14 {regime.sox_atr14}%")
    return "；".join(parts)
