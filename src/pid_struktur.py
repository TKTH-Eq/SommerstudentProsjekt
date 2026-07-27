"""
src/pid_struktur.py — Streamlit page: PDF → structure lifter (visible demo).

Select a P&ID; the lifter reconstructs a structured component + connectivity
model from the PDF ALONE (text tags + CNN valve symbols + pipe runs traced off
the raster), overlays the recovered graph on the drawing, and offers the
machine-readable "DEXPI-lite" export. An optional panel measures it against
DEXPI ground truth and surfaces the connectivity finding.

Registered in nav_pages.py (NOT a pages/ folder). Command-line twins:
    python src/extraction/pid_topology.py <stem>
    python src/extraction/eval_topology.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import page_header
from extraction.pid_topology import lift, render_gray, to_json, to_dexpi_lite

try:
    from config import PID_DIR, ROOT
except Exception:                                                  # noqa: BLE001
    ROOT = Path(__file__).resolve().parents[1]
    PID_DIR = ROOT / "data" / "raw" / "P&ID"

RESULTS = ROOT / "gatevalve-ai" / "results"
_TEXT_COL = "#2d7dd2"        # text-extracted node
_SYM_COL = "#e67e22"         # CNN symbol-only valve (the recall-gap content)
_SEG_COL = (46, 204, 113)    # traced pipe segment (2 nodes)
_JCT_COL = (150, 150, 150)   # junction / header (>2 nodes)


# ------------------------------------------------------------- cached compute
@st.cache_data(show_spinner="Lifting structure from the PDF…")
def _lift_cached(pdf_str: str, dpi: int, det_path: str) -> dict:
    dets = (json.loads(Path(det_path).read_text(encoding="utf-8"))
            if det_path and Path(det_path).exists() else [])
    return lift(pdf_str, dets, dpi=dpi)


@st.cache_data(show_spinner=False)
def _base_rgb(pdf_str: str, dpi: int):
    gray = render_gray(pdf_str, dpi)
    return Image.fromarray(gray).convert("RGB")


@st.cache_data(show_spinner="Comparing against DEXPI…")
def _dexpi_report(xml_str: str, our_tags: tuple) -> dict:
    from extraction.eval_topology import _dexpi_adjacency, _looks_tag
    proc, dex_tags = _dexpi_adjacency(Path(xml_str), kinds=("process",))
    sig, _ = _dexpi_adjacency(Path(xml_str), kinds=("signal",))
    dex_tags = {t for t in dex_tags if _looks_tag(t)}
    our = set(our_tags)
    scoped = sum(1 for p in proc if all(t in our for t in p))
    cov = len(our & dex_tags) / len(dex_tags) if dex_tags else 0.0
    return {"dex_tags": len(dex_tags), "coverage": cov,
            "proc": len(proc), "sig": len(sig), "scoped": scoped}


def _overlay(base: Image.Image, model: dict) -> Image.Image:
    im = base.copy()
    d = ImageDraw.Draw(im)
    pos = {n["id"]: (n["x"], n["y"]) for n in model["nodes"]}
    for e in model["edges"]:
        a, b = pos.get(e["a"]), pos.get(e["b"])
        if a and b:
            col = _SEG_COL if e["kind"] == "segment" else _JCT_COL
            d.line([a, b], fill=col, width=3)
    r = 7
    for n in model["nodes"]:
        col = _SYM_COL if n["source"] == "cnn" else _TEXT_COL   # text/anchored=blue
        x, y = n["x"], n["y"]
        d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline="white")
    return im


# --------------------------------------------------------------------- page
page_header("PDF → structure",
            "Component inventory from a legacy PDF — topology attempt kept as a "
            "documented failure")
st.caption("Two halves, one works and one does not. ✅ **Component inventory** "
           "— pure-PDF recovers most tags PLUS the symbol-only valves the text "
           "layer cannot see, exported as a structured list. ❌ **Topology / "
           "edge tracing** — does NOT work on this data and was abandoned; going "
           "from a legacy PDF to a *connected* DEXPI model is not achievable "
           "with this approach. The graph overlay below is kept only to show the "
           "attempt (see PID_TO_STRUCTURE.md). A draft for review, not an "
           "authoritative source.")

drawings = sorted(p for p in Path(PID_DIR).rglob("*") if p.suffix.lower() == ".pdf")
if not drawings:
    st.error(f"Found no PDFs under {PID_DIR}.")
    st.stop()

c1, c2 = st.columns([4, 1])
with c1:
    choice = st.selectbox("Drawing", drawings, format_func=lambda p: p.name)
with c2:
    dpi = st.number_input("DPI", 150, 300, 200, step=50)

stem = choice.stem
det_p = RESULTS / f"{stem}_detections.json"
if not det_p.exists():
    st.info("No CNN detections cached for this drawing — the lift will use "
            "text tags only (no symbol-only valves). Run the **🔍 Drawing "
            "analysis** page on it first to add the CNN valve symbols.")

if st.button("Lift structure from the drawing", type="primary"):
    st.session_state["pid_lifted"] = stem

if st.session_state.get("pid_lifted") == stem:
    model = _lift_cached(str(choice), int(dpi),
                         str(det_p) if det_p.exists() else "")
    s = model["stats"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Components", s["nodes"])
    m2.metric("… text-tagged", s["nodes_text"])
    m3.metric("… symbol-only (CNN)", s["nodes_symbol_only"],
              help="Valve symbols with no readable tag — invisible to text "
                   "extraction, recovered by the CNN. This is the recall gap "
                   "being filled, not just measured.")
    m4.metric("Pipe edges traced", s["edges"],
              help=f"{s['edges_segment']} clean segments · "
                   f"{s['edges_junction']} junction/header")
    st.caption(f"🔌 {s['valves_connected']}/{s['valves_total']} valve symbols "
               f"wired into a pipe · {s.get('nodes_anchored', 0)} tagged valve(s) "
               f"anchored to their CNN symbol centre (rare on this export — "
               f"tagged on/off valves are sparse and their labels sit far from "
               f"the symbol; see PID_TO_STRUCTURE.md).")

    st.subheader("Pipe-tracing experiment (abandoned — not real topology)")
    st.warning(
        "⚠️ **Edge tracing does not work on this data and was abandoned.** The "
        "raster pipe-tracer cannot recover DEXPI-comparable connectivity — the "
        "lines below are the *attempt*, not verified topology, and should not be "
        "read as recovered pipe runs. Going from a legacy PDF to a *connected* "
        "DEXPI model is not achievable with this approach; see "
        "PID_TO_STRUCTURE.md. The working output of this page is the **component "
        "inventory and export** above/below, not the graph.")
    st.markdown(
        f"<span style='color:{_TEXT_COL};font-weight:700'>● text-tagged</span> "
        f"&nbsp; <span style='color:{_SYM_COL};font-weight:700'>● symbol-only "
        f"valve (CNN)</span> &nbsp; <span style='color:#2ecc71;font-weight:700'>"
        f"— pipe segment</span> &nbsp; <span style='color:#999;font-weight:700'>"
        f"— junction/header</span>", unsafe_allow_html=True)
    with st.spinner("Rendering overlay…"):
        base = _base_rgb(str(choice), int(dpi))
        st.image(_overlay(base, model), use_container_width=True)
    st.caption("Node positions come from the tag TEXT, not the symbol where "
               "pipes attach — the main reason physical tracing under-connects "
               "(see PID_TO_STRUCTURE.md, future work).")

    # ---- machine-readable export ------------------------------------------
    st.subheader("Machine-readable export")
    st.caption("The deliverable the lift manufactures from a flat PDF: "
               "components + connections. The XML is DEXPI-lite / illustrative "
               "— it shows the SHAPE, not a schema-valid Proteus import file.")
    e1, e2 = st.columns(2)
    e1.download_button("⬇️ Structure (JSON)", to_json(model).encode("utf-8"),
                       file_name=f"{stem}.structure.json",
                       mime="application/json")
    e2.download_button("⬇️ DEXPI-lite (XML)", to_dexpi_lite(model).encode("utf-8"),
                       file_name=f"{stem}.dexpi-lite.xml",
                       mime="application/xml")
    with st.expander("Components (table)"):
        st.dataframe(
            [{"id": n["id"], "type": n["kind"], "tag": n["tag"] or "—",
              "source": n["source"]} for n in model["nodes"]],
            use_container_width=True, hide_index=True)

    # ---- measured against DEXPI -------------------------------------------
    xmls = list(Path(PID_DIR).parent.rglob(f"{stem}.DGN.xml"))
    if xmls:
        st.subheader("Measured against DEXPI")
        our_tags = tuple(sorted(n["id"] for n in model["nodes"] if n["tag"]))
        rep = _dexpi_report(str(xmls[0]), our_tags)
        a, b, c = st.columns(3)
        a.metric("Node coverage", f"{rep['coverage']*100:.0f}%",
                 help=f"of {rep['dex_tags']} DEXPI-tagged components recovered "
                      "from the PDF (text).")
        b.metric("Symbol-only valves added", f"+{s['nodes_symbol_only']}",
                 help="Beyond text — the CNN's contribution to closing the gap.")
        c.metric("Scoreable process edges", f"{rep['scoped']}/{rep['proc']}",
                 help="DEXPI tag-to-tag PROCESS adjacencies with BOTH endpoints "
                      "recoverable from the PDF.")
        st.info(
            f"**The connectivity finding.** This DEXPI export has {rep['proc']} "
            f"tag-to-tag *process* adjacencies, but only **{rep['scoped']}** have "
            f"both endpoints recoverable from the PDF — so tag-level edge scoring "
            f"has almost no valid targets. Physical piping is modelled through "
            f"*untagged* nozzle/segment elements, and most of what the export "
            f"labels connectivity is *signal/instrument-loop* links "
            f"({rep['sig']} here: PT↔PI, ZS↔ZL …), not process pipe. That is "
            f"direct input to the *minimum requirements for machine-readable "
            f"deliverables*: require tagged, tag-to-tag connectivity and "
            f"disambiguate process vs signal.")
    else:
        st.caption("No DEXPI XML for this drawing — the measurement panel needs "
                   "structured ground truth.")
