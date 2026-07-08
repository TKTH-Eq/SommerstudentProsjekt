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