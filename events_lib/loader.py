"""seed_events.yaml → pydantic 校验 → upsert MySQL events 表（source='seed'）。

规格：docs/04-events/seed-events.md（入库约定）
启动时（FastAPI lifespan）调用 upsert_seed_events()；用户事件 source='user'、
自动沉淀草稿 source='auto'，代码升级不清掉（幂等 upsert 只更新 payload）。
"""

from pathlib import Path

import yaml

from domain.events import HistoricalEvent
from storage import repository

SEED_PATH = Path(__file__).resolve().parent / "seed_events.yaml"


class SeedEventError(Exception):
    """种子事件库文件非法（启动即报错）"""


def load_seed_events(path: Path | None = None) -> list[HistoricalEvent]:
    """读取并校验种子事件（schema 见 domain/events.py）。"""
    data = yaml.safe_load((path or SEED_PATH).read_text(encoding="utf-8")) or {}
    raw_events = data.get("events") or []
    if not raw_events:
        raise SeedEventError(f"种子事件库为空：{path or SEED_PATH}")

    events: list[HistoricalEvent] = []
    errors: list[str] = []
    for i, item in enumerate(raw_events, start=1):
        try:
            events.append(HistoricalEvent.model_validate(item))
        except Exception as exc:  # pydantic ValidationError
            errors.append(f"第 {i} 条（{item.get('event_id', '?')}）校验失败：{exc}")

    if errors:
        raise SeedEventError("seed_events.yaml 存在非法条目：\n" + "\n".join(f"- {e}" for e in errors))

    ids = [e.event_id for e in events]
    if len(ids) != len(set(ids)):
        raise SeedEventError(f"seed_events.yaml 存在重复 event_id：{sorted(ids)}")
    return events


def upsert_seed_events(path: Path | None = None) -> int:
    """启动时幂等入库，返回条数。"""
    count = 0
    for event in load_seed_events(path):
        repository.put_event(event, source="seed")
        count += 1
    return count
