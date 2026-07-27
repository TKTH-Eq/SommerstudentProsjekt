"""
PID → structure lifter: recover a machine-readable component + connectivity
model from a legacy PDF P&ID, using ONLY PDF-derived inputs.

This is the constructive answer to the project's format argument. The rest of
the repo *measures* what PDF loses (55 % recall, symbol-only tags, loop-based
topology that assumes connections). This module tries to *manufacture* the
missing structure from the drawing itself:

  nodes  = text-extracted tags (instruments/equipment)   [extraction.tag_*]
         + CNN-detected valve symbols the text layer never tagged  [gatevalve-ai]
  edges  = pipe runs traced off the raster: ink minus text minus symbols minus
           border, connected-component labelled; components on the same pipe
           branch are connected.

DEXPI is used NOWHERE here — only in eval_topology.py, as ground truth. Feeding
DEXPI back in would defeat the purpose. The output is a "DEXPI-lite" structure
(components + connections) that a downstream tool could consume: the legacy
drawing, made machine-readable, with a measured accuracy attached.

Honest limits (measured in eval_topology.py, reported in every run):
  * line crossings with no junction dot merge two pipe runs into one component,
    so a pipe touching >2 nodes is flagged a JUNCTION (lower-confidence edges);
  * a pipe drawn purely as a symbol-to-symbol abutment (no gap) is missed;
  * connectivity is undirected — flow direction is not recovered from pixels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

# CNN classes that are line valves worth lifting as symbol-only components.
_VALVE_CLASSES = {
    "gate_open", "gate_closed", "ball_valve", "ball_open", "ball_closed",
    "globe_valve", "butterfly_valve", "check_valve", "other_valve",
}
# type codes that ARE valves — a tagged one of these should be anchored to the
# CNN symbol centre (where the pipe attaches), not left on its tag text.
_VALVE_TYPES = {"XV", "ESV", "PV", "LV", "FV", "HV", "TV", "PCV", "FCV", "LCV",
                "TCV", "BV", "GV", "CV"}


@dataclass
class Node:
    id: str
    kind: str                 # type_code (PT, XV, …) or CNN class (ball_valve…)
    tag: str | None           # real tag if text-located, else None (symbol-only)
    x: float                  # centre in render pixels
    y: float
    source: str               # "text" | "cnn"


# --------------------------------------------------------------------------- IO
def render_gray(pdf_path: str | Path, dpi: int) -> np.ndarray:
    import pypdfium2 as pdfium
    img = pdfium.PdfDocument(str(pdf_path))[0].render(scale=dpi / 72.0).to_numpy()
    if img.ndim == 3:                              # RGB(A) -> luminance
        img = (0.299 * img[..., 0] + 0.587 * img[..., 1]
               + 0.114 * img[..., 2]).astype(np.uint8)
    return img


def _words(pdf_path: str | Path, dpi: int) -> list[tuple[int, int, int, int]]:
    """All text word boxes in render pixels (to erase text from the pipe mask)."""
    import pdfplumber
    s = dpi / 72.0
    out = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for w in pdf.pages[0].extract_words():
                out.append((int(w["x0"] * s), int(w["top"] * s),
                            int(w["x1"] * s), int(w["bottom"] * s)))
    except Exception:                                       # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------- node build
def build_nodes(pdf_path, dpi, detections, dpi_scale=1.0,
                tag_match_px=90.0, anchor_valves=True) -> list[Node]:
    """Text tags (located) + CNN valves that no text tag explains. PURE PDF.

    anchor_valves: a text-tagged VALVE is snapped to the centre of the nearest
    CNN valve detection — the tag text sits beside the symbol, but the pipe
    attaches at the SYMBOL, so tracing must start there. Instruments keep their
    text position (their tag sits inside the bubble the pipe/signal meets, and
    the CNN does not detect bubbles)."""
    from extraction.tag_extractor import extract_tags, create_objects
    from extraction.tag_locator import locate_tags

    tags = sorted(extract_tags(str(pdf_path)))
    objs = {o.tag: o for o in create_objects(tags, "P&ID")}
    boxes = locate_tags(pdf_path, tags, dpi=dpi)

    nodes: list[Node] = []
    tag_centre_idx: list[tuple[float, float, int]] = []   # (cx, cy, node index)
    for tag, bs in boxes.items():
        x, y, w, h = bs[0]
        cx, cy = x + w / 2, y + h / 2
        tag_centre_idx.append((cx, cy, len(nodes)))
        nodes.append(Node(id=tag, kind=(objs[tag].type_code or "?"),
                          tag=tag, x=cx, y=cy, source="text"))

    n_sym = 0
    for d in detections or []:
        if d.get("cls") not in _VALVE_CLASSES:
            continue
        if d.get("tier", "sikker") != "sikker":
            continue
        x0, y0, x1, y1 = d["bbox_orig"]
        cx = (x0 + x1) / 2 * dpi_scale
        cy = (y0 + y1) / 2 * dpi_scale
        # nearest text tag to this detection
        near = None
        best = tag_match_px ** 2
        for tx, ty, idx in tag_centre_idx:
            dd = (cx - tx) ** 2 + (cy - ty) ** 2
            if dd <= best:
                best, near = dd, idx
        if near is not None:
            # a text tag explains this symbol. If that tag is a VALVE, snap it
            # to the symbol centre (pipe attaches here, not at the label).
            nd = nodes[near]
            if anchor_valves and nd.tag and objs[nd.tag].type_code in _VALVE_TYPES \
                    and nd.source == "text":
                nd.x, nd.y, nd.source = cx, cy, "text+cnn"
            continue
        n_sym += 1
        nodes.append(Node(id=f"sym{n_sym}:{d['cls']}", kind=d["cls"],
                          tag=None, x=cx, y=cy, source="cnn"))
    return nodes


# ------------------------------------------------------------------- pipe mask
def pipe_mask(gray: np.ndarray, word_boxes, node_boxes,
              erase_pad: int = 3) -> np.ndarray:
    """Binary pipe network: ink, minus text, minus symbols, minus the border /
    title block (long full-span rules and the outer margin)."""
    H, W = gray.shape
    ink = gray < 128
    # erase the outer frame + long spanning rules (borders, title-block lines)
    row_fill = ink.mean(axis=1)
    col_fill = ink.mean(axis=0)
    ink[row_fill > 0.5, :] = False
    ink[:, col_fill > 0.5] = False
    m = int(0.02 * min(H, W))                          # trim a thin margin
    ink[:m, :] = ink[-m:, :] = ink[:, :m] = ink[:, -m:] = False

    def erase(boxes):
        for (x0, y0, x1, y1) in boxes:
            a = max(int(min(x0, x1)) - erase_pad, 0)
            b = max(int(min(y0, y1)) - erase_pad, 0)
            c = min(int(max(x0, x1)) + erase_pad, W)
            d = min(int(max(y0, y1)) + erase_pad, H)
            ink[b:d, a:c] = False

    erase(word_boxes)
    erase(node_boxes)
    return ink


# ---------------------------------------------------------------- connectivity
def trace_edges(mask: np.ndarray, nodes: list[Node], box_half: int = 26,
                stub_pad: int = 10, min_pipe_area: int = 40,
                dilate_iter: int = 3):
    """Connect nodes that sit on the same pipe branch.

    Each node gets a small square footprint; we look for pipe-mask labels in a
    ring just outside it (the stubs leaving the symbol). Nodes sharing a pipe
    label are connected. A label touching exactly two nodes is a clean segment
    (high confidence); a label touching more is a junction/header (the pipe
    over-merge failure mode) and its edges are marked lower confidence.

    dilate_iter grows the pipe mask before labelling to bridge dashed lines and
    the small gaps left where text/symbols were erased — without it the network
    shatters into thousands of fragments and almost nothing connects.
    """
    from scipy import ndimage

    if dilate_iter:
        mask = ndimage.binary_dilation(mask, iterations=dilate_iter)
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
    if n == 0:
        return [], {"pipe_components": 0}
    sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    big = set(int(i) for i in np.arange(1, n + 1) if sizes[i - 1] >= min_pipe_area)

    H, W = mask.shape
    label_to_nodes: dict[int, set[int]] = {}
    node_labels: list[set[int]] = []
    for idx, nd in enumerate(nodes):
        x0 = max(int(nd.x) - box_half - stub_pad, 0)
        y0 = max(int(nd.y) - box_half - stub_pad, 0)
        x1 = min(int(nd.x) + box_half + stub_pad, W)
        y1 = min(int(nd.y) + box_half + stub_pad, H)
        ring = lab[y0:y1, x0:x1]
        labs = {int(v) for v in np.unique(ring) if v and int(v) in big}
        node_labels.append(labs)
        for lb in labs:
            label_to_nodes.setdefault(lb, set()).add(idx)

    edges = []
    seen = set()
    for lb, members in label_to_nodes.items():
        if len(members) < 2:
            continue
        members = sorted(members)
        junction = len(members) > 2
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                key = (a, b)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"a": nodes[a].id, "b": nodes[b].id,
                              "kind": "junction" if junction else "segment"})
    return edges, {"pipe_components": int(n), "pipe_components_kept": len(big)}


# ---------------------------------------------------------------------- lift
def lift(pdf_path, detections, dpi: int = 200, dpi_scale: float = 1.0,
         dilate_iter: int = 3) -> dict:
    """Full pipeline → {nodes, edges, stats}. detections = cached CNN JSON."""
    gray = render_gray(pdf_path, dpi)
    nodes = build_nodes(pdf_path, dpi, detections, dpi_scale=dpi_scale)
    nb = [(n.x - 26, n.y - 26, n.x + 26, n.y + 26) for n in nodes]
    mask = pipe_mask(gray, _words(pdf_path, dpi), nb)
    edges, pstats = trace_edges(mask, nodes, dilate_iter=dilate_iter)

    deg: dict[str, int] = {}
    for e in edges:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    valves = [n for n in nodes if n.source in ("text+cnn", "cnn")]
    return {
        "drawing": Path(pdf_path).stem,
        "dpi": dpi,
        "nodes": [asdict(n) for n in nodes],
        "edges": edges,
        "stats": {
            "nodes": len(nodes),
            # tagged components (text label; valves anchored to the CNN symbol)
            "nodes_text": sum(1 for n in nodes if n.source in ("text", "text+cnn")),
            "nodes_anchored": sum(1 for n in nodes if n.source == "text+cnn"),
            "nodes_symbol_only": sum(1 for n in nodes if n.source == "cnn"),
            "edges": len(edges),
            "edges_segment": sum(1 for e in edges if e["kind"] == "segment"),
            "edges_junction": sum(1 for e in edges if e["kind"] == "junction"),
            # connectivity: how many components are actually wired into a pipe
            "nodes_connected": sum(1 for n in nodes if deg.get(n.id, 0) > 0),
            "valves_connected": sum(1 for n in valves if deg.get(n.id, 0) > 0),
            "valves_total": len(valves),
            **pstats,
        },
    }


# ------------------------------------------------------------------- exports
def to_json(model: dict) -> str:
    return json.dumps(model, ensure_ascii=False, indent=2)


def to_dexpi_lite(model: dict) -> str:
    """Illustrative DEXPI-lite XML (NOT schema-valid Proteus): shows the shape
    of the machine-readable deliverable — tagged components and connections —
    that the lift recovers from a flat PDF."""
    import xml.etree.ElementTree as ET
    root = ET.Element("PlantModel", attrib={
        "source": "pid_topology.lift", "drawing": model["drawing"],
        "note": "DEXPI-lite / illustrative — not schema-valid Proteus"})
    comps = ET.SubElement(root, "Components")
    for n in model["nodes"]:
        ET.SubElement(comps, "Component", attrib={
            "ID": n["id"], "Type": n["kind"],
            "TagName": n["tag"] or "", "Source": n["source"],
            "X": f"{n['x']:.0f}", "Y": f"{n['y']:.0f}"})
    conns = ET.SubElement(root, "Connections")
    for e in model["edges"]:
        ET.SubElement(conns, "Connection", attrib={
            "From": e["a"], "To": e["b"], "Kind": e["kind"]})
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    ROOT = Path(__file__).resolve().parents[2]
    RES = ROOT / "gatevalve-ai" / "results"
    target = sys.argv[1] if len(sys.argv) > 1 else "C025-V-HO27-P-_E-002-01"
    pdf = next(ROOT.joinpath("data/raw").rglob(f"{target}.[pP][dD][fF]"))
    dets_p = RES / f"{target}_detections.json"
    dets = json.loads(dets_p.read_text()) if dets_p.exists() else []
    model = lift(pdf, dets)
    print(json.dumps(model["stats"], indent=2))
