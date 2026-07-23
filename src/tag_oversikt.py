"""
src/tag_oversikt.py
=====================================================================
Streamlit page: overview of ALL tags across every system.

Unlike a standalone CSV reader, this page runs the same extraction and
consistency modules the main app uses (extract_tags / create_objects /
check_consistency), so it can never disagree with the pipeline — the
same guarantee as app.py.

Place this file in  src/  next to app.py. It is registered by
st.navigation in app.py (do NOT put it in a pages/ folder).

    src/
      app.py
      system_analysis.py
      tag_oversikt.py   <-- this file
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Make the src/ modules importable (this file lives in src/pages/).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from config import PID_DIR, SCD_DIR, CATEGORY_COLORS, SAFETY_TYPES
    from extraction.tag_extractor import extract_tags, create_objects
    from analysis.consistency_check import check_consistency
except Exception as e:  # noqa: BLE001
    st.title("🏷️ Tag Overview")
    st.error(
        "Could not import project modules (config / extraction / "
        f"analysis).\n\n`{e}`\n\nRun the app from the project root using "
        "`streamlit run src/app.py`, and ensure this file is located in "
        "`src/pages/`."
    )
    st.stop()

STATUS_LABELS = {
    "BOTH": "On both P&ID and SCD",
    "PID_ONLY": "Only on P&ID",
    "SCD_ONLY": "Only on SCD",
}
STATUS_COLORS = {
    "BOTH": "#2e7d32",       # green
    "PID_ONLY": "#1565c0",   # blue
    "SCD_ONLY": "#e65100",   # orange
}


# --------------------------------------------------------------------------
# Discovery + register build (same modules as the pipeline)
# --------------------------------------------------------------------------

def find_systems() -> dict:
    """Systems that have BOTH a P&ID and an SCD (same rule as app.py)."""
    def scan(d) -> dict:
        out = {}
        for f in sorted(list(Path(d).glob("*.PDF")) + list(Path(d).glob("*.pdf"))):
            m = re.search(r"H[A-Z](\d{2})", f.stem)
            if m:
                out.setdefault(m.group(1), f)
        return out
    pid, scd = scan(PID_DIR), scan(SCD_DIR)
    return {s: (pid[s], scd[s]) for s in sorted(set(pid) & set(scd))}


def _dir_signature() -> tuple:
    """Cache key: filenames + mtimes, so the register rebuilds on change."""
    sig = []
    for d in (PID_DIR, SCD_DIR):
        for f in sorted(list(Path(d).glob("*.PDF")) + list(Path(d).glob("*.pdf"))):
            sig.append((f.name, f.stat().st_mtime))
    return tuple(sig)


@st.cache_data(show_spinner="Building tag register from drawings…")
def build_register(signature: tuple) -> pd.DataFrame:
    rows = []
    for system, (pid_path, scd_path) in find_systems().items():
        try:
            pid = create_objects(extract_tags(str(pid_path)), "P&ID")
            scd = create_objects(extract_tags(str(scd_path)), "SCD")
        except Exception as e:  # noqa: BLE001
            st.warning(f"System {system}: extraction failed ({e})")
            continue
        by_tag = {o.tag: o for o in list(pid) + list(scd)}
        cons = check_consistency(pid, scd)
        for status, bucket in (("BOTH", "both"),
                               ("PID_ONLY", "pid_only"),
                               ("SCD_ONLY", "scd_only")):
            for t in cons.get(bucket, []):
                o = by_tag.get(t)
                type_code = getattr(o, "type_code", "?") if o else "?"
                rows.append({
                    "tag": t,
                    "system": system,
                    "type": type_code,
                    "category": getattr(o, "category", "other") if o else "other",
                    "status": status,
                    "status_label": STATUS_LABELS[status],
                    "safety": type_code in SAFETY_TYPES,
                    "pid_file": pid_path.name if status in ("BOTH", "PID_ONLY") else "",
                    "scd_file": scd_path.name if status in ("BOTH", "SCD_ONLY") else "",
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Small helpers (mirrors app.py's chip styling)
# --------------------------------------------------------------------------

def chips(tags, cat_by_tag) -> str:
    if not len(tags):
        return "_none_"
    out = ""
    for t in tags:
        c = CATEGORY_COLORS.get(cat_by_tag.get(t, "other"), "#9aa0a6")
        out += (f"<span style='background:{c};color:#fff;border-radius:20px;"
                f"padding:2px 8px;margin:2px;display:inline-block;"
                f"font-size:12px'>{t}</span> ")
    return out


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

from ui import page_header
page_header("Tag Register",
            "Every system with both a P&ID and an SCD · live extraction")
st.caption("All tags from all systems that have both a P&ID and an SCD — extracted "
           "live using the same modules as the rest of the app. A draft for "
           "engineering review, not an authoritative source.")

if not find_systems():
    st.error("Found no systems with both P&ID and SCD in data/raw/.")
    st.stop()

df = build_register(_dir_signature())
if df.empty:
    st.info("No tags were extracted.")
    st.stop()

cat_by_tag = dict(zip(df["tag"], df["category"]))

# ----- Sidebar filters ----------------------------------------------------
st.sidebar.header("Filters")
systems = sorted(df["system"].unique())
sel_systems = st.sidebar.multiselect("System", systems, default=systems,
                                     format_func=lambda s: f"System {s}")
types = sorted(df["type"].unique())
sel_types = st.sidebar.multiselect("Type", types)
status_opts = list(STATUS_LABELS.keys())
sel_status = st.sidebar.multiselect("Status", status_opts, default=status_opts,
                                    format_func=lambda s: STATUS_LABELS[s])
only_safety = st.sidebar.checkbox("Safety-related tags only")
query = st.sidebar.text_input("Search tag", placeholder="e.g., PT48 or XV")

view = df[df["system"].isin(sel_systems) & df["status"].isin(sel_status)]
if sel_types:
    view = view[view["type"].isin(sel_types)]
if only_safety:
    view = view[view["safety"]]
if query:
    view = view[view["tag"].str.contains(query, case=False, regex=False)]

# ----- Metrics ------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tags (selection)", len(view))
c2.metric("Systems", view["system"].nunique())
c3.metric("On both", int((view["status"] == "BOTH").sum()))
c4.metric("P&ID only", int((view["status"] == "PID_ONLY").sum()))
c5.metric("SCD only (verify)", int((view["status"] == "SCD_ONLY").sum()))

st.divider()

# ----- Charts -------------------------------------------------------------
left, right = st.columns((3, 2))

with left:
    st.subheader("Reconciliation per system")
    per_sys = view.groupby(["system", "status", "status_label"]).size() \
                  .reset_index(name="count")
    if per_sys.empty:
        st.info("No tags in the selection.")
    else:
        chart = (
            alt.Chart(per_sys).mark_bar().encode(
                x=alt.X("system:N", title="System", sort=systems),
                y=alt.Y("count:Q", title="Number of tags", stack=True),
                color=alt.Color("status:N",
                                scale=alt.Scale(domain=list(STATUS_COLORS),
                                                range=list(STATUS_COLORS.values())),
                                legend=alt.Legend(title="Status")),
                order=alt.Order("status:N"),
                tooltip=["system", "status_label", "count"],
            ).properties(height=340)
        )
        st.altair_chart(chart, use_container_width=True)

with right:
    st.subheader("Distribution by type")
    per_type = view.groupby("type").size().reset_index(name="count") \
                   .sort_values("count", ascending=False)
    if not per_type.empty:
        chart2 = (
            alt.Chart(per_type).mark_bar(color="#455a64").encode(
                x=alt.X("count:Q", title="Count"),
                y=alt.Y("type:N", sort="-x", title=""),
                tooltip=["type", "count"],
            ).properties(height=340)
        )
        st.altair_chart(chart2, use_container_width=True)

st.divider()

# ----- Table --------------------------------------------------------------
st.subheader(f"Tags ({len(view)})")
show = view[["tag", "system", "type", "category", "status_label", "safety",
             "pid_file", "scd_file"]].rename(columns={
    "tag": "Tag", "system": "System", "type": "Type", "category": "Category",
    "status_label": "Status", "safety": "Safety",
    "pid_file": "P&ID", "scd_file": "SCD"})
st.dataframe(show, use_container_width=True, hide_index=True, height=460)

st.download_button(
    "⬇️ Download selection as CSV",
    data=view.drop(columns=["status_label"]).to_csv(index=False).encode("utf-8"),
    file_name="tag_selection.csv", mime="text/csv")

# ----- Single-tag detail --------------------------------------------------
st.divider()
st.subheader("Look up a single tag")
picked = st.selectbox("Select tag", sorted(view["tag"].unique()))
rows = view[view["tag"] == picked]
r0 = rows.iloc[0]
d1, d2, d3 = st.columns(3)
d1.markdown("**Type**")
d1.markdown(chips([picked], cat_by_tag), unsafe_allow_html=True)
d1.caption(f"{r0['type']} · {r0['category']}"
           + ("  ·  ⚠ safety" if r0["safety"] else ""))
d2.markdown("**Systems**")
d2.write(", ".join(f"System {s}" for s in sorted(rows["system"].unique())))
d3.markdown("**Status**")
d3.write(", ".join(sorted(rows["status_label"].unique())))
pidf = sorted({f for f in rows["pid_file"] if f})
scdf = sorted({f for f in rows["scd_file"] if f})
st.markdown("**P&ID drawings:** " + (", ".join(pidf) if pidf else "_none_"))
st.markdown("**SCD drawings:** " + (", ".join(scdf) if scdf else "_none_"))