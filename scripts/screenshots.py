"""Take real screenshots of the running Streamlit app (headless Chromium via Playwright).

    streamlit run streamlit_app.py --server.port 8599 --server.headless true &
    python scripts/screenshots.py http://localhost:8599
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8599"
OUT = Path(__file__).resolve().parents[1] / "docs"
TABS = [("What travellers share", "dashboard_overview.png"), ("Title explorer", "dashboard_title_explorer.png"),
        ("Top travellers", "dashboard_top_travellers.png"), ("Pipeline & data quality", "dashboard_pipeline_quality.png")]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("text=Which non-English Netflix titles travel?", timeout=120_000)
    for tab, name in TABS:
        page.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(4000)  # let plotly finish drawing
        page.screenshot(path=str(OUT / name), full_page=True)
        print("saved", OUT / name)
    browser.close()
