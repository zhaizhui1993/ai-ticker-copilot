"""CLI：数据刷新与验证（P3 验收入口）。

用法：
  uv run python scripts/refresh_data.py --scope market   # 行情 + 指标 + 指数体制层
  uv run python scripts/refresh_data.py --scope macro    # FRED 宏观（需 key）
  uv run python scripts/refresh_data.py --scope news     # 事件管道单轮（需 MySQL）
  uv run python scripts/refresh_data.py --scope all
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import get_macro, get_market, get_news  # noqa: E402
from config.loader import EMPTY_POOL_MESSAGE, load_stocks  # noqa: E402
from config.settings import settings  # noqa: E402
from domain import technicals  # noqa: E402


def refresh_market() -> None:
    print("=" * 62)
    print("指数体制层（docs/05-scoring/layered-technicals.md）")
    print("=" * 62)
    market = get_market()
    try:
        regime = market.get_index_regime()
    except Exception as exc:
        print(f"  [降级] 行情获取失败：{exc}")
        print("  应对（docs/09-delivery/risks.md 风险#1）：稍后重试（雅虎限频通常分钟级恢复）；"
              "或 MOCK_MODE=true 验证链路。")
        return
    for level in regime.indexes:
        status = "上方 ✓" if not level.below_ma200 else "下方 ✗（破位）"
        print(f"  {level.symbol:<6} 收盘 {level.close:>10.2f}  MA200 {level.ma200:>10.2f}  {status}")
    print(f"  VIX {regime.vix}  |  ^SOX ATR14 {regime.sox_atr14}%")
    broken = regime.regime_broken()
    print(f"  → 体制层判定：{'破位（分级约束：档位≤中性偏多、仓位上限系数 0.3）' if broken else '完好（允许做多）'}")

    print()
    stocks = load_stocks()
    if not stocks:
        print(EMPTY_POOL_MESSAGE)
        return
    print(f"股票池行情与指标（{len(stocks)} 只）")
    header = f"  {'ticker':<7}{'close':>9}{'chg%':>7}{'MA20':>9}{'MA50':>9}{'RSI14':>7}{'ATR%':>6}{'乖离200':>8}{'52w回撤':>9}{'量比':>6}"
    print(header)
    for stock in stocks:
        bars = market.get_daily_bars(stock.symbol, 300)
        last = bars[-1]
        prev = bars[-2]

        def f(v, width, precision=2):
            return f"{v:>{width}.{precision}f}" if isinstance(v, (int, float)) else f"{'-':>{width}}"

        print(f"  {stock.symbol:<7}"
              f"{f(last.close, 9)}"
              f"{f((last.close / prev.close - 1) * 100, 7)}"
              f"{f(technicals.sma(bars, 20), 9)}"
              f"{f(technicals.sma(bars, 50), 9)}"
              f"{f(technicals.rsi(bars), 7, 0)}"
              f"{f(technicals.atr_pct(bars), 6, 1)}"
              f"{f(technicals.bias_vs_ma200_pct(bars), 8, 1)}"
              f"{f(technicals.drawdown_from_high_pct(bars), 9, 1)}"
              f"{f(technicals.volume_ratio(bars), 6, 1)}")


def refresh_macro() -> None:
    print("=" * 62)
    print(f"FRED 宏观（MOCK_MODE={settings.mock_mode}）")
    print("=" * 62)
    try:
        macro = get_macro()
        series = macro.get_all()
        for series_id, point in series.items():
            if point is None:
                print(f"  {series_id:<15} 数据缺失（降级标注）")
            else:
                direction = ""
                if point.prev_value is not None:
                    arrow = "↑" if point.value > point.prev_value else ("↓" if point.value < point.prev_value else "→")
                    direction = f"  {arrow} 前值 {point.prev_value}"
                print(f"  {series_id:<15} {point.value:>10.2f}  @{point.as_of}{direction}")
    except Exception as exc:
        print(f"  宏观数据缺失（降级中性并标注）：{exc}")


def refresh_news() -> None:
    print("=" * 62)
    print("事件管道单轮（抓取→去重→预过滤→抽取→入库）")
    print("=" * 62)
    stocks = load_stocks()
    tickers = [s.symbol for s in stocks]
    if not tickers:
        print(f"{EMPTY_POOL_MESSAGE}（管道仍将运行，仅按主题词抓取）")
    summary = get_news().poll_once(tickers)
    print(f"  抓取 {summary['fetched']} 篇 → 增量 {summary['new']} 篇 → "
          f"预过滤后 {summary['filtered']} 篇 → 入库 {summary['stored']} 条事件")
    if summary.get("db_error"):
        print(f"  [降级] 入库失败（DB 不可用）：{summary['db_error']}")
    for event in summary.get("events", []):
        print(f"  + [{event.scope.value}] {event.title[:44]} ({event.source})")


def main() -> None:
    parser = argparse.ArgumentParser(description="数据刷新与验证")
    parser.add_argument("--scope", choices=["market", "macro", "news", "all"], default="market")
    args = parser.parse_args()

    if args.scope in ("market", "all"):
        refresh_market()
        print()
    if args.scope in ("macro", "all"):
        refresh_macro()
        print()
    if args.scope in ("news", "all"):
        refresh_news()


if __name__ == "__main__":
    main()
