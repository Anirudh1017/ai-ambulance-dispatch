"""Verify the IDLE status dot actually renders a visible indicator.

Regression guard for the missing `.dot-idle` rule: before the fix the 8px
circle had no background and rendered fully transparent, leaving the left
side of the status chip visually empty while the label read "IDLE".
"""
import time

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000/"

# Parse "rgb(r, g, b)" / "rgba(r, g, b, a)" into a tuple.
def parse_rgba(value):
    nums = value.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")
    r, g, b = (int(float(n)) for n in nums[:3])
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return r, g, b, a


def dot_appearance(page):
    return page.evaluate("""() => {
      const d = document.getElementById("status-dot");
      if (!d) return null;
      const cs = getComputedStyle(d);
      const r = d.getBoundingClientRect();
      return {
        cls: d.className,
        text: document.getElementById("status-text").textContent.trim(),
        bg: cs.backgroundColor,
        border: cs.borderTopWidth + " " + cs.borderTopStyle + " " + cs.borderTopColor,
        w: Math.round(r.width * 100) / 100,
        h: Math.round(r.height * 100) / 100,
      };
    }""")


def is_visible(appearance):
    """A dot counts as visible if it paints pixels: opaque fill or a solid border."""
    _, _, _, alpha = parse_rgba(appearance["bg"])
    bw, bstyle, _ = appearance["border"].split(" ", 2)
    solid_border = bstyle != "none" and float(bw.replace("px", "")) > 0
    painted_fill = alpha > 0.05
    return painted_fill or solid_border


def main():
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # --- 1. IDLE on launch: the bug under test --------------------------- #
        idle = dot_appearance(page)
        print("1. IDLE dot:", idle)
        assert idle["text"] == "IDLE", f"Expected IDLE label, got {idle['text']}"
        assert "dot-idle" in idle["cls"], f"Expected dot-idle class, got {idle['cls']}"
        assert is_visible(idle), "IDLE dot renders with no painted pixels (invisible)"
        assert idle["w"] > 0 and idle["h"] > 0, "IDLE dot has zero size"
        print("[OK] IDLE dot is visible and sized\n")

        # --- 2. Every other state must also stay visible --------------------- #
        for label, mod_cls in [
            ("RUNNING", "dot-running"),
            ("PAUSED", "dot-paused"),
            ("FINISHED", "dot-finished"),
        ]:
            page.evaluate(
                """(cls) => {
                    const d = document.getElementById("status-dot");
                    d.className = "dot " + cls;
                }""",
                mod_cls,
            )
            time.sleep(0.3)
            app = dot_appearance(page)
            print(f"{label} dot:", app)
            assert app["text"] == label, f"Expected {label} label, got {app['text']}"
            assert is_visible(app), f"{label} dot is invisible"
        print("[OK] RUNNING / PAUSED / FINISHED dots all render\n")

        # --- 3. Restore + confirm idle still fine after cycling -------------- #
        page.evaluate(
            """() => { document.getElementById("status-dot").className = "dot dot-idle"; }"""
        )
        time.sleep(0.3)
        restored = dot_appearance(page)
        assert restored["text"] == "IDLE" and is_visible(restored), "IDLE not restored"
        print("[OK] IDLE restored after state cycling\n")

        # --- 4. Real user flow: START -> RUNNING, PAUSE -> PAUSED ----------- #
        page.click("#btn-start")
        page.wait_for_function(
            "() => document.getElementById('status-text').textContent.trim() === 'RUNNING'",
            timeout=15000,
        )
        running = dot_appearance(page)
        print("After START:", running)
        assert "dot-running" in running["cls"] and is_visible(running), "RUNNING dot bad"
        assert parse_rgba(running["bg"])[3] > 0.05, "RUNNING dot fill is transparent"

        page.click("#btn-pause")
        page.wait_for_function(
            "() => document.getElementById('status-text').textContent.trim() === 'PAUSED'",
            timeout=10000,
        )
        paused = dot_appearance(page)
        print("After PAUSE:", paused)
        assert "dot-paused" in paused["cls"] and is_visible(paused), "PAUSED dot bad"
        assert parse_rgba(paused["bg"])[3] > 0.05, "PAUSED dot fill is transparent"
        print("[OK] Real START / PAUSE flow paints solid dots")

        assert not errors, f"Console errors: {errors}"
        print("\nALL CHECKS PASSED — IDLE indicator is visible.\n")

        # --- 5. Zoomed screenshots of the status chip, both themes ----------- #
        # Force idle first: the real START/PAUSE flow above left us on PAUSED.
        page.evaluate(
            """() => { document.getElementById("status-dot").className = "dot dot-idle"; }"""
        )
        time.sleep(0.4)
        chip = page.locator(".status-chip")
        for theme in ("light", "dark"):
            page.evaluate(
                "(t) => { document.documentElement.setAttribute('data-theme', t); }", theme
            )
            time.sleep(0.6)
            shot = dot_appearance(page)
            assert shot["text"] == "IDLE" and is_visible(shot), f"{theme} idle not visible"
            out = f"status_chip_{theme}.png"
            chip.screenshot(path=out)
            print(f"[SHOT] {out} -> {shot}")

        # --- 6. Regression proof: the check must fail without the CSS rule -- #
        # Force the idle state first (the real flow above left us on PAUSED).
        page.evaluate(
            """() => { document.getElementById("status-dot").className = "dot dot-idle"; }"""
        )
        time.sleep(0.4)
        baseline = dot_appearance(page)
        assert "dot-idle" in baseline["cls"] and is_visible(baseline), "Idle not applied"
        print("Idle dot before neutralising:", baseline)

        page.evaluate(
            """() => {
                const s = document.createElement("style");
                s.id = "kill-idle-dot";
                s.textContent = ".dot-idle { background: transparent !important; "
                              + "border: none !important; }";
                document.head.appendChild(s);
            }"""
        )
        time.sleep(0.4)
        regressed = dot_appearance(page)
        print("With .dot-idle neutralised:", regressed)
        assert not is_visible(regressed), (
            "Guard is ineffective: dot still visible with the rule removed"
        )
        print("[OK] Regression guard confirmed: removing the rule makes the dot invisible again.\n")

        browser.close()

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
