"""
src/dexpi_graph.py  —  DEXPI-driven topology page

A separate page from the PDF-based analysis. Where the PDF pipeline *guesses*
connectivity from tag proximity, DEXPI (Semantum's ISO-15926 export) states it
explicitly: every <Connection FromID ToID> links two element IDs, and each
component carries an ID + TagName. This page reads that real topology and draws
it with the SAME interactive_svg used on the PDF page — same tool, better data.

Only drawings that have a DEXPI XML are covered here (the reliable subset).
The PDF pages are unchanged and still cover everything as best-effort.

Register in app.py's st.navigation list, e.g.:
    st.Page("dexpi_graph.py", title="DEXPI topology", icon="🔗"),
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.engineering_object import EngineeringObject

# Reuse the project's own graph renderer so this page matches system_analysis.py.
try:
    from analysis.build_dependency_graph import interactive_svg
    _HAVE_SVG = True
except Exception:
    _HAVE_SVG = False

try:
    from config import CATEGORY_COLORS, PID_DIR
    RAW_DIR = Path(PID_DIR).parent
except Exception:
    CATEGORY_COLORS = {}
    RAW_DIR = Path("data/raw")


# --------------------------------------------------------------------------
# DEXPI parsing + topology
# --------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.split("}")[-1]


def find_dexpi_files() -> dict:
    """label -> xml path, for every DEXPI XML under data/raw."""
    out = {}
    for x in sorted(RAW_DIR.rglob("*.xml")) + sorted(RAW_DIR.rglob("*.XML")):
        m = re.search(r"H[A-Z](\d{2})", x.stem)
        label = f"{m.group(1) if m else '??'}  ·  {re.sub(r'[._]DGN$', '', x.stem, flags=re.I)}"
        out[label] = x
    return out


@st.cache_data(show_spinner="Reading DEXPI topology…")
def parse_topology(xml_path: str, mtime: float) -> dict:
    root = ET.parse(xml_path).getroot()

    id2tag: dict[str, str] = {}
    for el in root.iter():
        eid = el.get("ID")
        if not eid:
            continue
        tag = el.get("TagName")
        if not tag:
            for ga in el:
                if _local(ga.tag) == "GenericAttribute" and ga.get("Name") in (
                        "tagName", "valveTag", "TagNameAssignmentClass"):
                    tag = ga.get("Value")
                    break
        if tag and '"' not in tag:
            id2tag[eid] = tag.strip()

    # directed graph over ALL element IDs, from the connections
    gid = nx.DiGraph()
    n_conn = 0
    for el in root.iter():
        if _local(el.tag) == "Connection":
            n_conn += 1
            a, b = el.get("FromID"), el.get("ToID")
            if a and b:
                gid.add_edge(a, b)

    # contract untagged intermediate nodes -> tag-to-tag edges
    tagged = set(id2tag)
    edges = set()
    for u in tagged:
        if u not in gid:
            continue
        seen, stack = set(), list(gid.successors(u))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in tagged:
                if id2tag[u] != id2tag[n]:
                    edges.add((id2tag[u], id2tag[n]))
            else:
                stack.extend(gid.successors(n))

    return {
        "nodes": sorted(set(id2tag.values())),
        "edges": sorted(edges),
        "n_components": len(id2tag),
        "n_connections": n_conn,
    }


def build_graph(topo: dict, source: str) -> nx.DiGraph:
    """Build the graph exactly like analysis.build_dependency_graph.build_graph:
    tag-string nodes carrying category / type_code / loop / source attributes,
    so interactive_svg can read them."""
    g = nx.DiGraph()
    for tag in topo["nodes"]:
        o = EngineeringObject.from_tag(tag, source=source)
        g.add_node(o.tag, category=o.category, type_code=o.type_code,
                   loop=o.loop, source=o.source)
    for u, v in topo["edges"]:
        # from_tag normalises to upper-case; keep node keys consistent
        g.add_edge(EngineeringObject.from_tag(u).tag,
                   EngineeringObject.from_tag(v).tag)
    return g


# --------------------------------------------------------------------------
# Fallback renderer (only used if interactive_svg isn't importable)
# --------------------------------------------------------------------------

_FALLBACK_COLORS = {"input": "#2d7dd2", "logic": "#7b1fa2", "output": "#2e7d32",
                    "equipment": "#5d4037", "other": "#607d8b"}


def _fallback_dot(g: nx.DiGraph, highlight: str | None = None) -> str:
    lines = ['digraph G {', 'rankdir=LR;', 'bgcolor="transparent";',
             'nodesep=0.25; ranksep=0.6;',
             'node [style=filled, fontname="sans-serif", fontsize=10, shape=box];',
             'edge [color="#90a4ae", arrowsize=0.7];']
    for n, d in g.nodes(data=True):
        fill = CATEGORY_COLORS.get(d.get("category", "other")) \
            or _FALLBACK_COLORS.get(d.get("category", "other"), "#607d8b")
        pen = ' penwidth=3 color="#111"' if n == highlight else ""
        lines.append(f'"{n}" [fillcolor="{fill}", fontcolor="white"{pen}];')
    for u, v in g.edges:
        lines.append(f'"{u}" -> "{v}";')
    lines.append("}")
    return "\n".join(lines)


def draw(g: nx.DiGraph, highlight: str | None = None):
    """Render with interactive_svg when available, else graphviz fallback."""
    if _HAVE_SVG:
        try:
            he = None
            if highlight:
                he = {"sel": highlight,
                      "down": list(nx.descendants(g, highlight)),
                      "up": list(nx.ancestors(g, highlight))}
            components.html(
                f"<div style='font-family:Inter,sans-serif'>{interactive_svg(g, highlight=he)}</div>",
                height=640, scrolling=False)
            return
        except Exception as e:  # noqa: BLE001
            st.caption(f"(interactive_svg failed – using simple graph: {e})")
    st.graphviz_chart(_fallback_dot(g, highlight))


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

from ui import page_header
page_header("DEXPI topology",
            "Semantum DEXPI · FromID→ToID — stated connectivity, not guessed")
st.caption("Real connections from Semantum's DEXPI files — what is actually "
           "connected to what, not guessed from proximity. Same graph view as "
           "the system analysis, but fed from DEXPI. Only covers drawings that have "
           "a DEXPI XML; the PDF pages cover the rest.")

files = find_dexpi_files()
if not files:
    st.error("Found no DEXPI XML under data/raw/ (e.g. in "
             "'Semantum Huldra P&IDS').")
    st.stop()

from incident_context import incident_banner, match_index, anchor_tag
_inc = incident_banner("drawing and focus preselected below", key="topo")
choice = st.sidebar.selectbox(
    "Drawing (system · document)", sorted(files),
    index=match_index(sorted(files),
                      *((_inc.get("drawings") or []) if _inc else []),
                      _inc and _inc.get("system")))
xml_path = files[choice]
topo = parse_topology(str(xml_path), xml_path.stat().st_mtime)
g = build_graph(topo, source=xml_path.name)

connected = [n for n in g.nodes if g.degree(n) > 0]
isolated = g.number_of_nodes() - len(connected)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Components with tag", topo["n_components"])
c2.metric("Connections (raw)", topo["n_connections"])
c3.metric("Connected nodes", len(connected))
c4.metric("Edges (tag→tag)", g.number_of_edges())

if g.number_of_edges() == 0:
    st.warning("The DEXPI file for this drawing provided no tag-to-tag connections to "
               "draw. Select another drawing, or view the component list below.")
    with st.expander(f"Components with tag ({g.number_of_nodes()})"):
        st.dataframe({"tag": sorted(g.nodes)}, use_container_width=True,
                     hide_index=True)
    st.stop()

st.sidebar.divider()
focus = st.sidebar.selectbox(
    "Focus on tag", ["(entire graph)"] + sorted(connected),
    index=match_index(["(entire graph)"] + sorted(connected),
                      anchor_tag(_inc)))

if focus != "(entire graph)":
    st.markdown(f"**{focus}** &nbsp; "
                f"↓ downstream: {', '.join(g.successors(focus)) or '–'} &nbsp;&nbsp; "
                f"↑ upstream: {', '.join(g.predecessors(focus)) or '–'}")
    draw(g.subgraph(connected), highlight=focus)
else:
    if isolated:
        st.caption(f"Hiding {isolated} stand-alone tag(s) without registered "
                   f"connection.")
    draw(g.subgraph(connected))

with st.expander(f"All connections ({g.number_of_edges()})"):
    st.dataframe({"from": [u for u, _ in g.edges], "to": [v for _, v in g.edges]},
                 use_container_width=True, hide_index=True)

st.caption("Direction follows DEXPI FromID→ToID (flow/signal direction). "
           "Intermediate piping components without tags have been contracted out.")