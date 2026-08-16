"""
Fairness / equity metrics for the dispatch system.

The simulation's headline metric is the *mean* response time. Means hide
inequality: a system can have an excellent average while one zone is
consistently served 3× slower than the rest. This module computes the
equity view of a run:

  * ``gini_coefficient`` — the classic Gini index (0 = perfectly equal,
    1 = maximal inequality) computed over per-zone mean response times.
    Hand-computable, so tests can pin it to exact expected values.
  * ``zone_equity``      — a serialisable summary: per-zone counts/means/p95,
    best- and worst-served zones, min/max ratio and a per-zone variance
    alternative to Gini (the "variance" option of the equity metric).

Everything is counting statistics over observed response times — no
learned models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Gini coefficient                                                            #
# --------------------------------------------------------------------------- #

def gini_coefficient(values: List[float]) -> float:
    """Gini index over a list of non-negative values.

    For sorted values x_1 <= ... <= x_n with total T, the standard
    (relative-mean-difference) Gini is::

        G = (2 * sum(i * x_i)) / (n * T) - (n + 1) / n

    Properties:
      * G = 0 for perfectly equal values (all identical).
      * G = (n - 1) / (3n) ... bounded by [0, (n-1)/n), 0 for equality.
      * Values of zero are legal (zones with zero response time) and the
        formula stays exact.
    """
    vals = sorted(float(v) for v in values)
    n = len(vals)
    if n == 0:
        return 0.0
    total = sum(vals)
    if total <= 0.0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(vals))
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


def _p95(values: List[float]) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    return s[int(0.95 * (len(s) - 1))]


# --------------------------------------------------------------------------- #
# Per-zone equity summary                                                     #
# --------------------------------------------------------------------------- #

def zone_equity(zone_times: Dict[str, List[float]],
                all_zones: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build the serialisable equity block for one run.

    ``zone_times`` maps zone id -> observed response times (seconds).
    ``all_zones`` optionally supplies the full zone roster so zones with
    zero incidents appear with ``n=0`` (neutral in the UI heatmap).

    Returns::

        {"gini": float, "zone_variance": float,
         "per_zone": {zone: {"n": int, "mean": float, "p95": float}},
         "served_zones": int, "zones": int,
         "best_zone": str|None, "worst_zone": str|None,
         "max_min_ratio": float|None}
    """
    roster = list(all_zones) if all_zones is not None \
        else list(zone_times.keys())
    per_zone: Dict[str, Dict[str, Any]] = {}
    for z in roster:
        times = zone_times.get(z, [])
        per_zone[z] = {"n": len(times),
                       "mean": round(sum(times) / len(times), 2) if times
                       else 0.0,
                       "p95": round(_p95(times), 2) if times else 0.0}
    served = {z: d for z, d in per_zone.items() if d["n"] > 0}
    means = [d["mean"] for d in served.values()]

    gini = gini_coefficient(means) if len(means) >= 1 else 0.0
    zone_var = 0.0
    if len(means) >= 2:
        m = sum(means) / len(means)
        zone_var = sum((x - m) ** 2 for x in means) / len(means)

    best = worst = None
    ratio = None
    if served:
        best = min(served, key=lambda z: served[z]["mean"])
        worst = max(served, key=lambda z: served[z]["mean"])
        if served[best]["mean"] > 0:
            ratio = served[worst]["mean"] / served[best]["mean"]

    return {"gini": round(gini, 6),
            "zone_variance": round(zone_var, 2),
            "per_zone": per_zone,
            "served_zones": len(served),
            "zones": len(roster),
            "best_zone": best,
            "worst_zone": worst,
            "max_min_ratio": round(ratio, 2) if ratio is not None else None}