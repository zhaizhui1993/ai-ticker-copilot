"""价格回调挖掘 CLI：从指数/个股日线挖回调波段，产出事件草稿骨架。

用法：
  uv run python scripts/mine_events.py --symbol ^IXIC --since 2024-01-01
  uv run python scripts/mine_events.py --csv data/ixic.csv --since 2024-01-01 --min-dd 5
（行情通道恢复后跑真实模式；--csv 支持离线 Date,Close 两列文件）

输出：每段回调的峰/谷/幅度/达底/恢复 + HistoricalEvent YAML 骨架，
事件名称与机制留待人工/LLM 归因后入库（docs/04-events 数据纪律）。
"""

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.stock import DailyBar  # noqa: E402
from events_lib.mine import detect_pullbacks  # noqa: E402


def load_bars_csv(path: Path) -> list[DailyBar]:
    bars = []
    with path.open() as handle:
        for row in csv.DictReader(handle):
            try:
                bars.append(DailyBar(
                    date=datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                    open=float(row.get("Open") or row["Close"]),
                    high=float(row.get("High") or row["Close"]),
                    low=float(row.get("Low") or row["Close"]),
                    close=float(row["Close"]),
                ))
            except (KeyError, ValueError):
                continue
    return bars


def load_bars_yahoo(symbol: str, since: date) -> list[DailyBar]:
    from collectors import get_market
    end = date.today()
    return get_market().get_daily_bars_between(symbol, since - __import__("datetime").timedelta(days=30), end)


def main() -> int:
    parser = argparse.ArgumentParser(description="回调波段挖掘器")
    parser.add_argument("--symbol", default="^IXIC", help="默认纳指综合；支持任意 yfinance 符号")
    parser.add_argument("--csv", help="离线 CSV（Date,Close[,Open,High,Low]），行情通道不可用时用")
    parser.add_argument("--since", default="2024-01-01")
    parser.add_argument("--min-dd", type=float, default=5.0, help="回调判定阈值 %%（默认 5）")
    parser.add_argument("--rebound", type=float, default=3.0, help="波段结束反弹阈值 %%（默认 3）")
    args = parser.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d").date()
    if args.csv:
        bars = [b for b in load_bars_csv(Path(args.csv)) if b.date >= since]
        source = f"csv:{args.csv}"
    else:
        try:
            bars = load_bars_yahoo(args.symbol, since)
            source = f"yfinance:{args.symbol}"
        except Exception as exc:
            print(f"行情获取失败（{exc}）\n提示：可改用 --csv 离线数据，或等通道恢复")
            return 1

    episodes = detect_pullbacks(bars, min_dd_pct=args.min_dd, rebound_pct=args.rebound)
    print(f"# {source} | {since} → {bars[-1].date if bars else '-'} | 阈值 {args.min_dd}% | 检出 {len(episodes)} 段回调\n")
    for ep in episodes:
        print(f"{ep['peak_date']} 高 {ep['peak']} → {ep['trough_date']} 低 {ep['trough']}"
              f"  回撤 {ep['drawdown_pct']}%  达底 {ep['days_down']} 个交易日"
              f"  恢复 {ep['recovery_days'] if ep['recovery_days'] is not None else '未收复'}")
        print(f"""  - event_id: mine-{ep['trough_date']}
    name: ""            # ← 人工/LLM 归因
    start_date: {ep['peak_date']}
    end_date: {ep['trough_date']}
    category: tech      # ← 按驱动改（macro/monetary/tech…）
    summary: ""
    mechanism: ""
    keywords: []
    tickers_affected:
      - {{ticker: {args.symbol}, direction: -1, magnitude: 0.6,
         drawdown: {ep['drawdown_pct']}, drawdown_days: {ep['days_down']},
         recovery_days: {ep['recovery_days']}}}
    market: {{}}
    tags: [挖掘器产出, 待归因, 待核对]
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
