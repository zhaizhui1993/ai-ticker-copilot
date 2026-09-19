"""事件精排 prompt（docs/06-analyzer/prompts.md）。

要求给出可核对的匹配理由而非只给分值；similarity 仅在
"事件性质、传导机制、影响范围"三维度都匹配时才 ≥0.6。
"""

SYSTEM_PROMPT = """你是金融市场事件分析专家。给定一个当前事件和若干历史事件候选，逐个评估相似度。
规则：
1. similarity 取 0~1：仅在"事件性质、传导机制、影响范围"三个维度都匹配时才给 ≥0.6，
   单纯关键词重合不足以支撑高分；不确定时主动调低。
2. direction：该类历史事件对标的方向（-1 负 / 0 中性 / +1 正）。
3. magnitude：预期影响强度 0~1。
4. analogy_notes 必须写清"哪些维度相似、哪些维度不同"，给出可核对的理由，禁止只输出分数。
"""

USER_TEMPLATE = """当前事件：
{event}

候选历史事件（top-{n}）：
{candidates}

逐条输出 EventMatchResult（event_id / similarity / direction / magnitude / affected_tickers / analogy_notes）。
"""


def build_match_prompt(event, candidates: list) -> str:
    event_desc = (
        f"标题：{event.title}\n类别：{event.category.value}｜层级：{event.scope.value}\n"
        f"摘要：{event.summary}\n涉及标的：{'、'.join(event.tickers_mentioned) or '（未指明）'}"
    )
    cand_lines = []
    for i, c in enumerate(candidates, start=1):
        impacts = "、".join(
            f"{t.ticker}({'+' if t.direction > 0 else '-' if t.direction < 0 else '0'},"
            f"回撤{t.drawdown if t.drawdown is not None else '未回填'})"
            for t in c.tickers_affected
        ) or "（未指明）"
        cand_lines.append(
            f"[{i}] {c.event_id}（{c.start_date}，{c.category.value}）\n"
            f"    {c.name}\n    机制：{c.mechanism}\n    影响：{impacts}"
        )
    return USER_TEMPLATE.format(event=event_desc, n=len(candidates), candidates="\n".join(cand_lines))
