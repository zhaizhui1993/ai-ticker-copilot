"""CLI 端到端分析（P6 交付）。

用法：
  uv run python scripts/analyze.py --ticker NVDA          # 用现有数据
  uv run python scripts/analyze.py --ticker NVDA --refresh  # 强制刷新并分析
  MOCK_MODE=true uv run python scripts/analyze.py          # 无网无 key 全链路验证
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyzer import llm  # noqa: E402
from analyzer.pipeline import EmptyPoolError, run_analysis  # noqa: E402
from config.settings import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端分析")
    parser.add_argument("--ticker", action="append", help="限定标的（可多次）；默认全股票池")
    parser.add_argument("--refresh", action="store_true", help="跳过当日快照幂等，强制重跑")
    args = parser.parse_args()

    print(f"ai-ticker-copilot 端到端分析（MOCK_MODE={settings.mock_mode}，"
          f"LLM={'已配置' if llm.llm_available() else '未配置→规则版降级'}）")
    print("=" * 64)

    try:
        outcome = run_analysis(refresh=args.refresh, tickers=args.ticker)
    except EmptyPoolError as exc:
        print(str(exc))
        return 1

    if outcome.get("cached"):
        print("（当日快照已存在：返回已存结果，未重复调 LLM）")

    regime = outcome.get("regime")
    if regime is not None:
        broken = regime.regime_broken()
        print(f"体制层：{'破位（硬约束生效）' if broken else '完好（允许做多）'}  "
              f"VIX {regime.vix}  费半 ATR {regime.sox_atr14}%")
    else:
        print("体制层：数据缺失（按未破位处理并标注）")
    print()

    for ticker, output in outcome.get("outputs", {}).items():
        gate = " ｜硬约束生效" if output.regime_gate_applied else ""
        print(f"  {ticker:<6} 总分 {output.weighted_total:>5.1f}  分档 {output.band}{gate}")

    print()
    result = outcome["result"]
    print(f"市场综述：{result.market_summary}")
    print("-" * 64)
    for signal in result.signals:
        print(f"【{signal.ticker}】{signal.action.value}  置信度 {signal.confidence:.0%}")
        print(f"  理由：{signal.reason}")
        for risk in signal.risks:
            print(f"  风险：{risk}")
        if signal.price_target_hint:
            print(f"  提示：{signal.price_target_hint}")
        print()
    print(result.disclaimer)
    print(f"落库：{'已写入' if outcome.get('db_saved') else '跳过（DB 不可用，结果照常返回）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
