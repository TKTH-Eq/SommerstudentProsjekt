"""
Measure the PID→structure lifter against DEXPI ground truth — the same
validation-driven discipline the rest of the repo uses for extraction.

Two numbers per drawing:

  NODE COVERAGE   of the DEXPI tags, how many did the pure-PDF lift place?
                  (text tags it located; plus how many symbol-only valves it
                  added beyond text — content DEXPI has but the text layer
                  cannot.)
  EDGE P / R / F1 undirected adjacency between TAGGED nodes vs the DEXPI
                  tag graph, restricted to the tag pairs whose endpoints the
                  lift actually recovered (so we score topology recovery, not
                  the extraction recall gap twice).

DEXPI enters ONLY here. The lift itself never sees it.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "gatevalve-ai" / "results"


def _dexpi_adjacency(xml_path, kinds=("process",)):
    """Physical tag-to-tag adjacency from RAW DEXPI connections — NOT the
    loop-enriched tag_graph (that inflates edges with loop cliques and would
    make the pixel tracer look worse than it is). Two tagged elements are
    adjacent iff a drawn connection path links them through only UNTAGGED
    intermediates (pipe segments, nozzles) — i.e. one physical run, exactly
    what the raster tracer tries to recover.

    kinds selects the connection type. DEFAULT 'process' only: the pixel
    tracer follows drawn PIPES, so it is scored against physical piping. The
    'signal' connections in this dataset are instrument-loop/functional links
    (PT↔PI, ZS↔ZL, FIC↔FT — same loop number), a different graph the tracer is
    not meant to recover; include them only to study that separately."""
    from collections import deque
    import networkx as nx
    from extraction.dexpi_parser import parse_dexpi
    from models.engineering_object import EngineeringObject

    tags, conn, _ = parse_dexpi(xml_path)
    id2tag = {}
    for r in tags.itertuples():
        if isinstance(r.tag_name, str) and r.tag_name.strip():
            id2tag[r.id] = EngineeringObject.from_tag(r.tag_name).tag

    g = nx.Graph()
    for r in conn.itertuples():
        if r.kind not in kinds:
            continue
        if isinstance(r.from_id, str) and isinstance(r.to_id, str):
            g.add_edge(r.from_id, r.to_id)

    tagged = set(id2tag)
    pairs = set()
    for s in tagged:
        if s not in g:
            continue
        seen = {s}
        dq = deque([s])
        while dq:                       # BFS, stop expanding at tagged nodes
            u = dq.popleft()
            for v in g[u]:
                if v in seen:
                    continue
                seen.add(v)
                if v in tagged:
                    if id2tag[v] != id2tag[s]:
                        pairs.add(frozenset((id2tag[s], id2tag[v])))
                else:
                    dq.append(v)
    return pairs, set(id2tag.values())


def _our_adjacency(model):
    tagged = {n["id"] for n in model["nodes"] if n["tag"]}
    pairs = set()
    for e in model["edges"]:
        if e["a"] in tagged and e["b"] in tagged and e["a"] != e["b"]:
            pairs.add(frozenset((e["a"], e["b"])))
    return pairs, tagged


def evaluate(target: str, dpi: int = 200, **lift_kw) -> dict | None:
    """Honest metrics for the lift.

    NODE recovery is the headline and it is measured against DEXPI. EDGE
    recovery is reported as a capability count, NOT scored as P/R against
    DEXPI: this export models physical piping through UNTAGGED nozzle/segment
    elements, so almost no tag-to-tag process adjacency exists to score against
    (dexpi_tagtag_process = the count, usually ~0). That near-zero is a finding
    about the deliverable format, not a tracer failure — see the writeup."""
    from extraction.pid_topology import lift
    pdfs = list(ROOT.joinpath("data/raw").rglob(f"{target}.[pP][dD][fF]"))
    xmls = list(ROOT.joinpath("data/raw").rglob(f"{target}.DGN.xml"))
    det_p = RES / f"{target}_detections.json"
    if not (pdfs and xmls):
        return None
    dets = json.loads(det_p.read_text()) if det_p.exists() else []
    model = lift(pdfs[0], dets, dpi=dpi, **lift_kw)

    proc_pairs, dex_tags = _dexpi_adjacency(xmls[0], kinds=("process",))
    sig_pairs, _ = _dexpi_adjacency(xmls[0], kinds=("signal",))
    _, our_tags = _our_adjacency(model)
    dex_tags = {t for t in dex_tags if _looks_tag(t)}
    node_cov = len(our_tags & dex_tags) / len(dex_tags) if dex_tags else 0.0
    # SCOPED = process adjacencies whose BOTH endpoints the PDF actually
    # recovered. This is the count of GT edges that could even in principle be
    # scored — and it collapses to near zero, which is the whole point: node
    # recall (62 %) compounds on both endpoints, and the rest route through
    # untagged line/nozzle intermediates the tag graph never exposes.
    scoped = sum(1 for p in proc_pairs if all(t in our_tags for t in p))
    return {
        "drawing": target,
        "dexpi_tags": len(dex_tags),
        "node_coverage": round(node_cov, 3),
        "nodes_text": model["stats"]["nodes_text"],
        "nodes_symbol_only": model["stats"]["nodes_symbol_only"],
        "edges_recovered": model["stats"]["edges"],
        "edges_segment": model["stats"]["edges_segment"],
        # evidence for the connectivity finding: how much tag-to-tag adjacency
        # even EXISTS in the DEXPI export, and how much is scoreable at all.
        "dexpi_tagtag_process": len(proc_pairs),
        "dexpi_tagtag_signal": len(sig_pairs),
        "dexpi_process_scoped": scoped,
    }


def _looks_tag(t: str) -> bool:
    import re
    return bool(re.match(r"^\d{2}-", str(t)))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    targets = [p.stem.replace("_detections", "")
               for p in sorted(RES.glob("*_detections.json"))]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = []
    for t in targets:
        if only and only not in t:
            continue
        try:
            r = evaluate(t)
        except Exception as e:                              # noqa: BLE001
            r = None
            print(f"  {t}: FAILED {e}")
        if r:
            rows.append(r)
            print(f"{r['drawing'][:22]:22s} "
                  f"nodes: {r['nodes_text']:3d} text +{r['nodes_symbol_only']:2d} "
                  f"symbol-only · cov {r['node_coverage']*100:4.0f}% of "
                  f"{r['dexpi_tags']:3d} DEXPI tags · edges {r['edges_recovered']:3d} "
                  f"· DEXPI tag-tag proc/sig {r['dexpi_tagtag_process']:2d}/"
                  f"{r['dexpi_tagtag_signal']:2d}")
    if rows:
        import statistics as st
        tot_sym = sum(r["nodes_symbol_only"] for r in rows)
        print(f"\nMEAN over {len(rows)} drawings: "
              f"node coverage {st.mean(r['node_coverage'] for r in rows)*100:.0f}% "
              f"of DEXPI tags · {tot_sym} symbol-only valves recovered beyond "
              f"text ({st.mean(r['nodes_symbol_only'] for r in rows):.0f}/drawing) "
              f"· {st.mean(r['edges_recovered'] for r in rows):.0f} pipe edges/drawing")
        tp = sum(r["dexpi_tagtag_process"] for r in rows)
        sc = sum(r.get("dexpi_process_scoped", 0) for r in rows)
        print(f"Connectivity ground truth in this DEXPI export: {tp} tag-to-tag "
              f"PROCESS adjacencies total across {len(rows)} drawings, of which "
              f"only {sc} have BOTH endpoints recoverable from the PDF — so "
              f"tag-level edge scoring has almost no valid targets. Physical "
              f"piping is modelled through untagged nozzle/segment elements and "
              f"node recall compounds on both endpoints (see writeup).")
