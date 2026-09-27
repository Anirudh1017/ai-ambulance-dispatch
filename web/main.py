"""
FastAPI + WebSocket dashboard server.

The engine core is a pure-Python tick simulation with zero web dependencies;
this module is a thin, UI-only transport: one Engine per browser session,
streamed over a single WebSocket as JSON snapshots + decision events.

Wire protocol (client -> server):
    {"action": "start",   "scenario": "storm-disaster", "seed": 7}
    {"action": "pause"} | {"action": "resume"} | {"action": "step"}
    {"action": "reset"} | {"action": "set_speed", "tps": 12}
    {"action": "replay"}

Wire protocol (server -> client):
    {"type": "init",          "scenarios": [...], "max_ticks": N}
    {"type": "snapshot",      "data": {...}, "events": [...], "done": bool}
    {"type": "replay_chunk",  "data": [snapshots...]}   (map stripped)
    {"type": "replay_end"}
    {"type": "error",         "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from core import benchmark as bench
from core.engine import Engine
from core.scenarios import scenario_summaries

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="AI Ambulance Dispatch — Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _sanitize_benchmark(data: Any) -> Any:
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return 0.0
        return data
    elif isinstance(data, dict):
        return {k: _sanitize_benchmark(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_sanitize_benchmark(v) for v in data]
    return data


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/benchmark")
def get_benchmark(scenario: Optional[str] = None) -> Dict[str, Any]:
    scen = scenario or "downtown-rush"
    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmark_out", "benchmark_results.csv")
    if os.path.exists(csv_path):
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            if "scenario" in df.columns and scen in df["scenario"].values:
                df = df[df["scenario"] == scen]
                overall = bench.overall(df).to_dict("records")
                return _sanitize_benchmark({"scenario": scen, "seeds": [1, 2, 3], "n_runs": len(df), "rows": overall})
        except Exception:
            pass
    return run_benchmark({"scenario": scen, "seeds": 3})


@app.post("/benchmark")
def run_benchmark(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Small "Run Benchmark" trigger: one scenario × a few seeds × the
    smart vs naive stacks, aggregated inline for the dashboard. The full
    study (4 scenarios × 30 seeds × ablations, CSV + Markdown + PNG
    report) is `run_benchmark.py`; this endpoint is a live preview of the
    same core.benchmark harness. Sync def -> FastAPI threadpool, so the
    simulation event loop is never blocked."""
    scenario = payload.get("scenario") or "downtown-rush"
    n_seeds = max(1, min(int(payload.get("seeds", 3)), 10))
    seeds = list(range(1, n_seeds + 1))
    df = bench.run_benchmark([scenario], seeds)
    overall = bench.overall(df).to_dict("records")
    return _sanitize_benchmark({"scenario": scenario, "seeds": seeds,
                                "n_runs": len(df), "rows": overall})


# --------------------------------------------------------------------------- #
# Per-session simulation                                                      #
# --------------------------------------------------------------------------- #

