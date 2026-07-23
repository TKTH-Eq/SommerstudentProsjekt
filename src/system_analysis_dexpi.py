"""
src/system_analysis_dexpi.py  —  the system-analysis page, fed from DEXPI

Registered by src/app.py via st.navigation:
    st.Page("system_analysis_dexpi.py", title="System Analysis (DEXPI)", icon="🧭"),

Deliberately a mirror of system_analysis.py — same KPIs, failure explorer,
operator brief, alarm root-cause, live simulation and interactive graph,
driven by the SAME analysis modules (failure_map, root_cause, compute_kpis,
interactive_svg are all graph-generic). Only two things differ:

  INPUT   one DEXPI XML instead of a P&ID/SCD PDF pair, loaded through
          analysis.hazop_dexpi.load_dexpi_model — so the dependency graph
          carries STATED connectivity (368 real edges on HO27-002) instead
          of guessed loop chains, and consequences/root causes can cross
          loop boundaries.

  CHECK   the P&ID↔SCD consistency section is replaced by a DEXPI↔PDF
          reconciliation for the same drawing (when the PDF exists):
          tags on both, DEXPI-only (≈ the text-layer recall gap, per
          drawing) and PDF-only (extraction noise / off-model text).

That is the whole point of keeping both pages: same tool, better data.
"""
from __future__ import annotations
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components

from config import PID_DIR, CATEGORY_COLORS, SAFETY_TYPES
from analysis.hazop_dexpi import load_dexpi_model
from analysis.build_dependency_graph import interactive_svg
from analysis.kpi_analysis import compute_kpis
from analysis.analyze_scd import failure_map
from analysis.root_cause import root_cause
from analysis.signal_sim import simulate_series
from ai.operator_brief import operator_brief

RAW_DIR = Path(PID_DIR).parent


# ---- data discovery --------------------------------------------------------
def find_dexpi() -> dict:
    """{label: xml_path} for every DEXPI file, labelled by system + doc."""
    out = {}
    for x in sorted(RAW_DIR.rglob("*.DGN.xml")):
        m = re.search(r"H[A-Z](\d{2})", x.stem)
        label = f"{m.group(1) if m else '??'} · {x.stem.replace('.DGN', '')}"
        out[label] = x
    return out


def matching_pdf(xml_path: Path) -> Path | None:
    stem = xml_path.stem.replace(".DGN", "")
    for pdf in list(PID_DIR.glob("*.PDF")) + list(PID_DIR.glob("*.pdf")):
        if pdf.stem == stem:
            return pdf
    return None


@st.cache_resource(show_spinner="Reading DEXPI model…")
def run_pipeline(xml: str, mtime: float) -> dict:
    m = load_dexpi_model(Path(xml))
    allo, g = m["objects"], m["tag_graph"]
    return {
        "allo": allo, "g": g, "sections": m["sections"], "stats": m["stats"],
        "by_tag": {o.tag: o for o in allo},
        "kpis": compute_kpis(g, allo),
        "safety": sorted(o.tag for o in allo if o.type_code in SAFETY_TYPES),
        "fmap": failure_map(g, allo),
    }


@st.cache_resource(show_spinner="Comparing with the PDF text layer…")
def pdf_reconciliation(pdf: str, dexpi_tags: tuple) -> dict | None:
    try:
        from extraction.tag_extractor import extract_tags, create_objects
        pdf_tags = {o.tag for o in create_objects(extract_tags(pdf), "P&ID")}
    except Exception:                                                   # noqa: BLE001
        return None
    dx = set(dexpi_tags)
    return {"both": sorted(dx & pdf_tags),
            "dexpi_only": sorted(dx - pdf_tags),
            "pdf_only": sorted(pdf_tags - dx)}


# ---- small helpers (same look as system_analysis.py) ------------------------
def chips(tags, by_tag):
    if not tags:
        return "_none_"
    out = ""
    for t in tags:
        cat = by_tag[t].category if t in by_tag else "other"
        c = CATEGORY_COLORS.get(cat, "#9aa0a6")
        out += (f"<span style='background:{c};color:#fff;border-radius:20px;"
                f"padding:2px 8px;margin:2px;display:inline-block;font-size:12px'>{t}</span> ")
    return out


# ---- app -------------------------------------------------------------------
files = find_dexpi()
st.sidebar.title("Huldra drawing analysis — DEXPI")
if not files:
    st.error("Found no DEXPI XML under data/raw/ (Semantum folder).")
    st.stop()

