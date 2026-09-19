"""多轮对话：基于系统数据的研究助理（analyzer 层，唯一 LLM 出口之一）。

设计：
- 上下文打包（build_chat_context）：股票池 + 最近一次分析（DB 快照优先，
  缺 DB 时轻量现场组装）+ 体制层 + 近期事件 + 历史事件库摘要 + 降级状态
- 会话状态在客户端（前端持有历史，随请求带回），服务端截取最近 20 轮
- LLM 未配置时抛 LLMNotConfigured（端点转 503 + .env 指引）——对话无法
  规则降级，这是全系统唯一"LLM 必需"的功能（其余均有规则版降级）
"""

from analyzer import llm
from prompts.chat import SYSTEM_PROMPT, build_context_block

MAX_HISTORY = 20  # 服务端截断窗口（轮数上限，防 prompt 膨胀）


class LLMNotConfigured(Exception):
    """LLM_* 未配置：对话功能不可用（其余功能不受影响）。"""


def build_chat_context() -> dict:
    """组装对话上下文（各部分独立降级，缺什么标什么）。"""
    from config.loader import EMPTY_POOL_MESSAGE, load_stocks
    from events_lib.loader import load_seed_events

    degraded = []
    stocks = load_stocks()
    pool = ("；".join(f"{s.symbol}({s.segment.value}/{s.position.value}"
                      + (f"@{s.cost_basis}" if s.cost_basis else "") + ")"
                      for s in stocks) or EMPTY_POOL_MESSAGE)

    # 最近一次分析：DB 快照优先
    latest = "（今日尚无分析记录：可先在「分析」页运行，或直接基于下方基础数据提问）"
    try:
        from datetime import date, timedelta
        from storage import repository
        lines = []
        for stock in stocks:
            rows = repository.get_snapshots(stock.symbol, since=date.today() - timedelta(days=7))
            if rows:
                last = rows[-1]
                scores = ""
                if last.scores:
                    f = last.scores
                    scores = (f"｜四维 宏观{f.macro.score}/事件{f.event.score}"
                              f"/产业{f.industry.score}/公司{f.company.score}")
                lines.append(f"{stock.symbol}：信号 {last.signal}｜总分见分析{scores}")
        if lines:
            latest = "\n".join(lines)
    except Exception as exc:
        degraded.append(f"历史分析读取失败（DB）：{str(exc)[:80]}")

    # 体制层（有 TTL 缓存；限频/离线时降级）
    regime_desc = "（指数数据当前不可用）"
    try:
        from collectors import get_market
        from prompts.analysis import build_regime_desc
        r = get_market().get_index_regime()
        regime_desc = build_regime_desc(r) + f"；判定：{'破位（硬约束）' if r.regime_broken() else '完好'}"
    except Exception as exc:
        degraded.append(f"指数数据获取失败：{str(exc)[:80]}")

    # 近期事件（DB；缺 DB 时降级说明）
    events_desc = "（当前事件流不可用：DB 未配置）"
    try:
        from storage import repository
        events = repository.list_current_events(limit=8)
        events_desc = "\n".join(
            f"- [{e.occurred_date}][{e.scope.value}/{e.category.value}] {e.title}"
            f"（涉及 {'、'.join(e.tickers_mentioned) or '未指明'}）"
            for e in events) or "（暂无入库事件）"
    except Exception as exc:
        degraded.append(f"事件流读取失败（DB）：{str(exc)[:80]}")

    # 历史事件库摘要
    try:
        lib = load_seed_events()
        lib_desc = "\n".join(f"- {e.event_id}｜{e.name}｜{e.start_date}｜{e.category.value}" for e in lib)
        lib_count = len(lib)
    except Exception:
        lib_desc, lib_count = "（加载失败）", 0

    if not llm.llm_available():
        degraded.append("LLM 未配置（本对话功能依赖 LLM）")

    return {
        "pool": pool, "latest": latest, "regime": regime_desc,
        "events": events_desc, "lib": lib_desc, "lib_count": lib_count,
        "degraded": "；".join(degraded) or "无",
    }


def chat(messages: list[dict]) -> str:
    """多轮对话主入口。messages: [{role: 'user'|'assistant', content}]，返回回复文本。"""
    if not llm.llm_available():
        raise LLMNotConfigured(
            "对话功能需要配置 LLM：在 .env 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"
            "（任意 OpenAI 兼容模型）；未配置时分析/评分等其他功能不受影响"
        )

    history = [
        ("human" if m.get("role") == "user" else "ai", str(m.get("content", "")))
        for m in (messages or []) if m.get("content")
    ][-MAX_HISTORY:]
    if not history:
        raise ValueError("messages 为空")

    context = build_chat_context()
    system = SYSTEM_PROMPT + "\n\n== 系统数据上下文 ==\n" + build_context_block(context)
    reply = llm._chat().invoke([("system", system), *history])
    return reply.content
