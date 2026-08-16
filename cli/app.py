"""
Textual CLI dashboard — the same engine core, a terminal twin of the web
dashboard. Every panel is fed by Engine.snapshot() / events_since(), so both
UIs share one simulation and one explainability contract.

Keys:  space  play/pause     s  step one tick     r  reset
       R      replay run from memory (snapshot history)
       e      toggle decisions feed / full event stream
       + / -  speed          q  quit

Policy flags:  --dispatch cnp|greedy   --replan dstar|full_astar
               --idle mdp|station      --hospital csp|first_free
"""

from __future__ import annotations

import argparse
from typing import Dict, List, Optional

from rich.text import Text

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets._static import Static
from textual.widgets._header import Header
from textual.widgets._footer import Footer

from core.engine import Engine
from core.policies import BASELINE_LABELS, SUBSYSTEMS
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
    "dispatch.auction.award": "bright_cyan",
    "dispatch.auction.announce": "cyan",
    "dispatch.auction.bid": "cyan",
    "dispatch.auction.reject": "grey54",
    "dispatch.greedy": "lime",
    "dispatch.renegotiated": "bright_magenta",
    "ambulance.on_scene": "yellow",
    "hospital.allocated": "magenta",
    "ambulance.replanned": "cyan",
    "replan.cost_compare": "sky_blue3",
    "incident.cleared": "green",
    "mdp.solved": "cyan",
    "world.blockage_detected": "orange1",
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
    #stats { height: 9; border: round $primary; }
    #fairness { height: 8; border: round $primary; }
    #incidents { height: 7; border: round $primary; }
    #decisions { height: 1fr; border: round $primary; }
    #clock { background: $boost; color: $text; text-align: center; height: 1; }
    """

    BINDINGS = [
        ("space", "toggle", "play/pause"),
        ("s", "step", "step"),
        ("r", "reset", "reset"),
        ("R", "replay", "replay"),
        ("e", "toggle_feed", "events"),
        ("plus", "faster", "faster"),
        ("minus", "slower", "slower"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, scenario: str, seed: Optional[int], tps: float = 4.0,
                 policies: Optional[Dict[str, str]] = None) -> None:
        super().__init__()
        self.scenario = scenario
        self.seed = seed
        self.tps = tps
        self.policies = policies
        self.playing = False
        self.engine: Optional[Engine] = None
        self.cursor = 0
        self.timer = None
        self.feed_mode = "decisions"          # decisions | events
        self.replay_ix: Optional[int] = None  # playback cursor

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
                yield Static(id="fairness")
                yield Static(id="incidents")
                yield Static(id="decisions")
        yield Footer()

    def on_mount(self) -> None:
        self.engine = Engine(scenario=self.scenario, seed=self.seed,
                             config={"policies": self.policies}
                             if self.policies else None)
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
                                 seed=self.engine.seed,
                                 config={"policies": self.policies}
                                 if self.policies else None)
            self.cursor = 0
            self.replay_ix = None
            self._refresh()

    def action_replay(self) -> None:
        """Replay the run from memory (snapshot history), web-style."""
        if self.engine is None:
            return
        timeline = self.engine.replay_ticks()
        if not timeline:
            return
        self.playing = False
        if self.timer is not None:
            self.timer.pause()
        self.replay_ix = 0
        self._replay_timer = self.set_interval(
            0.12, self._on_replay_tick, pause=False)

    def _on_replay_tick(self) -> None:
        eng = self.engine
        if eng is None or self.replay_ix is None:
            return
        timeline = eng.replay_ticks()
        if self.replay_ix >= len(timeline):
            self.replay_ix = None
            if self._replay_timer is not None:
                self._replay_timer.stop()
            self._refresh()
            return
        snap = eng.snapshot_at(timeline[self.replay_ix])
        if snap is not None:
            self.query_one(MapWidget).set_snapshot(snap)
            self._render_text_panels(snap, replay=True)
        self.replay_ix += 1

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

    def action_toggle_feed(self) -> None:
        self.feed_mode = "events" if self.feed_mode == "decisions" \
            else "decisions"
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
        if self.engine is None:
            return
        self._render_text_panels(self.engine.snapshot(), replay=False)

    def _render_text_panels(self, snap: Dict, replay: bool) -> None:
        eng = self.engine
        if eng is None:
            return
        if not replay:
            self.query_one(MapWidget).set_snapshot(snap)
        st = snap["stats"]
        policies = st.get("policies", {})
        pol = "/".join(BASELINE_LABELS.get(policies.get(k, k), policies.get(k, k))
                       for k in SUBSYSTEMS)

        state = "replaying" if self.replay_ix is not None \
            else ("playing" if self.playing else "paused")
        color = "green" if state == "playing" else "cyan" \
            if state == "replaying" else "yellow"
        self.query_one("#clock", Static).update(
            f"[bold]t {snap['tick']}[/] · [bold]{snap['seconds']:.0f}s[/]   "
            f"{snap['scenario']['title']} (seed {snap['scenario']['seed']})   "
            f"[{color}]{state}[/]   {self.tps:.1f} t/s   "
            f"policies {pol}")

        eq = st.get("equity") or {}
        self.query_one("#stats", Static).update(
            f"[bold]reported[/] {st['incidents_reported']}  "
            f"[bold]cleared[/] {st['incidents_cleared']}  "
            f"[bold]active[/] {st['active']}  [bold]queue[/] {st['queue']}\n"
            f"response avg [bold]{st['response_avg']:.0f}s[/] "
            f"p95 [bold]{st['response_p95']:.0f}s[/] "
            f"var [bold]{st.get('response_variance', 0.0):.0f}[/]   "
            f"distance [bold]{st['total_distance_km']:.1f} km[/]   "
            f"replans [bold]{st['replans']}[/]   "
            f"replan saved [bold]{st.get('replan_savings_expansions', 0)} exp[/]\n"
            f"A* {st['search_expansions']['astar']}   "
            f"LRTA* {st['search_expansions']['lrta']}   "
            f"D* Lite {st['search_expansions']['dstar']}   |   "
            f"CSP {st['csp_solves']} solves / {st['csp_backtracks']} bt   "
            f"MDP {st['mdp_solves']} solves   arena {st['arena_runs']}\n"
            f"[bold magenta]equity[/] gini [bold]{eq.get('gini', 0.0):.3f}[/] "
            f"best [bold]{eq.get('best_zone') or '—'}[/] "
            f"worst [bold]{eq.get('worst_zone') or '—'}[/]   "
            f"[bold magenta]renegotiated[/] {st.get('renegotiations', 0)} "
            f"({st.get('renegotiation_savings_s', 0.0):.0f}s saved)")

        fair_lines = ["[bold]zone fairness (mean response)[/]"]
        per_zone = (eq.get("per_zone") or {})
        best, worst = eq.get("best_zone"), eq.get("worst_zone")
        if per_zone:
            ordered = sorted(per_zone.items(),
                             key=lambda kv: (kv[1]["mean"] or 0))
            for z, m in ordered:
                tag = "[green]BEST[/]" if z == best \
                    else "[red]WORST[/]" if z == worst else ""
                fair_lines.append(
                    f"  {z:<5} n={m['n']:<2} mean [bold]{m['mean']:>6.0f}s[/] "
                    f"p95 {m['p95']:>6.0f}s  {tag}")
        else:
            fair_lines.append("  no zone response data yet")
        self.query_one("#fairness", Static).update("\n".join(fair_lines))

        inc_lines = ["[bold]incidents[/]"]
        for i in snap["incidents"]:
            if i["status"] == "cleared":
                continue
            inc_lines.append(
                f"  {i['id']} S{i['severity']} {i['kind'][:18]:<18} "
                f"[{KIND_COLOR.get('incident.reported', '')}]"
                f"{i['status']}[/] unit {i['ambulance_id'] or '—'}")
        self.query_one("#incidents", Static).update("\n".join(inc_lines))

        if self.feed_mode == "events":
            lines = [f"[bold]event stream ({state})[/]"]
            for tick, e in list(eng.events)[-14:]:
                col = KIND_COLOR.get(e.kind, "grey")
                lines.append(f"  t{tick:<4} [{col}]{e.kind}[/] {e.summary}")
        else:
            lines = ["[bold]recent decisions[/]"]
            for e in snap["recent_decisions"][-14:]:
                col = KIND_COLOR.get(e["kind"], "grey")
                lines.append(
                    f"  t{e['tick']:<4} [{col}]{e['kind']}[/] {e['summary']}")
        self.query_one("#decisions", Static).update("\n".join(lines))

    # ------------------------------------------------------------------ #
    # Engine helpers                                                      #
    # ------------------------------------------------------------------ #
    @property
    def _replay_timer(self):
        return getattr(self, "_replay_timer_ref", None)

    @_replay_timer.setter
    def _replay_timer(self, timer) -> None:
        self._replay_timer_ref = timer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    summaries = scenario_summaries()
    parser.add_argument("--scenario", choices=[s["id"] for s in summaries],
                        default="downtown-rush")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--tps", type=float, default=4.0)
    parser.add_argument("--dispatch", choices=["cnp", "greedy"], default=None)
    parser.add_argument("--replan", choices=["dstar", "full_astar"],
                        default=None)
    parser.add_argument("--idle", choices=["mdp", "station"], default=None)
    parser.add_argument("--hospital", choices=["csp", "first_free"],
                        default=None)
    args = parser.parse_args()
    policies = {k: v for k, v in [
        ("dispatch", args.dispatch), ("replan", args.replan),
        ("idle", args.idle), ("hospital", args.hospital)] if v}
    DashboardApp(args.scenario, args.seed, args.tps,
                 policies or None).run()


if __name__ == "__main__":
    main()