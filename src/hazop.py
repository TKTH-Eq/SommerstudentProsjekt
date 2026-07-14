"""
src/hazop.py  —  HAZOP preparation page

Registered by src/app.py via st.navigation:
    st.Page("hazop.py", title="HAZOP-forberedelse", icon="⚠️"),

Thin shell over analysis/hazop_prep.py — same pattern as system_analysis.py:
pick a system, the pipeline runs (cached), pick nodes, get a pre-filled
HAZOP worksheet grounded in the extracted tags. Optional AI rewriting per
node when ANTHROPIC_API_KEY is set; the deterministic worksheet is always
the fallback and the source of truth.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st

from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph
from analysis.hazop_prep import build_worksheet, hazop_nodes, write_worksheet_csv, ai_enrich_node
from system_analysis import find_systems  # reuse discovery — one source of truth


systems = find_systems()
st.sidebar.title("HAZOP-forberedelse")
if not systems:
    st.error("No system found with both a P&ID and an SCD in data/raw/.")
    st.stop()

system = st.sidebar.selectbox("System", list(systems), format_func=lambda s: f"System {s}")
pid_path, scd_path = systems[system]


@st.cache_resource(show_spinner="Building worksheet…")
def load(system: str, pid: str, scd: str):
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    g = build_graph(objs)
    return objs, g, build_worksheet(g, objs)


objs, g, all_rows = load(system, str(pid_path), str(scd_path))

st.title(f"System {system} — HAZOP preparation")
st.caption("Pre-filled worksheet from AI-extracted P&ID/SCD data. Nodes are "
           "functional loops (real HAZOP nodes are process sections — that "
           "requires traced connectivity, i.e. DEXPI). Every tag referenced "
           "exists in the extraction; nothing is invented. For HAZOP team "
           "review — not a completed study.")

nodes = sorted({r["node"] for r in all_rows})
if not nodes:
    st.warning("No loop in this system has instruments that map to a process "
               "parameter — nothing to propose.")
    st.stop()

picked = st.multiselect("Nodes (functional loops)", nodes, default=nodes[:3])
rows = [r for r in all_rows if r["node"] in set(picked)]

if rows:
    df = pd.DataFrame(rows)[["node", "parameter", "deviation", "causes",
                             "consequences", "safeguards"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    # download the full worksheet (all nodes, all columns incl. recommendation)
    out = Path("reports/hazop_worksheet.csv")
    out.parent.mkdir(exist_ok=True)
    write_worksheet_csv(all_rows, out)
    st.download_button("Last ned hele arbeidsarket (CSV)",
                       out.read_bytes(), file_name=f"hazop_system_{system}.csv",
                       mime="text/csv")

    # optional AI pass, one node at a time (same key-gating as operator_brief)
    st.divider()
    if os.getenv("ANTHROPIC_API_KEY"):
        node_ai = st.selectbox("AI-omskriving av én node", picked or nodes)
        if st.button("Generer AI-utkast for noden"):
            node_rows = [r for r in all_rows if r["node"] == node_ai]
            with st.spinner("Spør modellen…"):
                st.markdown(ai_enrich_node(node_rows))
    else:
        st.caption("Sett ANTHROPIC_API_KEY for valgfri AI-omskriving per node — "
                   "arbeidsarket over er deterministisk og komplett uten.")
else:
    st.info("Velg minst én node.")