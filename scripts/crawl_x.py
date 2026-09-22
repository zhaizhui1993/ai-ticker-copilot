"""手动抓 X 并打印结果（P7 验收入口；X_MODE 路由 api/crawl/off）。

用法：uv run python scripts/crawl_x.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.x_source import crawl_and_store  # noqa: E402
from config.loader import load_influencers, load_stocks  # noqa: E402
from config.settings import settings  # noqa: E402


def main() -> int:
    if settings.x_mode == "off":
        print("X_MODE=off：X 采集已关闭（.env 修改后重试）")
        return 0
    influencers = load_influencers()
    stocks = load_stocks()
    if not influencers:
        print("博主列表为空：请编辑 config_files/influencers.yaml 填入要跟进的 X 博主")
        return 1
    tickers = [s.symbol for s in stocks]
    mode_desc = ("twitterapi.io 接口" if settings.x_mode == "api" else "Playwright 爬虫")
    print(f"开始抓取（{mode_desc}，{len(influencers)} 位博主；股票池 {len(tickers)} 只）…")

    try:
        outcome = crawl_and_store(influencers, tickers)
    except Exception as exc:
        print(f"抓取失败：{exc}")
        if settings.x_mode == "api":
            print("提示：检查 .env 的 X_API_KEY（twitterapi.io 控制台获取）与 X_API_BASE")
        else:
            print("提示：先运行 scripts/export_x_cookie.py 导出登录态，"
                  "并确认 uv run playwright install chromium 已执行；"
                  "或改用 X_MODE=api + X_API_KEY（第三方接口，免登录态）")
        return 1

    if outcome.get("throttled"):
        print(f"节流跳过（今日已抓）：{'、'.join(outcome['throttled'])}")
    if outcome.get("skipped"):
        for item in outcome["skipped"]:
            print(f"单博主失败（跳过）：{item}")
    if outcome.get("error"):
        print(f"[终止] {outcome['error']}")
        return 1

    for post in outcome["posts"]:
        time_desc = post.posted_at.strftime("%m-%d %H:%M") if post.posted_at else "?"
        reply = f" →@{post.reply_to}" if post.reply_to else ""
        print(f"  @{post.author}{reply} [{time_desc}] {post.content[:60]!r}")
    print(f"抓到 {len(outcome['posts'])} 条，入库新增 {outcome['stored']} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
