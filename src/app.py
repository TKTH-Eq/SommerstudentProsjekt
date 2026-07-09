"""
Streamlit front-end for the Huldra P&ID/SCD analysis tool.

Lets you pick a system that has BOTH a P&ID and an SCD in data/raw/, runs the
whole pipeline live, and shows KPIs, the consistency check, the safety register,
the interactive dependency graph and a failure explorer with an operator brief.

Run (from the project root):
    pip install streamlit
    streamlit run src/app.py

This is a thin shell over the same modules as main.py / dashboard.py - all the
logic lives there, so the app can never disagree with the batch pipeline.
"""
from __future__ import annotations
import sys, os, re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components

from config import PID_DIR, SCD_DIR, CATEGORY_COLORS, SAFETY_TYPES
from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph, interactive_svg
from analysis.consistency_check import check_consistency
from analysis.kpi_analysis import compute_kpis, quality_flags
from analysis.analyze_scd import failure_map
from analysis.root_cause import root_cause
from ai.operator_brief import operator_brief


# ---- data discovery --------------------------------------------------------
def find_systems() -> dict:
    """Systems that have BOTH a P&ID and an SCD, keyed by system code."""
    def scan(d: Path) -> dict:
        out = {}
        for f in sorted(list(d.glob("*.PDF")) + list(d.glob("*.pdf"))):
            m = re.search(r"H[A-Z](\d{2})", f.stem)
            if m:
                out.setdefault(m.group(1), f)
        return out
    pid, scd = scan(PID_DIR), scan(SCD_DIR)
    return {s: (pid[s], scd[s]) for s in sorted(set(pid) & set(scd))}


@st.cache_resource(show_spinner="Running pipeline…")
def run_pipeline(system: str, pid_path: str, scd_path: str) -> dict:
    pid = create_objects(extract_tags(pid_path), "P&ID")
    scd = create_objects(extract_tags(scd_path), "SCD")
    allo = sorted(set(pid) | set(scd), key=lambda o: o.tag)
    g = build_graph(allo)
    return {
        "pid": pid, "scd": scd, "allo": allo, "g": g,
        "by_tag": {o.tag: o for o in allo},
        "cons": check_consistency(pid, scd),
        "kpis": compute_kpis(g, allo),
        "flags": quality_flags(allo),
        "safety": sorted(o.tag for o in allo if o.type_code in SAFETY_TYPES),
        "fmap": failure_map(g, allo),
    }


# ---- small helpers ---------------------------------------------------------
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
st.set_page_config(page_title="Huldra P&ID/SCD analysis", layout="wide")

systems = find_systems()
st.sidebar.title("Huldra drawing analysis")
if not systems:
    st.error("No system found with both a P&ID and an SCD in data/raw/. "
             "Add matching drawings (filenames contain the system code, e.g. …-HO27-…).")
    st.stop()

system = st.sidebar.selectbox("System", list(systems), format_func=lambda s: f"System {s}")
pid_path, scd_path = systems[system]
st.sidebar.caption(f"P&ID: {pid_path.name}")
st.sidebar.caption(f"SCD:  {scd_path.name}")

R = run_pipeline(system, str(pid_path), str(scd_path))
kpis, cons, by_tag = R["kpis"], R["cons"], R["by_tag"]

st.title(f"System {system} — drawing analysis")
st.caption("Extracted automatically from legacy PDFs — a draft for engineer review, "
           "not an authoritative source.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Components", kpis["components"])
c2.metric("Functional loops", kpis["functional_loops"])
c3.metric("Safety-related tags", len(R["safety"]))
c4.metric("To verify (SCD-only)", len(cons["scd_only"]))

st.subheader("P&ID ↔ SCD consistency")
a, b, c = st.columns(3)
a.markdown(f"**On both — {len(cons['both'])}**", unsafe_allow_html=True)
a.markdown(chips(cons["both"], by_tag), unsafe_allow_html=True)
b.markdown(f"**P&ID only — {len(cons['pid_only'])}**  \nusually expected")
b.markdown(chips(cons["pid_only"], by_tag), unsafe_allow_html=True)
c.markdown(f"**SCD only — {len(cons['scd_only'])}**  \nlogic refs not on P&ID — verify")
c.markdown(chips(cons["scd_only"], by_tag), unsafe_allow_html=True)

if R["flags"]:
    st.subheader("Quality flags")
    for f in R["flags"]:
        st.write("• " + f)

st.subheader("Safety register")
st.markdown(chips(R["safety"], by_tag), unsafe_allow_html=True)

st.subheader("Dependency graph")
st.caption("Loop-based (input → logic → output), not traced piping.")
components.html(f"<div style='font-family:sans-serif'>{interactive_svg(R['g'])}</div>",
                height=620, scrolling=False)

st.subheader("Failure explorer")
st.caption("Pick a tag to see what can go wrong, what it affects, and where a symptom "
           "here could come from. Structural, from the loop model — a prompt, not a diagnosis.")
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

st.subheader("Alarm root-cause (simulated)")
st.caption("Pick the tags that are 'in alarm' to simulate an alarm shower. The graph "
           "separates the probable root cause from downstream consequences — the core of "
           "root-cause analysis. Wire this to the live alarm feed to make it operational.")
alarms = st.multiselect("Active alarms", sorted(R["fmap"]))
if alarms:
    res = root_cause(R["g"], alarms)
    if res["roots"]:
        primary = res["roots"][0]
        st.markdown(f"**Probable root cause:** "
                    f"<span style='background:{CATEGORY_COLORS.get(by_tag[primary].category,'#9aa0a6')};"
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
    st.caption("Decision support on the loop-based graph — proposes a likely origin for an "
               "engineer to confirm, not a diagnosis.")