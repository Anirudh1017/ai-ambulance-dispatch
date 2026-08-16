"""
Textual CLI dashboard — the same engine core, a terminal twin of the web
dashboard. Every panel is fed by Engine.snapshot() / events_since(), so both
UIs share one simulation and one explainability contract.

Keys:  space  play/pause     s  step one tick     r  reset
       + / -  speed          q  quit
"""

from __future__ import annotations

import argparse
import time
from typing import Dict, List, Optional

from rich.text import Text

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets._static import Static
from textual.widgets._header import Header
from textual.widgets._footer import Footer

from core.engine import Engine
from core.scenarios import scenario_summaries

STATUS_COLOR = {
    "idle": "grey",
    "drifting": "cyan",
    "enroute": "green",
    "on_scene": "yellow",
    "transporting": "magenta",
    "returning": "orange",
    "blocked": "red",
}
KIND_COLOR = {
    "incident.reported": "red",
    "ambulance.dispatched": "green",
    "ambulance.on_scene": "yellow",
    "hospital.allocated": "magenta",
    "ambulance.replanned": "cyan",
    "incident.cleared": "green",
    "mdp.solved": "cyan",
    "world.blockage_detected": "orange",
    "dispatch.failed": "red",
}

CELL_W, CELL_H = 4, 2          # ascii cell size per graph cell


class MapWidget(Static):
    """ASCII map of one engine snapshot (grid city, nodes on exact grid)."""

    def __init__(self) -> None:
        super().__init__(markup=False)
        self._snap: Optional[Dict] = None

    def set_snapshot(self, snap: Dict) -> None:
        self._snap = snap
        self.update(self._compose_ascii())

    def _compose_ascii(self) -> Text:
        snap = self._snap
        out = Text()
        if snap is None:
            return out
        m = snap["map"]
        rows, cols = 0, 0
        for n in m["nodes"]:
            r, c = n["id"][1:].split("_")
            rows = max(rows, int(r) + 1)
            cols = max(cols, int(c) + 1)
        W = cols * CELL_W + 1
        H = rows * CELL_H + 1
        grid: List[List[Optional[str]]] = [
            [None] * W for _ in range(H)]

        def setc(x: int, y: int, ch: str) -> None:
            if 0 <= x < W and 0 <= y < H:
                grid[y][x] = ch

        # edges
        for e in m["edges"]:
            r1, c1 = map(int, e["u"][1:].split("_"))
            r2, c2 = map(int, e["v"][1:].split("_"))
            if r1 == r2:                      # horizontal
                for x in range(c1 * CELL_W + 1, c2 * CELL_W):
                    setc(x, r1 * CELL_H, "─")
            else:                             # vertical
                setc(c1 * CELL_W, min(r1, r2) * CELL_H + 1, "│")

        # zone centres (coloured bracket)
        for i, z in enumerate(m["zones"]):
            cx, cy = z["center"]
            xs = [n["x"] for n in m["nodes"]]
            ys = [n["y"] for n in m["nodes"]]
            nx = min(m["nodes"], key=lambda n: (n["x"] - cx) ** 2
                     + (n["y"] - cy) ** 2)
            r, c = map(int, nx["id"][1:].split("_"))
            ch = str(i + 1)
            setc(c * CELL_W, r * CELL_H, ch)

        # blockages overwrite edges
        for u, v in snap["blockages"]["revealed"]:
            self._block_edge(grid, u, v, "X")
        for u, v in snap["blockages"]["hidden"]:
            self._block_edge(grid, u, v, "?")

        # hospitals
        for h in m["hospitals"]:
            r, c = map(int, h["node"][1:].split("_"))
            setc(c * CELL_W, r * CELL_H, "H")

        # incidents
        for inc in snap["incidents"]:
            if inc["status"] == "cleared":
                continue
            r, c = map(int, inc["node"][1:].split("_"))
            setc(c * CELL_W, r * CELL_H, str(inc["severity"]))

        # ambulances (collisions become a digit)
        for a in snap["ambulances"]:
            r, c = map(int, a["node"][1:].split("_"))
            x, y = c * CELL_W, r * CELL_H
            if grid[y][x] is not None and grid[y][x] not in ("│", "─"):
                cur = grid[y][x]
                grid[y][x] = str(int(cur) + 1) if cur.isdigit() else "a"
            else:
                grid[y][x] = "A"

        # flush grid with colours
        for y in range(H):
            for x in range(W):
                ch = grid[y][x]
                if ch is None:
                    out.append(" ")
                elif ch == "─" or ch == "│":
                    out.append(ch, style="grey35")
                elif ch == "X":
                    out.append(ch, style="orange1")
                elif ch == "?":
                    out.append(ch, style="grey62")
                elif ch == "H":
                    out.append(ch, style="bold bright_blue")
                elif ch in ("3", "4", "5"):
                    out.append(ch, style="bold red")
                elif ch == "A":
                    out.append(ch, style="bold green")
                elif ch.isdigit():
                    out.append(ch, style="bold cyan")
                else:
                    out.append(ch)
            if y < H - 1:
                out.append("\n")
        return out

    def _block_edge(self, grid: List[List[Optional[str]]], u: str, v: str,
                    ch: str) -> None:
        r1, c1 = map(int, u[1:].split("_"))
        r2, c2 = map(int, v[1:].split("_"))
        if r1 == r2:
            for x in range(c1 * CELL_W + 1, c2 * CELL_W):
                grid[r1 * CELL_H][x] = ch
        else:
            grid[min(r1, r2) * CELL_H + 1][c1 * CELL_W] = ch


