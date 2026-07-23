"""
src/anleggsoversikt.py  —  the plant at a glance

Registered via nav_pages.py. The plant model (analysis/plant_model.py) is
the project's most important asset but was invisible — it only powered the
control room. This page makes it visible at DRAWING level, where it is
readable in seconds: 17 nodes, one per sheet, connected where line numbers
prove the sheets share physical piping. The establishing shot before any
plant-wide demo: "first we show that the plant is now ONE model — then we
show what that enables."
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config import PID_DIR
from ui import page_header
from analysis.plant_model import (build_plant_model, metro_svg, metro_html,
                                  plant_criticality)

RAW_DIR = Path(PID_DIR).parent


@st.cache_resource(show_spinner="Stitching the plant model together…")
def load() -> dict:
    return build_plant_model(RAW_DIR)


M = load()
S = M["stats"]

page_header("Plant Overview",
            f"{S['drawings']} DEXPI drawings stitched together into a single model",
            kpis=[("DRAWINGS", str(S["drawings"])),
                  ("TAGS", str(S["tags"])),
                  ("LINE STITCHES", str(S["line_stitches"])),
                  ("CONNECTIONS", str(S["edges"]))])
st.caption("The stitches are shared line numbers: the same pipeline tag on two sheets IS "
           "the same physical line — this proves the connection between the sheets. "
           "This map is impossible to create from the PDFs — and trivial from "
           "structured deliveries.")

st.subheader("The Metro Map — how the sheets are connected")
st.caption("One node per drawing (color = system), line = shared line number "
           "(thicker = more shared lines). Interactive: scroll to zoom, "
           "drag the background to pan, drag a node to move it, "
           "hover over a node to highlight its neighbors, and click a "
           "system in the legend to isolate it.")
components.html(metro_html(M), height=640)

left, right = st.columns(2)

with left:
    st.subheader("The stitches")
    st.caption("Each row is a physical line crossing a drawing boundary — "
               "with the components anchoring it on each side.")
    rows = [{"line": ln, "drawing A": a[-14:], "drawing B": b[-14:],
             "anchor A": ", ".join(ta), "anchor B": ", ".join(tb)}
            for ln, a, b, ta, tb in M["stitches"]]
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True, height=380)

with right:
    st.subheader("Structurally most exposed components")
    st.caption("Most connections in the entire plant — where a failure can reach "
               "the furthest. Exposure, not consequence: redundancy, bypasses and "
               "operating modes are not in the model, so the list indicates where "
               "the engineer should look first, not what actually stops.")
    st.dataframe(pd.DataFrame(plant_criticality(M, 10)),
                 use_container_width=True, hide_index=True, height=380)

st.divider()
st.caption("Direction across a stitch is not provided in the export (off-page "
           "connectors are unnamed), so cross-edges are added both ways — "
           "a documented limitation, and a direct input to the "
           "minimum requirements: named, directed off-page references and "
           "consistent line numbers are what make a plant model cheap. "
           "Try the model in practice: Control Room Assistant → "
           "«🏭 Entire plant».")