choice = st.sidebar.selectbox("Drawing (system · document)", list(files))
xml_path = files[choice]
st.sidebar.caption(f"DEXPI: {xml_path.name}")

R = run_pipeline(str(xml_path), xml_path.stat().st_mtime)
kpis, by_tag = R["kpis"], R["by_tag"]

from ui import page_header
page_header(f"{choice.split(' · ')[0]} — system analysis (DEXPI)",
            "Connectivity STATED in DEXPI (FromID→ToID) — not guessed from loop numbers")
st.caption("Same analyses as the PDF page, but fed from the structured "
           "DEXPI model: the connections below are STATED in the file "
           "(FromID→ToID), not guessed from loop numbers. Consequences and "
           "root causes can therefore cross loop boundaries.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Components", kpis["components"])
c2.metric("Real connections", R["stats"]["tag_edges"])
c3.metric("Safety tags", len(R["safety"]))
c4.metric("Equipment sections", R["stats"]["sections"])

if kpis.get("most_connected"):
    st.caption("Most connected components (complexity indicator): "
               + ", ".join(kpis["most_connected"]))

# ---- DEXPI ↔ PDF reconciliation (replaces P&ID↔SCD on this page) -----------
pdf = matching_pdf(xml_path)
st.subheader("DEXPI ↔ PDF text layer")
if pdf is None:
    st.caption("No matching PDF in data/raw/P&ID for this drawing — "
               "reconciliation is shown when both formats exist.")
else:
    rec = pdf_reconciliation(str(pdf), tuple(sorted(o.tag for o in R["allo"])))
    if rec is None:
        st.caption("PDF extraction failed (missing PyMuPDF?) — skipping "
                   "reconciliation.")
    else:
        a, b, c = st.columns(3)
        a.markdown(f"**On both — {len(rec['both'])}**")
        a.markdown(chips(rec["both"], by_tag), unsafe_allow_html=True)
        b.markdown(f"**DEXPI only — {len(rec['dexpi_only'])}**  \n"
                   f"≈ the text layer's recall gap on this drawing")
        b.markdown(chips(rec["dexpi_only"], by_tag), unsafe_allow_html=True)
        c.markdown(f"**PDF only — {len(rec['pdf_only'])}**  \n"
                   f"extraction noise or text outside the model — verify")
        c.markdown(chips(rec["pdf_only"], by_tag), unsafe_allow_html=True)

st.subheader("Equipment-anchored sections")
for name, ms in R["sections"].items():
    with st.expander(f"{name} — {len(ms)} members"):
        st.markdown(chips(sorted(o.tag for o in ms), by_tag),
                    unsafe_allow_html=True)

st.subheader("Safety register")
st.markdown(chips(R["safety"], by_tag), unsafe_allow_html=True)

# ---- failure explorer (identical mechanics, real topology) ------------------
st.subheader("Failure explorer")
st.caption("Select a tag and see what can go wrong, what it affects, and where "
           "a symptom might come from — now along STATED connections, so "
           "the chains cross loop boundaries.")
tag = st.selectbox("Tag", sorted(R["fmap"]))
entry = R["fmap"][tag]

st.code(operator_brief(tag, entry, by_tag), language="text")

x, y, z = st.columns(3)
x.markdown("**What can go wrong**")
for m in entry["modes"]:
    x.write("• " + m)
y.markdown("**If it fails → affected**")
y.caption("safety functions"); y.markdown(chips(entry["safety"], by_tag), unsafe_allow_html=True)
y.caption("all downstream"); y.markdown(chips(entry["downstream"], by_tag), unsafe_allow_html=True)
z.markdown("**Possible cause of a symptom here**")
z.caption("upstream candidates"); z.markdown(chips(entry["upstream"], by_tag), unsafe_allow_html=True)

# ---- alarm root cause --------------------------------------------------------
st.subheader("Alarm root-cause (simulated)")
st.caption("Same mechanics as the PDF page — but here the cascade follows real "
           "process/signal connections from the DEXPI file.")