class DashboardApp(App):
    TITLE = "AI Ambulance Dispatch & Routing"
    CSS = """
    Screen { layout: horizontal; }
    #left { width: 2fr; }
    #right { width: 1fr; }
    MapWidget { height: 1fr; border: round $primary; padding: 1 2; }
    Static { padding: 0 1; }
    #stats { height: auto; border: round $primary; }
    #incidents { height: 7; border: round $primary; }
    #decisions { height: 1fr; border: round $primary; }
    #clock { background: $boost; color: $text; text-align: center; height: 1; }
    """

    BINDINGS = [
        ("space", "toggle", "play/pause"),
        ("s", "step", "step"),
        ("r", "reset", "reset"),
        ("plus", "faster", "faster"),
        ("minus", "slower", "slower"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, scenario: str, seed: Optional[int],
                 tps: float = 4.0) -> None:
        super().__init__()
        self.scenario = scenario
        self.seed = seed
        self.tps = tps
        self.playing = False
        self.engine: Optional[Engine] = None
        self.cursor = 0
        self.timer = None

    # ------------------------------------------------------------------ #
    # Composition                                                         #
    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left"):
                yield MapWidget()
                yield Static(id="clock", markup=False)
            with VerticalScroll(id="right"):
                yield Static(id="stats")
                yield Static(id="incidents")
                yield Static(id="decisions")
        yield Footer()

    def on_mount(self) -> None:
        self.engine = Engine(scenario=self.scenario, seed=self.seed)
        self._refresh()
        self.action_toggle()

    # ------------------------------------------------------------------ #
    # Control actions                                                     #
    # ------------------------------------------------------------------ #
    def action_toggle(self) -> None:
        if self.engine is None:
            return
        self.playing = not self.playing
        if self.playing:
            if self.timer is None:
                self.timer = self.set_interval(1.0 / self.tps,
                                               self._on_tick, pause=False)
            else:
                self.timer.resume()
        elif self.timer is not None:
            self.timer.pause()
        self._refresh()

    def action_step(self) -> None:
        if self.engine is not None:
            self.engine.tick_once()
            self._refresh()

    def action_reset(self) -> None:
        if self.engine is not None:
            self.engine = Engine(scenario=self.scenario,
                                 seed=self.engine.seed)
            self.cursor = 0
            self._refresh()

    def action_faster(self) -> None:
        self.tps = min(30.0, self.tps * 1.5)
        if self.timer is not None and self.playing:
            self.timer.stop()
            self.timer = self.set_interval(1.0 / self.tps,
                                           self._on_tick, pause=False)
        self._refresh()

    def action_slower(self) -> None:
        self.tps = max(0.5, self.tps / 1.5)
        if self.timer is not None and self.playing:
            self.timer.stop()
            self.timer = self.set_interval(1.0 / self.tps,
                                           self._on_tick, pause=False)
        self._refresh()

    def _on_tick(self) -> None:
        if self.engine is None:
            return
        self.engine.tick_once()
        self._refresh()
        if self.engine.tick >= int(self.engine.cfg["max_ticks"]):
            self.playing = False
            if self.timer is not None:
                self.timer.pause()

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        eng = self.engine
        if eng is None:
            return
        snap = eng.snapshot()
        self.query_one(MapWidget).set_snapshot(snap)
        st = snap["stats"]
        fmt = ("[bold]t {tick}[/] · [bold]{seconds}s[/]  {title} (seed {seed})  "
               "[{state}]{state_text}[/]  {tps:.1f} t/s\n\n"
               "[bold]reported[/] {reported}  [bold]cleared[/] {cleared}  "
               "[bold]active[/] {active}  [bold]queue[/] {queue}\n"
               "response avg [bold]{ravg:.0f}s[/] p95 [bold]{rp95:.0f}s[/]  "
               "distance [bold]{dist:.1f} km[/]  replans [bold]{replans}[/]\n"
               "A* {a}  LRTA* {l}  D* Lite {d}   |   CSP {csp} solves / "
               "{bt} backtracks   MDP {mdp} solves   arena {arena}")
        state = "playing" if self.playing else "paused"
        color = "green" if self.playing else "yellow"
        self.query_one("#clock", Static).update(fmt.format(
            tick=snap["tick"], seconds=snap["seconds"],
            title=snap["scenario"]["title"], seed=snap["scenario"]["seed"],
            state=color, state_text=state, tps=self.tps,
            reported=st["incidents_reported"], cleared=st["incidents_cleared"],
            active=st["active"], queue=st["queue"],
            ravg=st["response_avg"], rp95=st["response_p95"],
            dist=st["total_distance_km"], replans=st["replans"],
            a=st["search_expansions"]["astar"],
            l=st["search_expansions"]["lrta"],
            d=st["search_expansions"]["dstar"],
            csp=st["csp_solves"], bt=st["csp_backtracks"],
            mdp=st["mdp_solves"], arena=st["arena_runs"]))

        inc_lines = ["[bold]incidents[/]"]
        for i in snap["incidents"]:
            if i["status"] == "cleared":
                continue
            inc_lines.append(
                f"  {i['id']} S{i['severity']} {i['kind'][:18]:<18} "
                f"[{KIND_COLOR.get('incident.reported', '')}]"
                f"{i['status']}[/] unit {i['ambulance_id'] or '—'}")
        self.query_one("#incidents", Static).update("\n".join(inc_lines))

        dec_lines = ["[bold]recent decisions[/]"]
        for e in snap["recent_decisions"][-14:]:
            col = KIND_COLOR.get(e["kind"], "grey")
            dec_lines.append(
                f"  t{e['tick']:<4} [{col}]{e['kind']}[/] {e['summary']}")
        self.query_one("#decisions", Static).update("\n".join(dec_lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    summaries = scenario_summaries()
    parser.add_argument("--scenario", choices=[s["id"] for s in summaries],
                        default="downtown-rush")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--tps", type=float, default=4.0)
    args = parser.parse_args()
    DashboardApp(args.scenario, args.seed, args.tps).run()


if __name__ == "__main__":
    main()