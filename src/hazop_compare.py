"""
src/hazop_compare.py  —  PDF vs DEXPI, same HAZOP module, side by side

Registered by src/app.py via st.navigation:
    st.Page("hazop_compare.py", title="HAZOP: PDF vs DEXPI", icon="⚖️"),

The single most persuasive format argument in the project, made concrete:
the SAME worksheet machinery (analysis/hazop_prep.build_worksheet) is run
twice on the SAME drawing —

  LEFT   input = PDF text-layer extraction
         nodes = functional loops (shared tag number — connectivity guessed)
  RIGHT  input = Semantum DEXPI XML
         nodes = equipment-anchored process sections (connectivity stated)

Only the drawings that exist in BOTH forms are offered, so every difference
on screen is attributable to the input format, not the drawing.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st

from config import PID_DIR
from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph
from analysis.hazop_prep import build_worksheet, write_worksheet_csv
from analysis.hazop_dexpi import load_dexpi_model

RAW_DIR = Path(PID_DIR).parent


# ---- pairing: drawings that exist as both PDF and DEXPI XML ----------------
def find_pairs() -> dict[str, tuple[Path, Path]]:
    """{drawing stem: (pdf_path, xml_path)} for drawings with both forms."""
    xmls = {x.stem.replace(".DGN", ""): x for x in RAW_DIR.rglob("*.DGN.xml")}
    pairs = {}
    for pdf in sorted(list(PID_DIR.glob("*.PDF")) + list(PID_DIR.glob("*.pdf"))):
        if pdf.stem in xmls:
            pairs[pdf.stem] = (pdf, xmls[pdf.stem])
    return pairs


@st.cache_resource(show_spinner="Running both pipelines…")
def run_both(stem: str, pdf: str, xml: str) -> dict:
    # PDF side: text-layer extraction, loop-based nodes
    objs = sorted(set(create_objects(extract_tags(pdf), "P&ID")),
                  key=lambda o: o.tag)
    g_pdf = build_graph(objs)
    rows_pdf = build_worksheet(g_pdf, objs)
    # DEXPI side: stated connectivity, equipment-anchored sections. If a
    # drawing yields no sections (no tagged equipment, signal-only sheet),
    # fall back to loop-based nodes on the DEXPI objects — still better
    # consequences than the PDF side, since the tag graph is real.
    m = load_dexpi_model(Path(xml))
    fallback = not m["sections"]
    rows_dx = build_worksheet(m["tag_graph"], m["objects"],
                              nodes=m["sections"] or None)
    return {"pdf_objs": objs, "pdf_rows": rows_pdf, "pdf_edges": g_pdf.number_of_edges(),
            "dx": m, "dx_rows": rows_dx, "dx_fallback": fallback}


def _stats(rows, n_tags, n_edges) -> dict:
    with_sg = sum(1 for r in rows if not r["safeguards"].startswith("(none"))
    share = f"{with_sg}/{len(rows)} ({with_sg / len(rows):.0%})" if rows else "–"
    return {"tags": n_tags, "nodes": len({r["node"] for r in rows}),
            "deviation rows": len(rows),
            "share of rows with found barrier": share,
            "connections in graph": n_edges}


def _show(rows, key: str, stem: str):
    if not rows:
        st.warning("No nodes with process parameters.")
        return
    df = pd.DataFrame(rows)[["node", "deviation", "causes",
                             "consequences", "safeguards"]]
    node = st.selectbox("Node", ["(all)"] + sorted(df.node.unique()), key=key)
    if node != "(all)":
        df = df[df.node == node]
    st.dataframe(df, use_container_width=True, hide_index=True, height=420)
    out = Path(f"reports/hazop_{key}_{re.sub(r'[^A-Za-z0-9]+', '_', stem)}.csv")
    out.parent.mkdir(exist_ok=True)
    write_worksheet_csv(rows, out)
    st.download_button("Download (CSV)", out.read_bytes(),
                       file_name=out.name, mime="text/csv", key=f"dl_{key}")


# ---- page -------------------------------------------------------------------
from ui import page_header
page_header("HAZOP preparation: PDF vs DEXPI",
            "Same worksheet machinery · same drawing · two input formats")
st.caption("Same worksheet machinery, same drawing, two input formats. "
           "All differences below are due to the format: the PDF side must guess "
           "groupings from tag numbers, the DEXPI side reads the connections "
           "explicitly and can anchor nodes in equipment. Preparation material "
           "for HAZOP teams — not a completed study.")

pairs = find_pairs()
if not pairs:
    st.error("Found no drawing that exists as both PDF (data/raw/P&ID) and "
             "DEXPI XML (Semantum folder).")
    st.stop()

stem = st.sidebar.selectbox("Drawing", sorted(pairs))
pdf_path, xml_path = pairs[stem]
R = run_both(stem, str(pdf_path), str(xml_path))

s_pdf = _stats(R["pdf_rows"], len(R["pdf_objs"]), R["pdf_edges"])
s_dx = _stats(R["dx_rows"], R["dx"]["stats"]["tagged_elements"],
              R["dx"]["stats"]["tag_edges"])

st.subheader("Key figures")
mdf = pd.DataFrame({"PDF (text layer, loop nodes)": s_pdf,
                    "DEXPI (connections, equipment sections)": s_dx})
st.dataframe(mdf, use_container_width=True)
st.caption("«Share of rows with found barrier»: deviation rows where at least one real, "
           "extracted safeguard tag was identified — as a share, since "
           "the PDF side creates many more, smaller nodes and would otherwise win "
           "on volume. Note also the node names: the PDF side CAN only name nodes "
           "by loop number; the DEXPI side can anchor them in equipment.")

left, right = st.columns(2)
with left:
    st.subheader("PDF — functional loops")
    st.caption("Nodes = tags sharing a loop number. Connectivity is guessed; "
               "consequences cannot cross loop boundaries.")
    _show(R["pdf_rows"], "pdf", stem)
with right:
    st.subheader("DEXPI — equipment-anchored sections")
    st.caption("Nodes = everything process-connected around each piece of equipment (nozzle, "
               "segment, and containment relations from XML). Consequences "
               "follow real directed connections.")
    if R.get("dx_fallback"):
        st.info("This drawing yielded no equipment sections (no tagged "
                "equipment units in the process network) — showing loop nodes on "
                "DEXPI data instead. Consequences still use real "
                "connections.")
    _show(R["dx_rows"], "dexpi", stem)

st.divider()
st.caption("Honest boundaries: The DEXPI sections are graph-based approximations of "
           "a HAZOP leader's node cuts — on drawings with few tagged "
           "equipment units, the sections become broad, and elements between two "
           "pieces of equipment may belong to both sections. The PDF side inherits "
           "the text layer's recall ceiling (see Results.md).")