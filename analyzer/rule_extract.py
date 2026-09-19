"""规则版事件抽取（P3 交付，现为 LLM 不可用时的降级路径）。

关键词规则猜测 scope/category；明确标注"未经 LLM 校验"。
P6 起 analyzer/llm.extract_events 优先走 LLM 批量单次调用。
"""

from datetime import date

from domain.events import CurrentEvent, EventCategory, EventScope, RawArticle

# 关键词 → (scope, category) 猜测表；顺序即优先级（越靠前越具体）
_RULES: list[tuple[list[str], EventScope, EventCategory]] = [
    (["出口管制", "制裁", "禁售", "entity list", "export control"], EventScope.GEOPOLITICAL, EventCategory.REGULATION),
    (["加息", "降息", "利率", "美联储", "fed", "fomc", "点阵图"], EventScope.MACRO_POLICY, EventCategory.MONETARY),
    (["cpi", "通胀", "非农", "gdp", "失业率", "国债", "收益率", "财政"], EventScope.MACRO_POLICY, EventCategory.MACRO),
    (["财报", "earnings", "指引", "guidance", "营收", "订单", "ceo", "管理层", "回购", "收购"],
     EventScope.COMPANY, EventCategory.TECH),
    (["ai", "芯片", "半导体", "gpu", "算力", "capex", "数据中心", "光模块", "代工", "制程"],
     EventScope.INDUSTRY, EventCategory.TECH),
]


def _guess_scope_category(text: str) -> tuple[EventScope | None, EventCategory | None]:
    lowered = text.lower()
    for keywords, scope, category in _RULES:
        if any(k in lowered for k in keywords):
            return scope, category
    return None, None


def extract_events(
    articles: list[RawArticle],
    pool_tickers: list[str],
    seq_start: int = 1,
    today: date | None = None,
) -> list[CurrentEvent]:
    today = today or date.today()
    events: list[CurrentEvent] = []
    seq = seq_start
    for article in articles:
        text = f"{article.title} {article.summary}"
        scope, category = _guess_scope_category(text)
        if scope is None:
            continue  # 规则版宁缺勿滥；LLM 版会做更宽的判断
        mentioned = [t for t in pool_tickers if t.lower() in text.lower()]
        events.append(CurrentEvent(
            event_id=f"{today:%Y-%m-%d}-{seq:03d}",
            title=article.title[:200],
            occurred_date=today,
            scope=scope,
            category=category or EventCategory.TECH,
            summary=article.summary[:300] or article.title[:300],
            keywords=[],
            tickers_mentioned=mentioned,
            source=article.source,
            raw_url=article.raw_url,
        ))
        seq += 1
    return events
