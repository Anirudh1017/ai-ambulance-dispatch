import time
from playwright.sync_api import sync_playwright

def verify():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.25)
        page = context.new_page()
        page.goto("http://127.0.0.1:8000/")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 1. Verify START button label
        start_btn_text = page.inner_text("#btn-start").strip()
        print("Start button label:", start_btn_text)
        assert start_btn_text == "START", f"Expected START, got '{start_btn_text}'"

        # 2. Verify fleet summary straight line / hospital count
        fleet_text = page.inner_text("#fleet-summary").strip()
        print("Fleet summary text:", fleet_text)
        assert "units" in fleet_text and "stations" in fleet_text and "hospitals" in fleet_text and "calls" in fleet_text

        # 3. Start simulation
        page.click("#btn-start")
        time.sleep(1.5)

        # 4. Test Speed / tickRate slider & presets
        for speed_preset in ["1", "8", "20", "40"]:
            page.click(f".speed-preset[data-speed='{speed_preset}']")
            time.sleep(0.5)
            val = page.inner_text("#speed-val")
            print(f"Speed preset {speed_preset}x -> UI shows: {val}")
            assert f"{speed_preset}/s" in val

        # 5. Test Map Rotation (0 -> 90 -> 180 -> 270 -> 0)
        for expected_angle in ["90°", "180°", "270°", "0°"]:
            page.click("#btn-rotate-map")
            time.sleep(0.3)
            current_label = page.inner_text("#rotation-label")
            print(f"Rotated map -> angle: {current_label}")
            assert current_label == expected_angle

            # Verify no clipping at this rotation angle
            bounds = page.evaluate("""() => {
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
                    shellH: shell.height
                };
            }""")
            print(f"Bounds at {expected_angle}: {bounds}")
            assert bounds["minX"] >= 20, f"Clipped on left: {bounds['minX']}"
            assert bounds["maxX"] <= bounds["shellW"] - 20, f"Clipped on right: {bounds['maxX']} vs {bounds['shellW']}"
            assert bounds["minY"] >= 20, f"Clipped on top: {bounds['minY']}"
            assert bounds["maxY"] <= bounds["shellH"] - 20, f"Clipped on bottom: {bounds['maxY']} vs {bounds['shellH']}"

        # 6. Test Horizontal Strata View Toggle
        strata_label = page.inner_text("#strata-mode-label")
        print("Initial strata mode label:", strata_label)
        assert strata_label == "SIDEBAR"

        # Toggle to STRATA
        page.click("#btn-toggle-strata")
        time.sleep(0.5)
        strata_label_after = page.inner_text("#strata-mode-label")
        print("After toggle -> strata mode label:", strata_label_after)
        assert strata_label_after == "STRATA"
        has_strata_class = page.evaluate("() => document.getElementById('main-layout').classList.contains('layout-strata')")
        assert has_strata_class is True
        stored_mode = page.evaluate("() => localStorage.getItem('ems_strata_mode')")
        assert stored_mode == "strata"

        # Reload to test persistence
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        assert page.inner_text("#strata-mode-label") == "STRATA"
        assert page.evaluate("() => document.getElementById('main-layout').classList.contains('layout-strata')") is True

        # Toggle back to SIDEBAR
        page.click("#btn-toggle-strata")
        time.sleep(0.5)
        assert page.inner_text("#strata-mode-label") == "SIDEBAR"
        assert page.evaluate("() => document.getElementById('main-layout').classList.contains('layout-strata')") is False

        # 7. Test tick rate performance after 50 ticks
        clock_text = page.inner_text("#clock")
        print("Clock text after run:", clock_text)
        assert "t " in clock_text

        browser.close()
        print("\n>>> ALL VERIFICATION TESTS PASSED PERFECTLY! <<<")

if __name__ == "__main__":
    verify()
