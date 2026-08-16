import time
from playwright.sync_api import sync_playwright

def test_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # 1. Test 1280x800 with Windows default 1.25 deviceScaleFactor
        context1 = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1.25)
        page = context1.new_page()
        page.goto("http://127.0.0.1:8000/")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Check scenario select
        scenarios = page.eval_on_selector_all("#scenario option", "els => els.map(e => e.value)")
        print("Scenarios in dropdown:", scenarios)
        assert len(scenarios) >= 4

        # Start simulation so snapshot & map are received
        page.click("#btn-start")
        time.sleep(2)

        # Verify grid coordinate bounds on canvas
        bounds = page.evaluate("""() => {
            if (!state.world || !state.map) return null;
            const pts = state.map.nodes.map(n => worldToScreen(n.x, n.y));
            const xs = pts.map(p => p.x);
            const ys = pts.map(p => p.y);
            const shell = document.getElementById('map-shell').getBoundingClientRect();
            return {
                minX: Math.min(...xs),
                maxX: Math.max(...xs),
                minY: Math.min(...ys),
                maxY: Math.max(...ys),
                shellW: shell.width,
                shellH: shell.height,
            };
        }""")
        print("1280x800 Grid projection bounds:", bounds)
        assert bounds is not None
        assert bounds["minX"] >= 20, f"Grid clipped on left: {bounds['minX']}"
        assert bounds["maxX"] <= bounds["shellW"] - 20, f"Grid clipped on right: {bounds['maxX']} vs {bounds['shellW']}"
        assert bounds["minY"] >= 20, f"Grid clipped on top: {bounds['minY']}"
        assert bounds["maxY"] <= bounds["shellH"] - 20, f"Grid clipped on bottom: {bounds['maxY']} vs {bounds['shellH']}"

        # 2. Test 1920x1080 resolution
        context2 = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.5)
        page2 = context2.new_page()
        page2.goto("http://127.0.0.1:8000/")
        page2.wait_for_load_state("networkidle")
        time.sleep(1)
        page2.click("#btn-start")
        time.sleep(2)

        bounds2 = page2.evaluate("""() => {
            if (!state.world || !state.map) return null;
            const pts = state.map.nodes.map(n => worldToScreen(n.x, n.y));
            const xs = pts.map(p => p.x);
            const ys = pts.map(p => p.y);
            const shell = document.getElementById('map-shell').getBoundingClientRect();
            return {
                minX: Math.min(...xs),
                maxX: Math.max(...xs),
                minY: Math.min(...ys),
                maxY: Math.max(...ys),
                shellW: shell.width,
                shellH: shell.height,
            };
        }""")
        print("1920x1080 Grid projection bounds:", bounds2)
        assert bounds2 is not None
        assert bounds2["minX"] >= 20, f"Grid clipped on left: {bounds2['minX']}"
        assert bounds2["maxX"] <= bounds2["shellW"] - 20, f"Grid clipped on right: {bounds2['maxX']} vs {bounds2['shellW']}"
        assert bounds2["minY"] >= 20, f"Grid clipped on top: {bounds2['minY']}"
        assert bounds2["maxY"] <= bounds2["shellH"] - 20, f"Grid clipped on bottom: {bounds2['maxY']} vs {bounds2['shellH']}"

        # 3. Check clock and stats
        clock_text = page.inner_text("#clock")
        print("Clock after start:", clock_text)
        assert "t " in clock_text and "s" in clock_text

        # 4. Test Station and Hospital Tooltips
        tooltips = page.evaluate("""() => {
            const st = state.map.stations[0];
            const h = state.map.hospitals[0];
            const stPos = worldToScreen(...state.nodes.get(st.node));
            const hPos = worldToScreen(...state.nodes.get(h.node));
            const stHit = hitTest(stPos.x, stPos.y);
            const hHit = hitTest(hPos.x, hPos.y);
            return { stHit, hHit };
        }""")
        print("Station tooltip hit test:", tooltips["stHit"])
        print("Hospital tooltip hit test:", tooltips["hHit"])
        assert "BASE DEPOT" in tooltips["stHit"]["title"] or "STATION" in tooltips["stHit"]["title"]
        assert "HOSPITAL" in tooltips["hHit"]["title"]

        # 5. Test Legend Toggle and localStorage persistence
        assert page.is_visible("#legend-content") is True
        # Click hide
        page.click("#btn-toggle-legend")
        time.sleep(0.3)
        assert page.is_visible("#legend-content") is False
        assert page.inner_text("#legend-toggle-label") == "SHOW"
        stored_val = page.evaluate("() => localStorage.getItem('ems_legend_visible')")
        assert stored_val == "false"

        # Reload and check persistence
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        assert page.is_visible("#legend-content") is False
        assert page.inner_text("#legend-toggle-label") == "SHOW"

        # Click show
        page.click("#btn-toggle-legend")
        time.sleep(0.3)
        assert page.is_visible("#legend-content") is True
        assert page.inner_text("#legend-toggle-label") == "HIDE"
        stored_val = page.evaluate("() => localStorage.getItem('ems_legend_visible')")
        assert stored_val == "true"

        # 6. Take screenshots for confirmation
        page.screenshot(path="web_screenshot_1280.png")
        page2.screenshot(path="web_screenshot_1920.png")
        print("Screenshots captured successfully!")

        browser.close()
        print("ALL UI VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_ui()
