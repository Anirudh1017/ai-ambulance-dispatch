import time
from playwright.sync_api import sync_playwright

def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        
        # Capture any browser console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        
        print("Navigating to http://127.0.0.1:8000/ ...")
        page.goto("http://127.0.0.1:8000/")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # ------------------------------------------------------------------ #
        # Check Initial Status & Markup
        # ------------------------------------------------------------------ #
        status_text = page.inner_text("#status-text").strip()
        print("1. Initial status text:", status_text)
        assert status_text == "IDLE", f"Expected IDLE initial status, got {status_text}"

        # ------------------------------------------------------------------ #
        # Check Item 4: Analyze View Text Collision
        # ------------------------------------------------------------------ #
        print("\nChecking Item 4: Response Time & Rolling Latency text collision...", flush=True)
        page.click("#viewAnalyzeBtn")
        time.sleep(0.5)
        
        spark_heading_box = page.locator("#sparkHeading").bounding_box()
        chip_box = page.locator("text='Rolling latency'").bounding_box()
        print("Spark heading bounding box:", spark_heading_box, flush=True)
        print("Rolling latency chip bounding box:", chip_box, flush=True)
        
        # Verify both are visible and no overlapping bounds
        assert spark_heading_box is not None and chip_box is not None
        # They should not overlap on x if on the same line, or should have proper spacing
        overlap_x = max(0, min(spark_heading_box["x"] + spark_heading_box["width"], chip_box["x"] + chip_box["width"]) - max(spark_heading_box["x"], chip_box["x"]))
        overlap_y = max(0, min(spark_heading_box["y"] + spark_heading_box["height"], chip_box["y"] + chip_box["height"]) - max(spark_heading_box["y"], chip_box["y"]))
        is_overlapping = (overlap_x > 0 and overlap_y > 0)
        assert not is_overlapping, f"Collision detected between heading and chip: overlap_x={overlap_x}, overlap_y={overlap_y}"
        print("[OK] Response Time and Rolling Latency headers have clean layout with zero collision!", flush=True)

        # ------------------------------------------------------------------ #
        # Check Item 5: Benchmark Comparison Populated
        # ------------------------------------------------------------------ #
        print("\nChecking Item 5: Benchmark comparison population...", flush=True)
        time.sleep(1.0)
        bench_html = page.inner_html("#benchmark-box")
        delta_html = page.inner_html("#wow-bench-delta")
        print("Benchmark box has table:", "<table" in bench_html or "SMART vs NAIVE" in delta_html or "<table" in delta_html, flush=True)
        assert "<table" in bench_html or "<table" in delta_html or "SMART vs NAIVE" in delta_html, "Benchmark table did not populate!"
        print("[OK] Benchmark SMART vs NAIVE data populated cleanly!", flush=True)

        # Switch back to Command view
        page.click("#viewCommandBtn")
        time.sleep(0.5)

        # ------------------------------------------------------------------ #
        # Check Item 7: Pause & Resume Behavior
        # ------------------------------------------------------------------ #
        print("\nChecking Item 7: Pause / Resume functionality...", flush=True)
        # Start simulation
        page.click("#btn-start")
        time.sleep(1.0)
        
        status_running = page.inner_text("#status-text").strip()
        print("Status after start:", status_running, flush=True)
        assert status_running == "RUNNING"
        
        pause_btn = page.locator("#btn-pause")
        assert pause_btn.inner_text().strip() == "PAUSE"
        
        # Record tick
        tick_before_pause = page.evaluate("() => state.snap ? state.snap.tick : 0")
        time.sleep(0.5)
        
        # Click PAUSE
        print("Clicking PAUSE button...", flush=True)
        pause_btn.click()
        time.sleep(0.6)
        
        # Verify button flipped to RESUME
        resume_text = pause_btn.inner_text().strip()
        print("Pause button text after click:", resume_text, flush=True)
        assert resume_text == "RESUME", f"Expected RESUME, got {resume_text}"
        status_paused = page.inner_text("#status-text").strip()
        print("Status after pause:", status_paused, flush=True)
        assert status_paused == "PAUSED"
        
        # Check that ticks are not advancing while paused
        paused_tick = page.evaluate("() => state.snap ? state.snap.tick : 0")
        time.sleep(0.8)
        paused_tick_later = page.evaluate("() => state.snap ? state.snap.tick : 0")
        print(f"Ticks during pause: {paused_tick} -> {paused_tick_later}", flush=True)
        assert paused_tick == paused_tick_later, "Simulation continued ticking while paused!"
        
        # Click RESUME
        print("Clicking RESUME button...", flush=True)
        pause_btn.click()
        time.sleep(0.8)
        
        resumed_text = pause_btn.inner_text().strip()
        print("Pause button text after resume:", resumed_text, flush=True)
        assert resumed_text == "PAUSE", f"Expected PAUSE, got {resumed_text}"
        status_resumed = page.inner_text("#status-text").strip()
        print("Status after resume:", status_resumed, flush=True)
        assert status_resumed == "RUNNING"
        
        resumed_tick = page.evaluate("() => state.snap ? state.snap.tick : 0")
        print(f"Tick advanced after resume: {paused_tick} -> {resumed_tick}", flush=True)
        assert resumed_tick > paused_tick, "Simulation failed to advance ticks after resume!"
        print("[OK] Pause/Resume flipped state and resumed execution cleanly!", flush=True)

        # ------------------------------------------------------------------ #
        # Check Item 1: Diagonal Lines & Excessive Clutter Check
        # ------------------------------------------------------------------ #
        print("\nChecking Item 1: Road and route geometries (no diagonal cut-through lines)...", flush=True)
        # Check ambulance route points: ensure all routes follow graph edges only
        route_check = page.evaluate("""() => {
            if (!state.snap || !state.snap.ambulances) return { ok: true, reason: 'no ambulances' };
            const nodes = state.nodes;
            for (const a of state.snap.ambulances) {
                if (a.route && a.route.length >= 2) {
                    for (let i = 0; i < a.route.length - 1; i++) {
                        const u = nodes.get(a.route[i]);
                        const v = nodes.get(a.route[i+1]);
                        if (u && v) {
                            // On a grid network, valid road steps are Manhattan (dx == 0 or dy == 0)
                            const dx = Math.abs(u[0] - v[0]);
                            const dy = Math.abs(u[1] - v[1]);
                            if (dx > 0.01 && dy > 0.01) {
                                return { ok: false, u: a.route[i], v: a.route[i+1], dx, dy };
                            }
                        }
                    }
                }
            }
            return { ok: true };
        }""")
        print("Ambulance route geometry check:", route_check, flush=True)
        assert route_check["ok"], f"Found diagonal route edge: {route_check}"
        print("[OK] All ambulance routes are colinear to grid edges with zero diagonal line crossings!", flush=True)

        # Speed up simulation to let it finish
        print("\nSetting speed to 100x to reach simulation finish...", flush=True)
        page.evaluate("() => { if (typeof send === 'function') send({ action: 'set_speed', tps: 100 }); }")
        
        # Wait for run to finish (up to 40s)
        for i in range(80):
            time.sleep(0.5)
            is_finished = page.evaluate("() => !!(state.run && state.run.finished)")
            if is_finished:
                print(f"Simulation completed at wait tick {i}!", flush=True)
                break
        
        print("Simulation finished state:", page.evaluate("() => state.run ? state.run.finished : false"), flush=True)
        time.sleep(1.0)

        # ------------------------------------------------------------------ #
        # Check Item 2: Hospital Load Tracking Upon Completion
        # ------------------------------------------------------------------ #
        print("\nChecking Item 2: Hospital load tracking upon completion...", flush=True)
        hosp_heading = page.inner_text("#hospitalHeading")
        hosp_loads_html = page.inner_html("#wow-hospital-loads")
        print("Hospital heading text:", hosp_heading, flush=True)
        assert "completed" in hosp_heading.lower(), f"Hospital heading does not show completed: {hosp_heading}"
        assert "0/6" not in hosp_heading, f"Hospital heading still shows 0/6 completed: {hosp_heading}"
        assert "served" in hosp_loads_html or "completed" in hosp_loads_html, "Hospital load bars do not show served/completed count!"
        print("[OK] Hospital load tracks completed calls correctly (shows completed / served, not 0/6)!", flush=True)

        # ------------------------------------------------------------------ #
        # Check Item 3: Live Incident Tracker Final State
        # ------------------------------------------------------------------ #
        print("\nChecking Item 3: Live Incident Tracker final state...", flush=True)
        ticker_html = page.inner_text("#wow-ticker")
        print("Ticker text content:", ticker_html.replace("\n", " | "), flush=True)
        assert "awaiting telemetry" not in ticker_html.lower(), "Live Incident Tracker is stuck on 'awaiting telemetry' after run!"
        assert "run complete" in ticker_html.lower() or "calls cleared" in ticker_html.lower(), "Ticker does not show run completion summary!"
        print("[OK] Live Incident Tracker displays RUN COMPLETE verdict and telemetry without getting stuck!", flush=True)

        # ------------------------------------------------------------------ #
        # Check Item 6: Replay Scrubber and PLAY button
        # ------------------------------------------------------------------ #
        print("\nChecking Item 6: Replay Scrubber and PLAY button...", flush=True)
        # Switch to Analyze tab where Replay Scrubber is displayed
        page.click("#viewAnalyzeBtn")
        time.sleep(0.5)
        
        replay_label = page.inner_text("#wow-replay-label")
        print("Replay label before scrubbing:", replay_label, flush=True)
        
        # Click Replay PLAY button
        play_btn = page.locator("#wow-replay-play")
        play_btn.click()
        time.sleep(1.0)
        
        replay_label_playing = page.inner_text("#wow-replay-label")
        print("Replay label after PLAY click:", replay_label_playing, flush=True)
        assert "frame" in replay_label_playing.lower() or "t " in replay_label_playing.lower(), f"Replay scrubber did not load/play frames: {replay_label_playing}"
        
        # Test slider scrubbing
        slider = page.locator("#wow-replay-slider")
        slider_max = int(slider.get_attribute("max") or "0")
        print("Replay slider max frames:", slider_max, flush=True)
        assert slider_max > 0, "Replay slider max is 0 (no replay frames)!"
        
        # Scrub to frame 10
        page.evaluate("() => { const s = document.getElementById('wow-replay-slider'); s.value = '10'; s.dispatchEvent(new Event('input')); }")
        time.sleep(0.5)
        replay_label_scrubbed = page.inner_text("#wow-replay-label")
        print("Replay label after scrubbing to frame 10:", replay_label_scrubbed, flush=True)
        assert "frame 11" in replay_label_scrubbed or "frame 10" in replay_label_scrubbed
        print("[OK] Replay scrubber PLAY and slider scrubbing work reliably with frames in memory!", flush=True)

        browser.close()
        print("\n========================================================", flush=True)
        print(">>> ALL 7 FIXES TESTED AND VERIFIED SUCCESSFULLY! <<<", flush=True)
        print("========================================================", flush=True)

if __name__ == "__main__":
    run_tests()
