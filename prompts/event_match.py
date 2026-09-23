"""事件精排 prompt（docs/06-analyzer/prompts.md）。

要求给出可核对的匹配理由而非只给分值；similarity 仅在
"事件性质、传导机制、影响范围"三维度都匹配时才 ≥0.6。
v1.3：difference 升级为"事件差异 + 状态差异"双维度——历史回撤是
f(事件强度, 标的状态)，当前标的与历史样本的位置（乖离率/回撤深度）
不可比时，magnitude 必须相应调节，防止无条件照搬历史数字。
"""

SYSTEM_PROMPT = """你是金融市场事件分析专家。给定一个当前事件和若干历史事件候选，逐个评估相似度。
规则：
1. similarity 取 0~1：仅在"事件性质、传导机制、影响范围"三个维度都匹配时才给 ≥0.6，
   单纯关键词重合不足以支撑高分；不确定时主动调低。
2. direction：该类历史事件对标的方向（-1 负 / 0 中性 / +1 正）。
3. magnitude：预期影响强度 0~1。**状态调节**：候选标注了历史事件前状态（乖离率/距52周高）时，
   与当前事件标注的标的现状态比较——当前明显更拥挤（乖离更高/更接近新高），magnitude 上调；
   明明更超卖/离前高更远，magnitude 下调；状态未标注则不调节。
4. analogy_notes 必须写清"哪些维度相似、哪些维度不同"，给出可核对的理由，禁止只输出分数。
5. difference 必填，覆盖两层（无数据层写"未标注"）：
   ① 事件差异：利率/政策环境、产业阶段、量级规模、传导路径至少一处；
   ② 状态差异：当前标的位置 vs 历史样本位置（乖离率/回撤深度/前期涨幅）是否可比。
   禁止留空、禁止套话。
"""

USER_TEMPLATE = """当前事件：
{event}

候选历史事件（top-{n}）：
{candidates}

逐条输出 EventMatchResult（event_id / similarity / direction / magnitude / affected_tickers / analogy_notes / difference）。
"""


def build_match_prompt(event, candidates: list) -> str:
    event_desc = (
        f"标题：{event.title}\n类别：{event.category.value}｜层级：{event.scope.value}\n"
        f"摘要：{event.summary}\n涉及标的：{'、'.join(event.tickers_mentioned) or '（未指明）'}"
    )
    reactions = _current_state_desc(event)
    if reactions:
        event_desc += f"\n标的现状态（事件时点）：\n{reactions}"

    cand_lines = []
    for i, c in enumerate(candidates, start=1):
        impacts = "、".join(
            f"{t.ticker}({'+' if t.direction > 0 else '-' if t.direction < 0 else '0'},"
            f"回撤{t.drawdown if t.drawdown is not None else '未回填'},"
            f"前状态:乖离{t.pre_bias_ma200 if t.pre_bias_ma200 is not None else '未回填'}%"
            f"/距52周高{t.pre_drawdown_52w if t.pre_drawdown_52w is not None else '未回填'}%)"
            for t in c.tickers_affected
        ) or "（未指明）"
        fizzled_mark = "｜**fizzled 对照（预期冲击未兑现）**" if c.fizzled else ""
        cand_lines.append(
            f"[{i}] {c.event_id}（{c.start_date}，{c.category.value}{fizzled_mark}）\n"
            f"    {c.name}\n    机制：{c.mechanism}\n    影响：{impacts}"
        )
    return USER_TEMPLATE.format(event=event_desc, n=len(candidates), candidates="\n".join(cand_lines))


def _current_state_desc(event) -> str:
    """当前事件标注的标的现状态（入库时富化的价格反应），供状态可比性判断。"""
    lines = []
    for r in event.price_reactions[:5]:
        parts = []
        if r.drawdown_52w is not None:
            parts.append(f"距52周高 {r.drawdown_52w}%")
        if r.prior_20d_pct is not None:
            parts.append(f"前20日 {r.prior_20d_pct:+.0f}%")
        if r.event_day_pct is not None:
            parts.append(f"事件日 {r.event_day_pct:+.1f}%")
        if parts:
            lines.append(f"  {r.ticker}：{'｜'.join(parts)}")
    return "\n".join(lines)
