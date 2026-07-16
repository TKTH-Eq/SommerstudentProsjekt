"""
Plant model: stitch every DEXPI drawing into ONE dependency graph.

Why: every tool in this project — failure explorer, root cause, the alarm
shower with its AI brief — operates per drawing, because that is all a
document-centric world allows. But faults do not respect sheet boundaries.
This module builds the plant-wide graph that makes cross-drawing reasoning
possible, using two stitch mechanisms the structured data provides:

  SHARED LINE NUMBERS   the same piping-line tag (e.g. 4"-PV-274599-ED200-4)
                        appearing on two drawings IS the same physical line;
                        the tagged elements nearest to it on each sheet are
                        connected with kind="cross_drawing" edges.

  SHARED COMPONENT TAGS the same component tag on two drawings is the same
                        physical component; its nodes merge into one, which
                        fuses the per-drawing graphs at that point.

Direction across a line stitch is not stated in the export (off-page
connectors carry FlowIn/FlowOut but no names), so cross-drawing edges are
added BOTH ways and marked as such — reachability is preserved, direction
is approximate. That is a documentable limitation, and itself an input to
the minimum-requirement set: consistent line numbering and named off-page
references are what make a plant model cheap to build.

Everything downstream (failure_map, root_cause, control_room, the Streamlit
pages) takes an arbitrary graph, so the plant model plugs in unchanged —
same tools, whole plant.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

if __name__ == "__main__" and __package__ is None:      # direct run support
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction.dexpi_parser import parse_dexpi
from analysis.hazop_dexpi import load_dexpi_model

MAX_STITCH_TAGS = 3        # nearest tags per drawing-side of a line stitch
NEAR_HOPS = 4              # how far from a segment we look for tagged anchors


def _line_anchor_tags(xml_path: Path, tagged: set[str]) -> dict[str, list[str]]:
    """{line tag: [nearest component tags on this drawing]}.

    Uses the raw ID-level connection graph: from each piping segment that
    carries the line tag, walk outward a few hops and collect the first
    tagged elements met — the components that physically sit on that line.
    """
    tags_df, conn_df, _ = parse_dexpi(xml_path)
    id2tag = dict(zip(tags_df[tags_df.tag_name.notna()].id,
                      tags_df[tags_df.tag_name.notna()].tag_name))
    g = nx.Graph()
    for r in conn_df.itertuples():
        if r.from_id and r.to_id:
            g.add_edge(r.from_id, r.to_id)
    # containment: a segment's components are its CHILDREN in the XML —
    # connections alone never reference the segment ID itself (same lesson
    # as hazop_dexpi's section building)
    import xml.etree.ElementTree as ET
    _PHYS = {"Equipment", "ActuatingSystem", "PipingNetworkSegment",
             "PipingNetworkSystem", "ProcessInstrumentationFunction",
             "ActuatingFunction", "InstrumentationLoopFunction"}

    def _walk(el, pid, pkind):
        eid = el.get("ID")
        if eid and pid and pkind in _PHYS:
            g.add_edge(pid, eid)
        if eid:
            pid, pkind = eid, el.tag
        for ch in el:
            _walk(ch, pid, pkind)

    _walk(ET.parse(xml_path).getroot(), None, None)

    segs = tags_df[(tags_df.category == "piping_segment") & tags_df.tag_name.notna()]
    by_line: dict[str, list[str]] = defaultdict(list)
    for r in segs.itertuples():
        if r.id not in g:
            continue
        seen, frontier, found = {r.id}, [r.id], []
        for _ in range(NEAR_HOPS):
            nxt = []
            for n in frontier:
                for m in g.neighbors(n):
                    if m in seen:
                        continue
                    seen.add(m)
                    t = id2tag.get(m)
                    if t and t in tagged:
                        found.append(t)
                    else:
                        nxt.append(m)
            frontier = nxt
            if len(found) >= MAX_STITCH_TAGS:
                break
        for t in found[:MAX_STITCH_TAGS]:
            if t not in by_line[r.tag_name]:
                by_line[r.tag_name].append(t)
    return by_line


def build_plant_model(raw_dir: Path) -> dict:
    """Load every DEXPI file, merge on shared tags, stitch on shared lines.

    Returns {graph, objects, drawings_of, stitches, stats}:
      graph      nx.DiGraph over tags; cross-drawing edges have
                 kind="cross_drawing" and line=<line tag>
      objects    [EngineeringObject] — one per unique tag
      drawings_of {tag: [drawing stems]} — provenance for the UI
      stitches   [(line, drawing_a, drawing_b, tags_a, tags_b)]
    """
    files = sorted(Path(raw_dir).rglob("*.DGN.xml"))
    G = nx.DiGraph()
    objects: dict[str, object] = {}
    drawings_of: dict[str, list[str]] = defaultdict(list)
    line_anchors: dict[str, dict[str, list[str]]] = {}   # drawing -> line -> tags

    for x in files:
        stem = x.stem.replace(".DGN", "")
        m = load_dexpi_model(x)
        for o in m["objects"]:
            if o.tag not in objects:
                objects[o.tag] = o
            drawings_of[o.tag].append(stem)
        for n, data in m["tag_graph"].nodes(data=True):
            if n not in G:
                G.add_node(n, **data)
        for u, v in m["tag_graph"].edges():
            G.add_edge(u, v, kind="in_drawing", drawing=stem)
        line_anchors[stem] = _line_anchor_tags(x, {o.tag for o in m["objects"]})

    # ---- line-number stitches ----------------------------------------------
    stitches = []
    stems = list(line_anchors)
    for i, a in enumerate(stems):
        for b in stems[i + 1:]:
            for line in set(line_anchors[a]) & set(line_anchors[b]):
                ta, tb = line_anchors[a][line], line_anchors[b][line]
                if not ta or not tb:
                    continue
                stitches.append((line, a, b, ta, tb))
                for x1 in ta:
                    for x2 in tb:
                        if x1 == x2:
                            continue        # same component: already merged
                        G.add_edge(x1, x2, kind="cross_drawing", line=line)
                        G.add_edge(x2, x1, kind="cross_drawing", line=line)

    shared_tags = sum(1 for t, ds in drawings_of.items() if len(set(ds)) > 1)
    cross_edges = sum(1 for _, _, d in G.edges(data=True)
                      if d.get("kind") == "cross_drawing")
    return {
        "graph": G,
        "objects": list(objects.values()),
        "drawings_of": {t: sorted(set(ds)) for t, ds in drawings_of.items()},
        "stitches": stitches,
        "stats": {"drawings": len(files), "tags": len(objects),
                  "edges": G.number_of_edges(), "cross_edges": cross_edges,
                  "line_stitches": len(stitches), "shared_tags": shared_tags},
    }


if __name__ == "__main__":
    # quick check:  python src/analysis/plant_model.py [data/raw]
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")
    M = build_plant_model(raw)
    print("Anleggsmodell:", M["stats"], "\n")
    print("Eksempler på sømmer (linje: tegning A <-> tegning B):")
    for line, a, b, ta, tb in M["stitches"][:6]:
        print(f"  {line}\n    {a[-14:]}: {ta}\n    {b[-14:]}: {tb}")
    # finn en kaskade som faktisk krysser tegninger
    from analysis.control_room import scenario_order
    best = None
    for n in M["graph"].nodes:
        order = scenario_order(M["graph"], n)
        drawn = {d for t in order for d in M["drawings_of"].get(t, [])}
        if len(drawn) > 1 and (best is None or len(order) > len(best[1])):
            best = (n, order, drawn)
    if best:
        n, order, drawn = best
        print(f"\nStørste kryss-tegnings-kaskade: feil i {n} -> "
              f"{len(order)} alarmer over {len(drawn)} tegninger:")
        for d in sorted(drawn):
            print(f"  {d[-14:]}")