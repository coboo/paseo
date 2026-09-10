"""README 用页面截图：Playwright 对本地 Streamlit 应用逐页截图，落 docs/screenshots/。

用法（先起本地应用）：
    uv run streamlit run app/paseo.py --server.port 8599 --server.headless true
    uv run python scripts/take_screenshots.py

等待策略：networkidle 后先等"Running"状态消失（实时抓取可能耗时 10s+），
再停 2s 让图表/表格渲染完。截图为全页（估值页较长）。
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8599"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"

# (url_path, 文件名)；faber 为默认首页，挂在根路径（直接访问 /faber 会触发 404 toast）
PAGES = [
    ("", "faber_strategy.png"),
    ("market", "market_monitor.png"),
    ("valuation", "valuation_dashboard.png"),
    ("backtest", "gem_backtest.png"),
    ("data", "data_browser.png"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        for url_path, filename in PAGES:
            page.goto(f"{BASE}/{url_path}")
            page.wait_for_load_state("networkidle")
            # Streamlit 运行中会有 "Running" 状态文本；等它消失（数据抓取完成）
            try:
                page.wait_for_selector("text=Running", state="detached", timeout=60_000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            page.screenshot(path=OUT / filename, full_page=True)
            print(f"OK {filename}")
        browser.close()
    print(f"\n截图目录：{OUT}")


if __name__ == "__main__":
    main()
