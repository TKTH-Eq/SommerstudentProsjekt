"""
src/referansevelger.py
=====================================================================
Streamlit page: mark one clean instance of a symbol, see exactly what the
geometry reader gets out of it, and save it as a reference.

Why this page rather than more tuning: when a generated pattern turns out to be
a pipe elbow, two things could be wrong — the detector put the box in the wrong
place, or the geometry reader misread a correct box. Every knob you turn moves
both at once. Marking the box yourself removes the first possibility entirely,
and what comes out then answers the question with no ambiguity left.

The picture is the point. A table saying "7 primitives" cannot tell you whether
you extracted a ball valve or seven fragments of pipe. The two panels side by
side — the drawing as it is, and the geometry as extracted — can, at a glance.

Add to app.py:

    st.Page("referansevelger.py", title="Reference symbols", icon="🎯"),
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.broker_config import extract_region_geometry      # noqa: E402
from analysis.symbol_reference import (                          # noqa: E402
    Reference, describe_profile, load_references, render_svg,
    save_reference, shape_profile, sweep_variants,
)
from tegningsvisning import crop_around, original_image          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATEVALVE_DIR = ROOT / "gatevalve-ai"
RESULTS_DIR = GATEVALVE_DIR / "results"
REF_DIR = ROOT / "data" / "broker" / "references"

try:
    from config import PID_DIR                                   # noqa: E402
except Exception:                                                # noqa: BLE001
    PID_DIR = ROOT / "data" / "raw" / "P&ID"

try:
    from ui import page_header                                   # noqa: E402
except Exception:                                                # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)

DEXPI_CLASSES = ["GateValve", "BallValve", "GlobeValve", "CheckValve",
                 "ButterflyValve", "PipeReducer", "PlugValve", "NeedleValve"]

page_header("Reference symbols",
            "Mark one clean instance — and see what the geometry reader "
            "actually gets out of it")

pdfs = sorted(p for p in Path(PID_DIR).rglob("*")
              if p.suffix.lower() == ".pdf") if Path(PID_DIR).exists() else []
if not pdfs:
    st.error(f"Found no PDFs under {PID_DIR}.")
    st.stop()

drawing = st.selectbox("Drawing", pdfs, format_func=lambda p: p.name)

# ------------------------------------------------------- pick a starting box
det_path = RESULTS_DIR / f"{drawing.stem}_detections.json"
run_path = RESULTS_DIR / f"{drawing.stem}_run.json"
dets = []
if det_path.exists():
    try:
        dets = json.loads(det_path.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        dets = []

dpi_default = 200
if run_path.exists():
    try:
        dpi_default = int(json.loads(run_path.read_text(encoding="utf-8"))["dpi"])
    except Exception:                                            # noqa: BLE001
        pass

st.caption("Start from a detection and adjust, or type a box directly. The box "
           "is in pixels at the analysis DPI — the same space as bbox_orig.")

if dets:
    ordered = sorted(range(len(dets)), key=lambda i: -float(dets[i].get("conf", 0)))
    pick = st.selectbox(
        "Start from detection", [None] + ordered,
        format_func=lambda i: "— type the box myself —" if i is None else
        (f"{dets[i].get('cls')} · {float(dets[i].get('conf', 0)):.2f} · "
         f"({dets[i]['bbox_orig'][0]}, {dets[i]['bbox_orig'][1]})"))
    start = dets[pick]["bbox_orig"] if pick is not None else [500, 500, 560, 560]
else:
    st.info("No detections for this drawing yet — type a box, or run it on the "
            "Drawing analysis page first.")
    start = [500, 500, 560, 560]

b1, b2, b3, b4, b5 = st.columns(5)
with b1:
    x0 = st.number_input("x0", value=int(start[0]), step=5)
with b2:
    y0 = st.number_input("y0", value=int(start[1]), step=5)
with b3:
    x1 = st.number_input("x1", value=int(start[2]), step=5)
with b4:
    y1 = st.number_input("y1", value=int(start[3]), step=5)
with b5:
    dpi = st.number_input("DPI", 72, 600, dpi_default, step=25)

bbox = [float(x0), float(y0), float(x1), float(y1)]
if x1 <= x0 or y1 <= y0:
    st.error("x1 must be greater than x0, and y1 greater than y0.")
    st.stop()

s1, s2, s3 = st.columns(3)
with s1:
    mode = st.selectbox("Mode", ["majority", "contain", "intersect"], index=0)
with s2:
    pad_px = st.slider("Padding (px)", 0.0, 40.0, 8.0, 2.0)
with s3:
    flip_y = st.checkbox("Flip y-axis", value=False,
                         help="Off is correct for the Huldra sheets: "
                              "pdfplumber already reports top-down "
                              "coordinates there. If a whole drawing comes "
                              "back empty, try turning it on.")

settings = {"mode": mode, "pad_px": float(pad_px), "flip_y": flip_y}

# ------------------------------------------------------------ the comparison
try:
    curves = extract_region_geometry(drawing, tuple(bbox), int(dpi), **settings)
    err = ""
except Exception as e:                                           # noqa: BLE001
    curves, err = [], str(e)
if err:
    st.error(f"Extraction failed: {err}")

left, right = st.columns(2)
with left:
    st.markdown("**On the drawing**")
    try:
        img = original_image(drawing, int(dpi))
        st.image(crop_around(img, bbox, margin=1.2), use_container_width=True)
    except Exception as e:                                       # noqa: BLE001
        st.warning(f"Could not render: {e}")
with right:
    st.markdown("**What was extracted**")
    st.markdown(render_svg(curves, size=300), unsafe_allow_html=True)

profile = shape_profile(curves)
if curves:
    st.success(describe_profile(profile))
    total_points = sum(len(c.coords) // 2 for c in curves)
    if total_points < 6:
        st.warning(f"Only {total_points} points in total. That is too little "
                   f"geometry to be a symbol — either the box is off the mark, "
                   f"or the reader is dropping segments. Check the variant "
                   f"sweep below.")
    elif len(curves) <= 2:
        st.info(f"Few primitives ({len(curves)}) but {total_points} points: "
                f"this symbol is drawn as continuous polylines rather than "
                f"separate strokes. That is a legitimate composition, and one "
                f"the configuration may not have — compare it on the Symbol "
                f"variants page.")
else:
    st.warning("Nothing extracted. Run the sweep — if every row is zero, the "
               "region is not where you think it is.")

# --------------------------------------------------------------- diagnosis
with st.expander("Variant sweep — which settings read this symbol?", expanded=not curves):
    st.caption("Six ways of reading the same region. All zero means the box is "
               "in the wrong place: check the DPI and whether the page is "
               "rotated. Zero for «contain» but many for «majority» means the "
               "bezier control points were the problem — the default already "
               "handles that.")
    rows = sweep_variants(drawing, bbox, int(dpi))
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------- saving
st.divider()
st.subheader("Save as reference")
st.caption("A saved reference is ground truth for what this symbol is made of. "
           "It filters noisy regions elsewhere on the sheet, and it can be used "
           "directly as the geometry for a Model Broker pattern.")

n1, n2 = st.columns([2, 1])
with n1:
    name = st.text_input("Name", value=f"{drawing.stem[-8:]}_symbol")
with n2:
    dexpi_class = st.selectbox("DEXPI class", DEXPI_CLASSES)
note = st.text_input("Note (optional)",
                     placeholder="e.g. drawn filled rather than outlined")

if st.button("Save reference", type="primary", disabled=not curves):
    ref = Reference.from_curves(name, dexpi_class, drawing.name, bbox,
                                int(dpi), settings, curves, note)
    path = save_reference(ref, REF_DIR)
    st.success(f"Saved to `{path}`")

existing = load_references(REF_DIR)
if existing:
    st.markdown(f"**{len(existing)} saved references**")
    cols = st.columns(min(4, len(existing)))
    for i, ref in enumerate(existing[:8]):
        with cols[i % len(cols)]:
            st.markdown(render_svg(ref.curves, size=120), unsafe_allow_html=True)
            st.caption(f"{ref.name}  \n{ref.dexpi_class} · "
                       f"{len(ref.coords)} prim.")
    with st.expander("Reference table"):
        st.dataframe(pd.DataFrame([
            {"name": r.name, "class": r.dexpi_class, "drawing": r.drawing,
             "primitives": len(r.coords), "dpi": r.dpi,
             "mode": r.settings.get("mode"), "note": r.note}
            for r in existing]), use_container_width=True, hide_index=True)

st.caption("Marking the box yourself removes detector error from the picture. "
           "If extraction still fails here, the geometry reader is the problem "
           "— and that is a useful thing to have established.")