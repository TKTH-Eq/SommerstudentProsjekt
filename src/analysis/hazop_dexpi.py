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


def load_dexpi_model(xml_path: Path,
                     cap: int | None = None) -> dict:
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

    # nearest-anchor partition: ONE simultaneous BFS from all anchors, each
    # element joining its closest equipment — a proper partition even when
    # the piping between anchors is fully connected. (The old per-anchor
    # flood only stopped at other anchors, so a lone anchor — or none —
    # swallowed the whole drawing into one group.)
    from collections import deque
    section_members = defaultdict(set)        # node name -> set of tags
    claimed = set()
    owner = {}
    dq = deque()
    for aid in sorted(anchors, key=lambda a: anchors[a]):
        if isinstance(equip.set_index("id").tag_name.get(aid), str):
            section_members[anchors[aid]].add(id2norm.get(aid, ""))
        if aid in gund:
            owner[aid] = aid
            dq.append(aid)
    while dq:
        n = dq.popleft()
        for nb in gund.neighbors(n):
            if nb in owner or nb in anchors:
                continue
            owner[nb] = owner[n]
            dq.append(nb)
    for n, aid in owner.items():
        if n in id2norm and n not in anchors:
            section_members[anchors[aid]].add(id2norm[n])
            claimed.add(n)

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

    # quality gate 1: NO usable anchors — fall back entirely to
    # CONTIGUOUS LOOP GROUPS (functional loops merged along actual
    # tag-graph connectivity, size-capped).
    _cap = cap if cap and cap >= 10 else SECTION_CAP
    method = "equipment-anchored"
    if len(sections) < 2:
        fb = _loop_group_sections(objects, tg, cap=_cap)
        if len(fb) > len(sections):
            sections = fb
            method = ("loop groups (fallback — too few usable "
                      "equipment anchors in the export)")
    else:
        # quality gate 2: a few anchors can still swallow half the drawing
        # each (e.g. 2 anchors — 86 + 83 tags). An 80-tag "section" is
        # not a HAZOP node. Subdivide oversized anchor sections into loop
        # groups WITHIN the anchor, keeping the anchor name as prefix, so
        # locality is preserved and the split is visible.
        sections, n_split = _cap_sections(sections, tg, cap=_cap)
        if n_split:
            method += (f" · {n_split} oversized section(s) subdivided "
                       f"by loop groups (cap {_cap})")

    return {
        "objects": list(objects.values()),
        "tag_graph": tg,
        "sections": sections,
        "stats": {"tagged_elements": len(objects),
                  "connections": len(conn_df),
                  "tag_edges": tg.number_of_edges(),
                  "equipment_anchors": len(anchors),
                  "sections": len(sections),
                  "section_method": method},
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

def _loop_group_sections(objects: dict, tg, cap: int = 40) -> dict:
    """Fallback node basis when equipment anchors are missing or too
    coarse: merge functional loops that are DIRECTLY CONNECTED in the tag
    graph into contiguous groups, packed along a BFS order and size-capped
    so no group degenerates into "the whole drawing". Deterministic.
    Better than single loops (cross-loop consequences stay inside a
    node), honest about approximating an engineer's section cut."""
    from collections import defaultdict as _dd
    loops = _dd(list)
    for o in objects.values():
        loops[getattr(o, "loop", None) or o.tag].append(o)
    lg = nx.Graph()
    lg.add_nodes_from(loops)
    for u, v in tg.edges():
        lu = getattr(objects.get(u), "loop", None) or u
        lv = getattr(objects.get(v), "loop", None) or v
        if lu != lv and lu in loops and lv in loops:
            lg.add_edge(lu, lv)
    sections, k = {}, 0

    def _emit(chunk):
        nonlocal k
        ms = [o for lp in chunk for o in loops[lp]]
        if len(ms) >= 2:
            k += 1
            label = ", ".join(str(c) for c in chunk[:4]) + \
                ("\u2026" if len(chunk) > 4 else "")
            sections[f"loop group {k} ({label})"] = ms

    comps = sorted(nx.connected_components(lg),
                   key=lambda c: (-len(c), sorted(map(str, c))[0]))
    for comp in comps:
        start_s = sorted(map(str, comp))[0]
        start = next(c for c in comp if str(c) == start_s)
        order = list(nx.bfs_tree(lg.subgraph(comp), start))
        chunk, size = [], 0
        for lp in order:
            n = len(loops[lp])
            if chunk and size + n > cap:
                _emit(chunk)
                chunk, size = [], 0
            chunk.append(lp)
            size += n
        _emit(chunk)
    return sections

SECTION_CAP = 40          # max tags per HAZOP node before subdivision


def _cap_sections(sections: dict, tg, cap: int = SECTION_CAP):
    """Subdivide any section larger than `cap` into contiguous loop groups
    WITHIN that section (anchor name kept as prefix). Returns
    (new_sections, n_subdivided). Sections at or under the cap pass
    through untouched."""
    out, n_split = {}, 0
    for name, ms in sections.items():
        if len(ms) <= cap:
            out[name] = ms
            continue
        sub_obj = {o.tag: o for o in ms}
        subs = _loop_group_sections(sub_obj, tg.subgraph(sub_obj), cap=cap)
        if len(subs) <= 1:
            out[name] = ms
            continue
        n_split += 1
        for i, (k2, ms2) in enumerate(subs.items(), 1):
            lab = k2.split("(", 1)[1].rstrip(")") if "(" in k2 else str(i)
            out[f"{name} · part {i} ({lab})"] = ms2
    return out, n_split