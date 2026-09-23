"""事件前状态回填 CLI（v1.3）：直接操作 seed_events.yaml 正本，无需 MySQL。

用法：
  uv run python scripts/backfill_pre_state.py                     # 干跑：报告缺口（离线可用）
  uv run python scripts/backfill_pre_state.py --write             # 回填 pre-state + market 指标
  uv run python scripts/backfill_pre_state.py --write-all         # 连 drawdown/recovery 一起回填
  uv run python scripts/backfill_pre_state.py --event 2025-01-deepseek-shock --write
约定：
  - 保守语义：已有值不覆盖（人工核对过的数字优先于算法值）
  - 写入前自动备份 seed_events.yaml.bak-<时间戳>，回写后自校验，git diff 核对后提交
  - Yahoo 限频常见：--sleep 每请求间隔秒（默认 2）；被限频等待后重跑即可（幂等）
  - mock 模式拒绝执行（假行情会污染种子库）
  - 启动时 upsert_seed_events() 自动把 yaml 同步进 MySQL，无需单独入库
"""

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from events_lib.loader import SEED_PATH, load_seed_events  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--event", action="append", help="限定 event_id（可多次）；默认全部")
    parser.add_argument("--write", action="store_true", help="回填 pre-state + market（默认干跑）")
    parser.add_argument("--write-all", action="store_true",
                        help="在 --write 基础上连 drawdown/recovery 一起回填")
    parser.add_argument("--sleep", type=float, default=2.0, help="每请求间隔秒（防限频），默认 2")
    args = parser.parse_args()

    all_events = load_seed_events()          # 回写永远用全量（防 --event 过滤丢事件）
    targets = all_events
    if args.event:
        wanted = set(args.event)
        targets = [e for e in all_events if e.event_id in wanted]
        missing = wanted - {e.event_id for e in targets}
        if missing:
            print(f"未找到事件：{sorted(missing)}")
            return 1

    # 干跑缺口报告（离线可用）
    gap_pre = sum(1 for e in targets for t in e.tickers_affected
                  if t.pre_drawdown_52w is None and t.pre_bias_ma200 is None)
    gap_market = sum(1 for e in targets if not any(
        v is not None for v in (e.market.sp500_1w, e.market.sp500_1m, e.market.vix_peak)))
    gap_link = sum(1 for e in targets for t in e.tickers_affected if t.drawdown is None)
    print(f"事件 {len(targets)} 条｜pre-state 缺失标的 {gap_pre}｜market 缺失 {gap_market}"
          f"｜drawdown 缺失 {gap_link}")
    if not (args.write or args.write_all):
        print("（干跑：加 --write 回填 pre-state + market；--write-all 连 drawdown/recovery）")
        return 0

    from config.settings import settings
    if settings.mock_mode:
        print("MOCK_MODE=true：拒绝回填（mock 行情会污染种子库）")
        return 1

    from collectors import get_market
    from events_lib.pre_state import backfill_events
    report = backfill_events(
        targets, get_market(),
        fill_market=True, fill_linkage=args.write_all,
        sleep=(lambda: time.sleep(args.sleep)) if args.sleep > 0 else None,
    )
    print(f"回填完成：pre-state {report['pre_state_filled']} 条标的、market {report['market_filled']} 条事件"
          + (f"、linkage {report['linkage_filled']} 条标的" if args.write_all else ""))
    if report["failed"]:
        print(f"失败/跳过 {len(report['failed'])} 项（限频可稍后重跑，幂等）：")
        for event_id, sym, err in report["failed"][:20]:
            print(f"  {event_id} {sym}: {err}")

    # 备份 + 回写（会重排 YAML 格式，与 backfill_events.py 同约定；核对以 git diff 为准）
    # mode="json"：枚举/日期序列化为标量——默认 python 模式会把 Enum 写成
    # !!python/object 标签，safe_load 无法读回（回写后自校验会拦住）
    backup = SEED_PATH.with_name(f"seed_events.yaml.bak-{datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(SEED_PATH, backup)
    data = {"events": [e.model_dump(mode="json", exclude_none=True) for e in all_events]}
    SEED_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    load_seed_events()                       # 回写后自校验（防格式损坏）
    print(f"已回写 {SEED_PATH}（备份：{backup.name}）；git diff 核对后提交")
    return 0


if __name__ == "__main__":
    sys.exit(main())
