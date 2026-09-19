"""历史事件联动层量化回填。

规格：docs/04-events/initialization.md ②
- 窗口：T0 前 30 交易日 ~ T0 后 180 交易日（算法见 events_lib/linkage.py）
- 默认只打印 YAML 片段供人工核对；--write 回写 seed_events.yaml（核对点：
  回撤数字与公开报道一致，如 DeepSeek 冲击 NVDA 单日约 −17%）

用法：
  uv run python scripts/backfill_events.py --event 2025-01-deepseek-shock
  uv run python scripts/backfill_events.py --event 2025-01-deepseek-shock --write
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import get_market  # noqa: E402
from config.settings import settings  # noqa: E402
from events_lib.linkage import compute_linkage, compute_market_metrics  # noqa: E402
from events_lib.loader import SEED_PATH, load_seed_events  # noqa: E402

SPY_SYMBOL = "SPY"
VIX_SYMBOL = "^VIX"


def backfill(event_id: str, write: bool = False) -> None:
    events = load_seed_events()
    event = next((e for e in events if e.event_id == event_id), None)
    if event is None:
        print(f"未找到事件：{event_id}（可用 --list 查看种子清单，见 build_events.py）")
        return

    t0 = event.start_date
    start = t0 - timedelta(days=90)   # 日历日换算，保证 T0 前有 ≥30 个交易日
    end = t0 + timedelta(days=400)    # 覆盖 T0 后 180 个交易日

    market = get_market()
    print(f"# 事件：{event.name}（{event_id}，T0={t0}）MOCK_MODE={settings.mock_mode}")
    print("# 核对点：回撤数字与公开报道一致；不一致说明 T0 或窗口设定有误，调整后重跑")

    try:
        spy = market.get_daily_bars_between(SPY_SYMBOL, start, end)
        vix = market.get_daily_bars_between(VIX_SYMBOL, start, end)
        metrics = compute_market_metrics(spy, vix, t0)
    except Exception as exc:
        metrics = {"sp500_1w": None, "sp500_1m": None, "vix_peak": None}
        print(f"# [降级] 市场指标获取失败：{exc}")

    print(yaml.dump({
        "market": {
            "sp500_1w": metrics["sp500_1w"],
            "sp500_1m": metrics["sp500_1m"],
            "vix_peak": metrics["vix_peak"],
        }
    }, allow_unicode=True, sort_keys=False).strip())

    for impact in event.tickers_affected:
        try:
            bars = market.get_daily_bars_between(impact.ticker, start, end)
            result = compute_linkage(bars, t0)
        except Exception as exc:
            print(f"# {impact.ticker}: 获取失败（降级跳过）：{exc}")
            continue
        if result is None:
            print(f"# {impact.ticker}: 窗口内无数据，跳过")
            continue
        print(yaml.dump({
            "ticker": impact.ticker,
            "drawdown": result["drawdown"],
            "drawdown_days": result["drawdown_days"],
            "recovery_days": result["recovery_days"],
        }, allow_unicode=True, sort_keys=False).strip())

    if write:
        _write_back(event_id, event, metrics)


def _write_back(event_id: str, event, metrics: dict) -> None:
    """人工核对后回写（会重排 YAML 格式；核对以打印片段为准）。"""
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    for item in data.get("events", []):
        if item.get("event_id") != event_id:
            continue
        item.setdefault("market", {}).update({
            k: v for k, v in metrics.items() if v is not None
        })
        for impact in item.get("tickers_affected", []):
            # 量化回填在人工核对后由脚本使用者在 YAML 中确认（保守：只回写市场指标，
            # 个股回撤片段打印后人工誊写，防止算法异常直接污染种子库）
            pass
    SEED_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"\n# 已回写市场指标到 {SEED_PATH}（个股回撤请人工核对片段后誊写）")


def main() -> None:
    parser = argparse.ArgumentParser(description="历史事件量化回填")
    parser.add_argument("--event", required=True, help="event_id，如 2025-01-deepseek-shock")
    parser.add_argument("--write", action="store_true", help="核对后回写（默认只打印）")
    args = parser.parse_args()
    backfill(args.event, args.write)


if __name__ == "__main__":
    main()
