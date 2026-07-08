"""Complexity indicators and drawing-quality flags."""
from __future__ import annotations
import networkx as nx
from collections import Counter


def compute_kpis(graph: nx.DiGraph, objects) -> dict:
    cats = Counter(o.category for o in objects)
    isolated = list(nx.isolates(graph))
    # most-connected nodes = single points that many things depend on
    deg = sorted(graph.degree, key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "components": len(objects),
        "by_category": dict(cats),
        "connections": graph.number_of_edges(),
        "functional_loops": len({o.loop for o in objects}),
        "isolated_tags": isolated,
        "unparsed_tags": [o.tag for o in objects if not o.type_code],
        "most_connected": [f"{n} ({d})" for n, d in deg],
    }


def quality_flags(objects) -> list[str]:
    flags = []
    unparsed = [o.tag for o in objects if not o.type_code]
    if unparsed:
        flags.append(f"{len(unparsed)} tag(s) could not be parsed to type+number "
                     f"(possible extraction noise): {unparsed[:8]}")
    # near-duplicate tags from leading-zero variants (e.g. LSL548 vs LSL0548).
    # A/B/C redundancy legs share the same number and are NOT flagged.
    seen = {}
    for o in objects:
        if not o.number:
            continue
        key = (o.type_code, o.number.lstrip("0"))
        seen.setdefault(key, set()).add(o.number)
    for (tc, _), numbers in seen.items():
        if len(numbers) > 1:                       # differing raw numbers -> artefact
            variants = sorted(f"{tc}{n}" for n in numbers)
            flags.append(f"near-duplicate tags (leading-zero variant), verify: {variants}")
    return flags