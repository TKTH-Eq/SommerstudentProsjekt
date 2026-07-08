"""SCD-oriented analysis: safety register + failure propagation query."""
from __future__ import annotations
import csv
from pathlib import Path
import networkx as nx
from config import SAFETY_TYPES


def safety_register(objects, path: Path):
    """Tags that carry a safety / shutdown role."""
    rows = [o for o in objects if o.type_code in SAFETY_TYPES]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "type", "category", "source"])
        for o in sorted(rows, key=lambda o: o.tag):
            w.writerow([o.tag, o.type_code, o.category, o.source])
    return rows


def failure_propagation(graph: nx.DiGraph, tag: str) -> dict:
    """If `tag` fails, what downstream functions are affected?"""
    if tag not in graph:
        return {"tag": tag, "found": False}
    affected = list(nx.descendants(graph, tag))
    safety_hit = [n for n in affected
                  if graph.nodes[n].get("category") in ("logic", "output")]
    return {
        "tag": tag, "found": True,
        "directly_downstream": list(graph.successors(tag)),
        "all_affected": affected,
        "safety_functions_affected": safety_hit,
    }


def candidate_causes(graph: nx.DiGraph, tag: str) -> list:
    """Upstream traversal: components that could STRUCTURALLY be the origin of a
    symptom seen at `tag`. Narrows the search space - it does NOT rank by
    probability (that needs failure rates + live data, not on the drawing).
    """
    if tag not in graph:
        return []
    return list(nx.ancestors(graph, tag))


# Typical failure modes by instrument/equipment type. Generic engineering
# knowledge shown as prompts for the engineer - not drawing-specific.
FAILURE_MODES = {
    "PT": ["signal drift", "stuck reading", "signal loss", "impulse line blocked"],
    "PI": ["drift", "stuck reading"],
    "PDT": ["drift", "impulse line blocked", "signal loss"],
    "PDI": ["drift", "stuck reading"],
    "TT": ["drift", "signal loss", "sensor detached"],
    "TI": ["drift", "signal loss"],
    "LT": ["drift", "stuck", "false level", "signal loss"],
    "LSH": ["false trip", "fails to trip", "stuck"],
    "LSL": ["false trip", "fails to trip", "stuck"],
    "FT": ["drift", "blocked element", "signal loss"],
    "FE": ["blocked / fouled element", "erosion"],
    "XV": ["fails to close", "fails to open", "seat leak", "slow stroke"],
    "FV": ["sticks", "wrong position", "actuator fault"],
    "PV": ["sticks", "wrong position", "actuator fault"],
    "PSV": ["premature lift", "fails to lift", "seat leak"],
    "HS": ["wrong position", "no command"],
    "PIC": ["wrong output", "tuning drift", "mode stuck"],
    "LIC": ["wrong output", "tuning drift", "mode stuck"],
    "FIC": ["wrong output", "tuning drift", "mode stuck"],
    "ZS": ["false position feedback", "no feedback"],
    "ZL": ["false position feedback", "no feedback"],
    "KA": ["trip", "reduced performance", "seal failure", "surge"],
    "PA": ["trip", "reduced performance", "seal failure", "cavitation"],
}


def failure_modes(type_code: str) -> list:
    return FAILURE_MODES.get(type_code, ["malfunction / signal fault"])


def failure_map(graph: nx.DiGraph, objects) -> dict:
    """Precompute a failure view for every tag (for the interactive dashboard)."""
    by_tag = {o.tag: o for o in objects}
    out = {}
    for tag in graph.nodes:
        fp = failure_propagation(graph, tag)
        o = by_tag.get(tag)
        out[tag] = {
            "category": o.category if o else "other",
            "modes": failure_modes(o.type_code) if o else failure_modes(""),
            "downstream": fp["all_affected"],
            "safety": fp["safety_functions_affected"],
            "upstream": candidate_causes(graph, tag),
        }
    return out