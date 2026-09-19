"""事件事实层草稿生成（P4 版）。

规格：docs/04-events/initialization.md ①——完整流程为
"主题 → WebSearch 权威源检索 → LLM 结构化 → YAML 草稿 → 人工核对"。
当前为 P4 占位：生成待补全的草稿骨架（WebSearch + 真 LLM 抽取在 P6 接入，
届时只替换检索与抽取两步，骨架与核对流程不变）。

用法：
  uv run python scripts/build_events.py --list
  uv run python scripts/build_events.py --draft "美国对华芯片出口管制升级" \
      --category regulation --date 2026-10-17 [--keywords 出口管制,芯片] [--tickers NVDA,SMH]
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.events import EventCategory  # noqa: E402
from events_lib.loader import SEED_PATH, load_seed_events  # noqa: E402

CATEGORIES = [c.value for c in EventCategory]


def list_events() -> None:
    events = load_seed_events()
    print(f"种子事件库（{len(events)} 条，{SEED_PATH}）：")
    for e in events:
        quant = sum(1 for t in e.tickers_affected if t.drawdown is not None)
        print(f"  {e.event_id:<35} {e.start_date} {e.category.value:<11} "
              f"量化已回填 {quant}/{len(e.tickers_affected)} 标的")


def draft(topic: str, category: str, day: str, keywords: str, tickers: str) -> None:
    event_id = f"{day.replace('-', '-')}-{topic[:12]}"
    skeleton = {
        "event_id": event_id,
        "name": topic,
        "start_date": day,
        "category": category,
        "summary": "",   # ≤200 字背景（人工补全）
        "mechanism": "",  # 传导机制一句话（人工补全）
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
        "tickers_affected": [
            {"ticker": t.strip(), "direction": -1, "magnitude": 0.5}
            for t in tickers.split(",") if t.strip()
        ],
        "market": {},
        "tags": ["草稿待核对"],
    }
    print("# 事实层草稿（人工核对三条：公告日期 / 传导机制 / 受影响标的）")
    print("# 核对通过后追加到 seed_events.yaml；量化字段由 backfill_events.py 回填")
    print(yaml.dump([skeleton], allow_unicode=True, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="事件事实层草稿生成（P4 占位版）")
    parser.add_argument("--list", action="store_true", help="列出种子事件库")
    parser.add_argument("--draft", metavar="TOPIC", help="生成事实层草稿骨架")
    parser.add_argument("--category", choices=CATEGORIES, default="macro")
    parser.add_argument("--date", default="2026-09-19")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--tickers", default="")
    args = parser.parse_args()

    if args.list:
        list_events()
    elif args.draft:
        draft(args.draft, args.category, args.date, args.keywords, args.tickers)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