alarms = st.multiselect("Active alarms", sorted(R["fmap"]))
if alarms:
    res = root_cause(R["g"], alarms)
    if res["roots"]:
        primary = res["roots"][0]
        st.markdown(f"**Probable root cause:** "
                    f"<span style='background:{CATEGORY_COLORS.get(by_tag[primary].category, '#9aa0a6')};"
                    f"color:#fff;border-radius:20px;padding:2px 10px'>{primary}</span>",
                    unsafe_allow_html=True)
        if res["explains"][primary]:
            st.caption("explains these downstream alarms as consequences:")
            st.markdown(chips(res["explains"][primary], by_tag), unsafe_allow_html=True)
        if len(res["roots"]) > 1:
            st.caption("other independent roots:")
            st.markdown(chips(res["roots"][1:], by_tag), unsafe_allow_html=True)
    st.markdown("**Classification**")
    for a in res["active"]:
        cls = res["classification"][a]
        mark = "🔴 " if cls == "root cause" else "↳ "
        st.write(f"{mark}`{a}` — {cls}")

# ---- live simulation ---------------------------------------------------------
st.subheader("Live sensor → threshold → alarm → root-cause")
st.caption("Synthetic sensor data drifts towards setpoint; the alarm cascades "
           "along the DEXPI topology and the tool points to the root cause. "
           "Not a process model, not live data.")

inputs_down = [n for n in R["g"].nodes
               if by_tag[n].category == "input" and list(nx.descendants(R["g"], n))]
inputs_down = inputs_down or [n for n in R["g"].nodes
                              if list(nx.descendants(R["g"], n)) and not list(nx.ancestors(R["g"], n))]

if not inputs_down:
    st.info("No input tag with downstream connections to simulate on this drawing.")
else:
    s1, s2, s3 = st.columns(3)
    sensor = s1.selectbox("Drifting sensor", sorted(inputs_down))
    baseline = s2.number_input("Baseline value", value=40.0)
    threshold = s3.number_input("HH set point", value=100.0)
    speed = st.slider("Seconds per step", 0.1, 1.5, 0.4, 0.1)

    if st.button("▶ Run simulation"):
        vals, breach = simulate_series(baseline, threshold, steps=30)
        breach = breach if breach is not None else len(vals) - 1
        chart_ph, status_ph = st.empty(), st.empty()
        for i in range(1, breach + 2):
            chart_ph.line_chart({"value": vals[:i], "HH set point": [threshold] * i})
            cur = vals[i - 1]
            if i - 1 >= breach:
                status_ph.warning(f"⚠ {sensor} = {cur} crossed HH ({threshold}) — ALARM raised")
            else:
                status_ph.info(f"{sensor} = {cur} — normal (below {threshold})")
            time.sleep(speed)
        order = [sensor] + [n for n in nx.bfs_tree(R["g"], sensor) if n != sensor]
        log_ph, res_ph = st.empty(), st.empty()
        log = []
        for k in range(1, len(order) + 1):
            active, newest = order[:k], order[k - 1]
            res = root_cause(R["g"], active)
            log.insert(0, f"🔔 **{newest}** — {res['classification'].get(newest, '')}")
            log_ph.markdown("  \n".join(log[:8]), unsafe_allow_html=True)
            primary = res["roots"][0] if res["roots"] else None
            if primary:
                res_ph.markdown(
                    f"**Probable root cause:** "
                    f"<span style='background:{CATEGORY_COLORS.get(by_tag[primary].category, '#9aa0a6')};"
                    f"color:#fff;border-radius:20px;padding:2px 10px'>{primary}</span> "
                    f"— explains {len(res['explains'][primary])} downstream alarm(s)",
                    unsafe_allow_html=True)
            time.sleep(speed)
        st.success(f"Complete — {sensor} breach propagated along stated "
                   f"connectivity; root cause identified as {order[0]}.")

# ---- graph -------------------------------------------------------------------
st.subheader("Dependency graph — stated connectivity")
st.caption("Edges are FromID→ToID from the DEXPI file (process and "
           "signal direction), not loop assumptions. Search for a tag to "
           "highlight it and its chains.")
search = st.selectbox("🔍 Search a tag to highlight on the graph",
                      [""] + sorted(R["fmap"]), key="dx_graph_search")
hl_tag = search or tag
he = R["fmap"].get(hl_tag)
highlight = {"sel": hl_tag, "down": he["downstream"], "up": he["upstream"]} if he else None
if hl_tag:
    st.markdown(
        f"Highlighting **{hl_tag}** &nbsp; "
        f"<span style='color:#12233b'>■ selected</span> &nbsp; "
        f"<span style='color:#b8442c'>■ downstream (consequence)</span> &nbsp; "
        f"<span style='color:#2d7dd2'>■ upstream (cause)</span>", unsafe_allow_html=True)
components.html(
    f"<div style='font-family:sans-serif'>{interactive_svg(R['g'], highlight=highlight)}</div>",
    height=640, scrolling=False)