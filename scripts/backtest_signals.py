"""信号评测 CLI（P0-3 演进）：薄封装，逻辑在 analyzer/evaluation.py。

模式：
  默认            信号前瞻研究（含全池等权同期基准对照列）
  --deviation     LLM 偏离质量追踪（偏离组 vs 遵守组的前瞻超额 + 体制封顶违背）
  --calibration   校准曲线（置信度 vs 实际胜率；--llm 仅看 LLM 产物）
  --regime [SYM]  MA200 体制层 whipsaw 统计（默认 ^SOX）
  --full          全量月度评估并追加存档到 data/eval/monthly-YYYY-MM.md（调度器同款）

用法：
  uv run python scripts/backtest_signals.py
  uv run python scripts/backtest_signals.py --deviation --calibration
  uv run python scripts/backtest_signals.py --regime ^SOX --years 5
  uv run python scripts/backtest_signals.py --full            # 存档
  MOCK_MODE=true uv run python scripts/backtest_signals.py    # 冒烟（数字无意义）
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyzer import evaluation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", help="逗号分隔，默认快照表全部 ticker")
    parser.add_argument("--since", default="2000-01-01", help="起始日期 yyyy-mm-dd")
    parser.add_argument("--regime", nargs="?", const="^SOX", default=None, metavar="SYMBOL",
                        help="体制层 whipsaw 统计（默认 ^SOX）")
    parser.add_argument("--years", type=float, default=6.0, help="--regime 回看年数，默认 6")
    parser.add_argument("--deviation", action="store_true", help="LLM 偏离质量追踪")
    parser.add_argument("--calibration", action="store_true", help="校准曲线")
    parser.add_argument("--llm", action="store_true", help="--calibration 仅看 LLM 产物")
    parser.add_argument("--full", action="store_true", help="全量月度评估并追加存档")
    parser.add_argument("--out", default=None, help="--full 存档目录（默认 data/eval）")
    args = parser.parse_args()

    from collectors import get_market
    from config.settings import settings

    market = get_market()
    if settings.mock_mode:
        print("[backtest] MOCK_MODE：以下数字来自 mock 行情，仅链路冒烟，无统计意义。")

    if args.regime:
        print(evaluation.regime_whipsaw(market, args.regime, args.years))
        return

    if args.full:
        text = evaluation.build_full_report(market, since=date.fromisoformat(args.since))
        print(text)
        path = evaluation.archive_report(text, out_dir=args.out)
        print(f"\n[backtest] 月度评估已追加存档：{path}（只追加不覆盖）")
        return

    try:
        records = evaluation.load_signal_records(
            [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None,
            since=date.fromisoformat(args.since),
        )
    except Exception as exc:
        print(f"[backtest] 快照读取失败（需真实模式 + MySQL）：{exc}")
        raise SystemExit(1)
    if not records:
        print("[backtest] 无历史信号可评测（先在真实模式跑若干天分析）")
        return

    missed = evaluation.attach_forward_returns(records, market)
    if missed:
        print(f"[backtest] {missed} 条信号未匹配到行情（日期越界或行情缺失），已剔除")
    usable = [r for r in records if any(r.get(f"fwd_{h}d") is not None
                                        for h in evaluation.HORIZONS)]
    if not usable:
        print("[backtest] 有效信号为 0（行情不足以计算任何前瞻窗口）")
        return

    if args.deviation:
        print(evaluation.report_deviation(usable))
    if args.calibration:
        print(evaluation.report_calibration(usable, "llm" if args.llm else "all"))
    if not (args.deviation or args.calibration):
        print(evaluation.report_signals(usable))


if __name__ == "__main__":
    main()