class SimSession:
    """One browser tab owns one Engine + its tick loop."""

    DEFAULT_TPS = 8.0

    def __init__(self) -> None:
        self.engine: Optional[Engine] = None
        self.cursor = 0
        self.playing = False
        self.tps = self.DEFAULT_TPS
        self.tick_task: Optional[asyncio.Task] = None
        self.replay_task: Optional[asyncio.Task] = None

    # -- lifecycle ----------------------------------------------------------
    def start(self, scenario: str, seed: Optional[int]) -> None:
        self.stop()
        self.engine = Engine(scenario=scenario, seed=seed)
        self.cursor = 0
        self.playing = True
        self.tick_task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        self.playing = False
        for task in (self.tick_task, self.replay_task):
            if task and not task.done():
                task.cancel()
        self.tick_task = self.replay_task = None

    def pause(self) -> None:
        self.playing = False
        if self.tick_task and not self.tick_task.done():
            self.tick_task.cancel()
        self.tick_task = None

    def resume(self) -> None:
        if self.engine is None or self.engine.tick >= int(self.engine.cfg["max_ticks"]):
            return
        if self.tick_task and not self.tick_task.done():
            self.tick_task.cancel()
        self.playing = True
        self.tick_task = asyncio.create_task(self._tick_loop())

    def set_speed(self, tps: float) -> None:
        self.tps = max(1.0, min(120.0, float(tps)))

    # -- engine stepping ------------------------------------------------------
    def tick_once(self) -> bool:
        """One engine tick; True when the simulation finished."""
        if self.engine is None:
            return False
        self.engine.tick_once()
        return self.engine.tick >= int(self.engine.cfg["max_ticks"])

    def snapshot_message(self) -> Dict[str, Any]:
        snap = self.engine.snapshot()
        events, self.cursor = self.engine.events_since(self.cursor)
        done = self.engine.tick >= int(self.engine.cfg["max_ticks"])
        return {"type": "snapshot", "data": snap, "events": events,
                "done": done}

    def status_message(self) -> Dict[str, Any]:
        """Authoritative button-state source: the client renders its
        controls purely from these flags, so UI can never drift from the
        server's actual state."""
        return {"type": "status",
                "running": self.playing and self.engine is not None,
                "has_engine": self.engine is not None,
                "finished": (self.engine is not None
                             and self.engine.tick
                             >= int(self.engine.cfg["max_ticks"]))}

    async def _tick_loop(self) -> None:
        try:
            while self.playing:
                finished = self.tick_once()
                await self._send(self.snapshot_message())
                if finished:
                    self.playing = False
                    await self._send(self.status_message())
                    return
                await asyncio.sleep(1.0 / self.tps)
        except asyncio.CancelledError:
            pass

    # -- replay ----------------------------------------------------------------
    async def replay(self) -> None:
        if self.engine is None:
            return
        ticks = self.engine.replay_ticks()
        if not ticks:
            return
        # strip the (unchanged) map from replayed snapshots to keep the
        # payload small; the client already holds the live map
        chunk: List[Dict[str, Any]] = []
        for t in ticks:
            s = self.engine.snapshot_at(t)
            if s is None:
                continue
            s.pop("map", None)
            chunk.append(s)
            if len(chunk) >= 100:
                await self._send({"type": "replay_chunk", "data": chunk})
                chunk = []
        if chunk:
            await self._send({"type": "replay_chunk", "data": chunk})
        await self._send({"type": "replay_end", "count": len(ticks)})

    # -- transport --------------------------------------------------------------
    def set_socket(self, ws: WebSocket) -> None:
        self._ws = ws

    async def _send(self, message: Dict[str, Any]) -> None:
        if hasattr(self, "_ws"):
            try:
                await self._ws.send_text(json.dumps(message))
            except Exception:
                self.playing = False


# --------------------------------------------------------------------------- #
# WebSocket endpoint                                                          #
# --------------------------------------------------------------------------- #

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session = SimSession()
    session.set_socket(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "init",
            "scenarios": scenario_summaries(),
            "max_ticks": Engine(scenario="downtown-rush").cfg["max_ticks"],
            "default_speed": SimSession.DEFAULT_TPS,
        }))
        # reconnected mid-run: repaint immediately from the current state
        if session.engine is not None:
            await session._send(session.snapshot_message())
        await session._send(session.status_message())
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")
            if action == "start":
                session.start(msg.get("scenario", "downtown-rush"),
                              msg.get("seed"))
                await session._send(session.status_message())
            elif action == "pause":
                session.pause()
                await session._send(session.status_message())
            elif action == "resume":
                session.resume()
                await session._send(session.status_message())
            elif action == "step":
                finished = session.tick_once()
                await session._send(session.snapshot_message())
                if finished:
                    session.playing = False
                await session._send(session.status_message())
            elif action == "reset":
                session.start(session.engine.scenario_name
                              if session.engine else "downtown-rush",
                              session.engine.seed
                              if session.engine else None)
                await session._send(session.status_message())
            elif action == "set_speed":
                session.set_speed(msg.get("tps", session.DEFAULT_TPS))
            elif action == "replay":
                if session.replay_task and not session.replay_task.done():
                    session.replay_task.cancel()
                session.replay_task = asyncio.create_task(session.replay())
            else:
                await session._send({"type": "error",
                                     "message": f"unknown action: {action}"})
    except WebSocketDisconnect:
        pass
    finally:
        session.stop()