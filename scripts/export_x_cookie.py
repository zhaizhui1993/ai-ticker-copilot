"""导出 X 登录态：有头浏览器手动登录 → storage_state 落盘。

用法：uv run python scripts/export_x_cookie.py
（首次需先 uv run playwright install chromium；登录含二次验证由人工完成）
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.x_crawler import state_path  # noqa: E402


def main() -> int:
    from playwright.sync_api import sync_playwright

    target = state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"登录态将保存到：{target}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 有头：人工登录
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://x.com/login", timeout=30000)
        print("请在浏览器中完成登录（含二次验证）。最长等待 180 秒…")

        deadline = time.time() + 180
        logged_in = False
        while time.time() < deadline:
            try:
                cookies = {c["name"] for c in context.cookies()}
                if "auth_token" in cookies:
                    logged_in = True
                    break
            except Exception:
                pass
            time.sleep(3)

        if not logged_in:
            print("超时未检测到登录态（cookie auth_token）。重跑本脚本再试。")
            browser.close()
            return 1

        context.storage_state(path=str(target))
        print(f"登录态已保存：{target}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
