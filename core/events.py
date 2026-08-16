"""
Structured, serialisable decision events emitted by the simulation engine.

Every decision the system makes — a search expansion, a CNP auction phase,
a CSP backtrack, an MDP policy choice, a replan — is recorded as an event.
Both user interfaces (FastAPI web dashboard, Textual CLI dashboard) consume
these events through ``Engine.events_since()``.

Each event carries:
  * ``tick``      — simulation tick at which it was emitted
  * ``kind``      — machine-readable event type (filter key in the UIs)
  * ``summary``   — one human-readable sentence for explainability panels
  * ``detail``    — arbitrary JSON-serialisable payload
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Event:
    """Base structured event. ``kind`` subclasses the schema; ``summary``
    is the explainability text shown in both dashboards."""

    tick: int
    kind: str
    summary: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick": self.tick,
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
        }


def _fmt_eta(seconds: float) -> str:
    return f"{seconds:.0f}s" if seconds >= 60 else f"{seconds:.1f}s"


# --------------------------------------------------------------------------- #
# Incident lifecycle                                                          #
# --------------------------------------------------------------------------- #

def incident_reported(tick: int, incident_id: str, node: str, severity: int,
                      kind: str, scene: str) -> Event:
    return Event(
        tick, "incident.reported",
        f"911 call at {scene}: {kind} (severity {severity}) — "
        f"contract-net auction opened for incident {incident_id}.",
        {"incident_id": incident_id, "node": node, "severity": severity,
         "kind": kind, "scene": scene},
    )


def auction_phase(tick: int, incident_id: str, phase: str,
                  payload: Dict[str, Any]) -> Event:
    texts = {
        "announce": f"CNP announce: task for incident {incident_id} "
                    f"broadcast to {payload.get('eligible', 0)} free units.",
        "bid": f"CNP bid: {payload.get('ambulance_id')} proposes ETA "
               f"{_fmt_eta(payload.get('eta_seconds', 0))} via "
               f"{payload.get('algorithm')}.",
        "award": f"CNP award: {payload.get('winner')} wins incident "
                 f"{incident_id} (score {payload.get('score')}).",
        "reject": f"CNP reject: {payload.get('ambulance_id')} refused "
                  f"incident {incident_id} — "
                  f"{payload.get('reason', 'no feasible ETA')}.",
    }
    return Event(tick, "dispatch.auction." + phase, texts[phase], payload)


def ambulance_dispatched(tick: int, ambulance_id: str, incident_id: str,
                         node: str, route_len: int, algorithm: str,
                         eta_seconds: float) -> Event:
    return Event(
        tick, "ambulance.dispatched",
        f"Unit {ambulance_id} en route to incident {incident_id} "
        f"(route {route_len} edges via {algorithm}, ETA {_fmt_eta(eta_seconds)}).",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "node": node, "route_len": route_len, "algorithm": algorithm,
         "eta_seconds": eta_seconds},
    )


def greedy_dispatch(tick: int, incident_id: str, ambulance_id: str,
                    eta_seconds: float, candidates: int,
                    algorithm: str = "A*", scene_node: str = "") -> Event:
    """Baseline-policy dispatch: nearest available unit, no CNP auction."""
    return Event(
        tick, "dispatch.greedy",
        f"Greedy baseline: nearest available unit {ambulance_id} awarded "
        f"incident {incident_id} (ETA {_fmt_eta(eta_seconds)}, single "
        f"criterion, {candidates} candidate(s) — no CNP auction).",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "eta_seconds": eta_seconds, "candidates": candidates,
         "algorithm": algorithm, "node": scene_node},
    )


def ambulance_arrived_scene(tick: int, ambulance_id: str, incident_id: str,
                            on_scene_seconds: float) -> Event:
    return Event(
        tick, "ambulance.on_scene",
        f"Unit {ambulance_id} on scene at {incident_id}; response time "
        f"{_fmt_eta(on_scene_seconds)}. Providing {on_scene_seconds:.0f}s "
        f"of stabilisation.",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "on_scene_seconds": on_scene_seconds},
    )


def hospital_allocated(tick: int, incident_id: str, hospital_id: str,
                       distance_km: float, beds_used: int, csp_info: Dict[str, Any]) -> Event:
    return Event(
        tick, "hospital.allocated",
        f"CSP allocation: incident {incident_id} -> {hospital_id} "
        f"({distance_km:.1f} km, {beds_used} bed(s) reserved). "
        f"CSP: {csp_info.get('assignments')} assignments, "
        f"{csp_info.get('backtracks')} backtrack(s), {csp_info.get('nodes')} nodes.",
        {"incident_id": incident_id, "hospital_id": hospital_id,
         "distance_km": distance_km, "beds_used": beds_used,
         "csp": csp_info},
    )


def patient_loaded(tick: int, ambulance_id: str, incident_id: str,
                   hospital_id: str) -> Event:
    return Event(
        tick, "ambulance.transporting",
        f"Unit {ambulance_id} transporting patient from {incident_id} "
        f"to {hospital_id}.",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "hospital_id": hospital_id},
    )


def arrived_hospital(tick: int, ambulance_id: str, incident_id: str,
                     hospital_id: str, bed_freed_after: float) -> Event:
    return Event(
        tick, "ambulance.hospital_arrival",
        f"Unit {ambulance_id} delivered patient of {incident_id} to "
        f"{hospital_id}; bed held {bed_freed_after:.0f}s for handover.",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "hospital_id": hospital_id, "handover_seconds": bed_freed_after},
    )


def incident_cleared(tick: int, incident_id: str, severity: int,
                     response_seconds: float, total_seconds: float) -> Event:
    return Event(
        tick, "incident.cleared",
        f"Incident {incident_id} closed (severity {severity}); response "
        f"{_fmt_eta(response_seconds)}, end-to-end {_fmt_eta(total_seconds)}.",
        {"incident_id": incident_id, "severity": severity,
         "response_seconds": response_seconds, "total_seconds": total_seconds},
    )


# --------------------------------------------------------------------------- #
# Search / replanning                                                         #
# --------------------------------------------------------------------------- #

def blockage_detected(tick: int, edge_u: str, edge_v: str, ambulance_id: Optional[str],
                      reason: str) -> Event:
    return Event(
        tick, "world.blockage_detected",
        f"Edge {edge_u}–{edge_v} discovered BLOCKED by {reason}"
        + (f" (unit {ambulance_id} detects it locally)" if ambulance_id else "")
        + ". World model updated.",
        {"edge_u": edge_u, "edge_v": edge_v, "ambulance_id": ambulance_id,
         "reason": reason},
    )


def route_replanned(tick: int, ambulance_id: str, incident_id: str,
                    old_len: int, new_len: int, algorithm: str,
                    cause: str, saved_edges: int, expansions: int) -> Event:
    return Event(
        tick, "ambulance.replanned",
        f"Unit {ambulance_id} replanned route for {incident_id} via "
        f"{algorithm} ({cause}): {old_len} -> {new_len} edges "
        f"({saved_edges} shared, {expansions} expansions).",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "old_len": old_len, "new_len": new_len, "algorithm": algorithm,
         "cause": cause, "shared_edges": saved_edges, "expansions": expansions},
    )


def replan_summary(tick: int, ambulance_id: str, incident_id: str,
                   dstar_expansions: int, full_rerun_expansions: int,
                   savings: int) -> Event:
    """Counterfactual cost of a full rerun vs the actual incremental
    replan, logged so the benchmark can show per-replan savings."""
    return Event(
        tick, "replan.cost_compare",
        f"Replan cost: D* Lite {dstar_expansions} expansion(s) vs full A* "
        f"rerun {full_rerun_expansions} — {savings} expansion(s) saved "
        f"(unit {ambulance_id}, incident {incident_id}).",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "dstar_expansions": dstar_expansions,
         "full_rerun_expansions": full_rerun_expansions,
         "savings": savings},
    )


def search_trace(tick: int, algorithm: str, start: str, goal: str,
                 expanded: int, generated: int, cost: Optional[float],
                 optimal: bool, duration_ms: float) -> Event:
    return Event(
        tick, "search.run",
        f"{algorithm}: {start} -> {goal}, expanded {expanded} node(s), "
        f"cost {cost if cost is not None else '—'} ({'optimal' if optimal else 'budgeted'} "
        f"in {duration_ms:.1f} ms).",
        {"algorithm": algorithm, "start": start, "goal": goal,
         "expanded": expanded, "generated": generated, "cost": cost,
         "optimal": optimal, "duration_ms": duration_ms},
    )


# --------------------------------------------------------------------------- #
# MDP idle positioning                                                        #
# --------------------------------------------------------------------------- #

def idle_reposition(tick: int, ambulance_id: str, from_zone: str, to_zone: str,
                    value: float, policy_provenance: str, iterations: int,
                    travel_seconds: float, rationale: str) -> Event:
    return Event(
        tick, "ambulance.idle_move",
        f"Unit {ambulance_id} repositions zone {from_zone} -> {to_zone} "
        f"(MDP policy, V={value:.2f}, {iterations} value-iteration sweeps, "
        f"{_fmt_eta(travel_seconds)} to arrive). {rationale}",
        {"ambulance_id": ambulance_id, "from_zone": from_zone,
         "to_zone": to_zone, "value": value, "iterations": iterations,
         "travel_seconds": travel_seconds, "policy": policy_provenance},
    )


def mdp_summary(tick: int, states: int, actions: int, iterations: int,
                residual: float, gamma: float) -> Event:
    return Event(
        tick, "mdp.solved",
        f"MDP solved by exact value iteration: {states} states x {actions} "
        f"actions, {iterations} sweeps, Bellman residual {residual:.2e}, "
        f"γ={gamma}.",
        {"states": states, "actions": actions, "iterations": iterations,
         "residual": residual, "gamma": gamma},
    )


# --------------------------------------------------------------------------- #
# World / misc                                                                #
# --------------------------------------------------------------------------- #

def status_change(tick: int, ambulance_id: str, old: str, new: str) -> Event:
    return Event(
        tick, "ambulance.status",
        f"Unit {ambulance_id}: {old} -> {new}.",
        {"ambulance_id": ambulance_id, "old": old, "new": new},
    )


def scenario_started(tick: int, scenario: str, seed: int,
                     ambulances: int, incidents: int) -> Event:
    return Event(
        tick, "sim.start",
        f"Simulation started: scenario '{scenario}' (seed {seed}), "
        f"{ambulances} unit(s), {incidents} scheduled incident(s).",
        {"scenario": scenario, "seed": seed, "ambulances": ambulances,
         "incidents": incidents},
    )


def incident_generated(tick: int, incident_id: str, node: str, severity: int,
                       kind: str, due_tick: int) -> Event:
    return Event(
        tick, "sim.incident_scheduled",
        f"Incident {incident_id} scheduled at tick {due_tick} "
        f"({kind}, severity {severity}) at node {node}.",
        {"incident_id": incident_id, "node": node, "severity": severity,
         "kind": kind, "due_tick": due_tick},
    )


def dispatch_failed(tick: int, incident_id: str, reason: str) -> Event:
    return Event(
        tick, "dispatch.failed",
        f"No unit could take incident {incident_id}: {reason}. "
        f"It stays in the queue.",
        {"incident_id": incident_id, "reason": reason},
    )


def scrape_route(tick: int, ambulance_id: str, incident_id: str,
                 destination: str, cause: str) -> Event:
    return Event(
        tick, "ambulance.replanned",
        f"Unit {ambulance_id} ({incident_id}) re-plans to {destination} "
        f"({cause}).",
        {"ambulance_id": ambulance_id, "incident_id": incident_id,
         "destination": destination, "cause": cause},
    )


def engine_message(tick: int, level: str, text: str) -> Event:
    return Event(tick, f"sim.{level}", text, {"level": level, "text": text})


def event_from_dict(d: Dict[str, Any]) -> Event:
    """Deserialise an event dict back into an ``Event`` (used by replay)."""
    return Event(tick=d["tick"], kind=d["kind"], summary=d["summary"],
                 detail=d.get("detail", {}))
