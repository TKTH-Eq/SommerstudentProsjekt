"""
HAZOP nodes from DEXPI connectivity — the "better data" half of the
PDF-vs-DEXPI HAZOP comparison.

Where the PDF pipeline can only group tags into functional loops (shared
tag number), DEXPI states connectivity explicitly: <Connection FromID ToID>
plus semantic associations ("is located in", "is a part of", ...). That is
enough to build something much closer to REAL HAZOP nodes:

  SECTION     Everything reachable from one equipment item (pump, heat
              exchanger, vessel) through process/signal connections and
              location associations, stopping at the next equipment item.
              This mirrors how a HAZOP chair cuts a P&ID into nodes:
              equipment-anchored process sections.

  MEMBERS     All TAGGED elements in the section: instruments, valves,
              piping components — the population the worksheet machinery
              (analysis/hazop_prep.py) needs.

  CONSEQUENCE The tag-to-tag directed graph (untagged intermediates
              contracted away) gives real cross-section downstream
              propagation — the thing the loop-based PDF graph cannot do.

The worksheet itself is built by hazop_prep.build_worksheet(nodes=...):
same columns, same guidewords, same safeguard filtering — only the node
quality differs. That is the point of the demo.

Honest limits: sections from graph reachability approximate but do not
replace an engineer's node cut (no design-intent knowledge); drawings where
Semantum's export has few tag-to-tag connections yield coarse sections; and
untagged equipment is anchored by its class name (Pump, HeatExchanger).
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

if __name__ == "__main__" and __package__ is None:      # direct run support
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction.dexpi_parser import parse_dexpi
from models.engineering_object import EngineeringObject

# associations that mean "these two IDs belong together physically/logically"
_MEMBERSHIP_ASSOCS = {
    "is located in", "is the location of",
    "is a part of", "is a collection including",
    "fulfills", "is fulfilled by",
    "is logical start of", "is logical end of",
    "has logical start", "has logical end",
}

# number-first tag form used on Huldra (e.g. 27-4561PV), which
# EngineeringObject's type-first regex does not match
_NUMFIRST = re.compile(r"^(\d{2})-(\d{3,4})([A-Z]{1,4})$")


def _to_object(tag: str, source: str) -> EngineeringObject:
    """EngineeringObject from a DEXPI tag name, handling number-first tags."""
    o = EngineeringObject.from_tag(tag, source=source)
    if not o.type_code:
        m = _NUMFIRST.match(tag.strip().upper())
        if m:
            system, num, tc = m.groups()
            from config import categorise
            return EngineeringObject(tag=o.tag, system=system, type_code=tc,
                                     number=num, category=categorise(tc),
                                     source=source)
    return o


def load_dexpi_model(xml_path: Path) -> dict:
    """Parse one DEXPI file into everything the HAZOP worksheet needs.

    Returns {objects, tag_graph, sections, stats}:
      objects   [EngineeringObject]  — every tagged element
      tag_graph nx.DiGraph over tags — real directed connectivity
                (untagged intermediates contracted), for consequences
      sections  {node_name: [EngineeringObject]} — equipment-anchored
                HAZOP node candidates
    """
    tags_df, conn_df, assoc_df = parse_dexpi(xml_path)
    source = xml_path.stem.replace(".DGN", "")

    # Nozzle tags (N1, N2, ...) repeat per equipment item and line-number tags
    # repeat per segment — both would collide as graph keys and neither fits
    # the instrument/valve worksheet machinery. They stay in the ID graphs as
    # untagged pass-through elements instead.
    _SKIP = {"nozzle", "piping_segment", "piping_system",
             "pipe_off_page", "signal_off_page"}
    named = tags_df[tags_df.tag_name.notna() & ~tags_df.category.isin(_SKIP)]
    id2tag = dict(zip(named.id, named.tag_name))

    # ---- containment: child elements belong to their XML parent -----------
    # Connections reference nozzle/segment IDs, but a nozzle is a CHILD of its
    # equipment in the XML — without parent-child edges, equipment is
    # unreachable and every section ends up unanchored. Only PHYSICAL parents
    # count: linking through document containers (PlantModel, Drawing) would
    # merge the whole file into one section.
    _PHYS_PARENTS = {"Equipment", "ActuatingSystem", "PipingNetworkSegment",
                     "PipingNetworkSystem", "ProcessInstrumentationFunction",
                     "ActuatingFunction", "InstrumentationLoopFunction"}
    containment: list[tuple[str, str]] = []
    import xml.etree.ElementTree as ET

    def _walk(el, parent_id, parent_kind):
        eid = el.get("ID")
        if eid and parent_id and parent_kind in _PHYS_PARENTS:
            containment.append((parent_id, eid))
        if eid:
            parent_id, parent_kind = eid, el.tag
        for ch in el:
            _walk(ch, parent_id, parent_kind)

    _walk(ET.parse(xml_path).getroot(), None, None)

    # ---- objects -----------------------------------------------------------
    objects = {}
    for t in id2tag.values():
        o = _to_object(t, source)
        objects[o.tag] = o
    id2norm = {i: _to_object(t, source).tag for i, t in id2tag.items()}

    # ---- ID-level graphs ---------------------------------------------------
    gdir = nx.DiGraph()                      # directed, for flow direction
    for r in conn_df.itertuples():
        if r.from_id and r.to_id:
            gdir.add_edge(r.from_id, r.to_id)
    # containment both ways in the directed graph: flow passes THROUGH an
    # equipment item via its nozzles (pipe -> nozzle -> equipment -> nozzle)
    for p, c in containment:
        gdir.add_edge(p, c)
        gdir.add_edge(c, p)

    # membership graph: PROCESS connections + containment + associations.
    # Signal connections are deliberately excluded here — a controller wired
    # to a section belongs to its own location, not to every section it
    # signals to. Signals still drive consequences via the directed graph.
    gund = nx.Graph()
    for r in conn_df.itertuples():
        if r.kind == "process" and r.from_id and r.to_id:
            gund.add_edge(r.from_id, r.to_id)
    for p, c in containment:
        gund.add_edge(p, c)
    if len(assoc_df):
        for r in assoc_df.itertuples():
            if r.assoc_type in _MEMBERSHIP_ASSOCS and r.source_id and r.target_id:
                gund.add_edge(r.source_id, r.target_id)

    # ---- tag-to-tag directed graph (contract untagged intermediates) ------
    tg = nx.DiGraph()
    for o in objects.values():
        tg.add_node(o.tag, category=o.category, type_code=o.type_code,
                    loop=o.loop, source=o.source)
    tagged_ids = set(id2norm)
    for u in tagged_ids:
        if u not in gdir:
            continue
        seen, stack = set(), list(gdir.successors(u))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in tagged_ids:
                if id2norm[u] != id2norm[n]:
                    tg.add_edge(id2norm[u], id2norm[n])
            else:
                stack.extend(gdir.successors(n))

    # ---- equipment-anchored sections --------------------------------------
    equip = tags_df[tags_df.category == "equipment"]
    anchors = {}                              # id -> node name
    for r in equip.itertuples():
        name = r.tag_name if isinstance(r.tag_name, str) else \
            f"{r.component_class} ({str(r.id)[-4:]})"
        anchors[r.id] = f"{name}-section"

    section_members = defaultdict(set)        # node name -> set of tags
    claimed = set()
    for aid, name in anchors.items():
        if isinstance(equip.set_index("id").tag_name.get(aid), str):
            section_members[name].add(id2norm.get(aid, ""))
        if aid not in gund:
            continue
        seen, stack = {aid}, list(gund.neighbors(aid))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in anchors and n != aid:      # stop at next equipment
                continue
            if n in id2norm:
                section_members[name].add(id2norm[n])
                claimed.add(n)
            stack.extend(gund.neighbors(n))

    # leftovers: tagged elements not reached from any equipment, grouped by
    # connected component so related items stay together. Truly isolated tags
    # (no connectivity at all) are left out of the node list — they appear in
    # the tag register but cannot form a meaningful HAZOP node.
    left = [i for i in tagged_ids if i not in claimed and i not in anchors]
    if left:
        sub = gund.subgraph([n for n in gund if n in set(left)]).copy()
        comps = sorted(nx.connected_components(sub), key=len, reverse=True)
        k = 0
        for comp in comps:
            if len(comp) < 2:
                continue
            k += 1
            for i in comp:
                section_members[f"unanchored-section-{k}"].add(id2norm[i])

    sections = {}
    for name, tags in sorted(section_members.items()):
        ms = [objects[t] for t in sorted(tags) if t in objects]
        if len(ms) >= 2:
            sections[name] = ms

    return {
        "objects": list(objects.values()),
        "tag_graph": tg,
        "sections": sections,
        "stats": {"tagged_elements": len(objects),
                  "connections": len(conn_df),
                  "tag_edges": tg.number_of_edges(),
                  "equipment_anchors": len(anchors),
                  "sections": len(sections)},
    }


if __name__ == "__main__":
    # quick check:  python src/analysis/hazop_dexpi.py [path-to-DGN.xml]
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from analysis.hazop_prep import build_worksheet

    default = next(Path("data/raw").rglob("*HO27-P-_E-002*.DGN.xml"), None)
    xml = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    m = load_dexpi_model(xml)
    print(f"{xml.name}: {m['stats']}\n")
    for name, ms in m["sections"].items():
        print(f"  {name}: {len(ms)} members "
              f"({sum(1 for o in ms if o.type_code)} typed)")
    rows = build_worksheet(m["tag_graph"], m["objects"], nodes=m["sections"])
    print(f"\n{len(rows)} worksheet rows")
    for r in rows[:4]:
        print(f"\n[{r['node']}] {r['deviation']}\n"
              f"   causes:      {r['causes']}\n"
              f"   consequence: {r['consequences'][:160]}\n"
              f"   safeguards:  {r['safeguards']}")