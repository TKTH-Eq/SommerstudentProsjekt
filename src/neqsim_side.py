"""
src/neqsim_side.py  —  NeqSim simulation page

Registered by src/app.py via st.navigation:
    st.Page("neqsim_side.py", title="NeqSim simulation", icon="🧪"),

Two tabs, both grounded in the DEXPI export (data/processed/dexpi_tags.csv
etc., built by analysis/parse_dexpi_data.py — run that first if the CSVs
are missing):

  1. Fluid overview  — all fluid codes present in a DEXPI-covered drawing,
                       with NeqSim-computed density/Z-factor/molar mass per
                       fluid type. Reuses analysis/neqsim_system_report.py.
  2. Fault simulation — pick a component to "fail", see what gets isolated,
                       and (if it isolates something) the NeqSim hydrate
                       consequence for that segment's fluid. Reuses
                       analysis/simulate_component_failure.py.

NeqSim connectivity is DEXPI-only (see RESULTS.md / project notes): PDF-only
drawings carry no machine-readable fluid identification, so this page only
lists drawings that have a DEXPI XML.

Same pattern as hazop.py / tag_oversikt.py: a clear import-error message
if the modules or Java/NeqSim aren't available, instead of a raw traceback.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.spatial import cKDTree

try:
    from analysis.neqsim_system_report import (
        find_xml_for_drawing, summarize_fluid_codes, compute_neqsim_properties,
        RAW_DIR, PROCESSED_DIR,
    )
    from analysis.simulate_component_failure import (
        load_graph, simulate_failure, lookup_fluid_code,
    )
except Exception as e:  # noqa: BLE001
    st.title("🧪 NeqSim simulation")
    st.error(
        "Could not import NeqSim analysis modules "
        f"(analysis.neqsim_system_report / analysis.simulate_component_failure).\n\n"
        f"`{e}`\n\n"
        "Ensure these files are in `src/analysis/`, and that "
        "`neqsim_tools/` (with `fluid_lookup.py`) is in `src/`."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Component type classification — groups DEXPI objects into meaningful
# failure scenario categories, so the user selects TYPE first and only sees
# relevant components in the dropdown menu afterwards (instead of choosing
# freely among instruments, valves, pumps, pipe segments, etc. mixed together).
# ---------------------------------------------------------------------------

_VALVE_CLASSES = {"GateValve", "GlobeValve", "BallValve", "AngleValve",
                  "CheckValve", "PlugValve", "ButterflyValve", "NeedleValve"}


def classify_component_type(category: str, component_class: str) -> str:
    if category == "piping_component":
        if component_class in _VALVE_CLASSES:
            return "Valves"
        if component_class in {"Flange", "FlangedConnection", "PipeTee", "PipeReducer"}:
            return "Piping components (flange/reducer/tee)"
        if component_class == "FlowMeasuringElement":
            return "Flow measuring elements"
        return "Other piping components"
    if category == "piping_segment":
        return "Pipe segments"
    if category == "equipment":
        if component_class == "Pump":
            return "Pumps"
        if component_class == "Compressor":
            return "Compressors"
        return "Other equipment"
    if category in {"actuator", "actuating_system", "actuating_function"}:
        return "Actuators"
    if category in {"instrument", "instrument_loop", "signal_generator"}:
        return "Instruments"
    if category == "nozzle":
        return "Nozzles"
    if category in {"pipe_off_page", "signal_off_page"}:
        return "Off-page references"
    return "Other"


# Explains what the consequence number ACTUALLY means for each type — since a
# valve closing physically isolates a segment (hydrate consequence is directly
# relevant), while e.g. a failing instrument normally does NOT physically
# isolate a pipe segment in itself.
_TYPE_GUIDANCE = {
    "Valves": (
        "✅ **Most physically relevant type.** A closing valve directly "
        "isolates a pipe segment — the hydrate consequence below represents "
        "a real blowdown situation."
    ),
    "Pipe segments": (
        "✅ **Physically relevant.** A 'failing' pipe segment (e.g. rupture) "
        "can isolate the rest of the line in the same way as a closed valve."
    ),
    "Pumps": (
        "⚠️ **Different physics than the hydrate model assumes.** A pump stopping "
        "normally results in loss of pressure support/throughput, not necessarily "
        "an isolated, shut-in volume of gas. The isolation number below shows "
        "what is graphically cut off, but the hydrate calculation is less "
        "directly applicable than for a valve."
    ),
    "Compressors": (
        "⚠️ **Different physics than the hydrate model assumes** — same caveat "
        "as for pumps."
    ),
    "Instruments": (
        "⚠️ **Probably NOT physically relevant.** A failing instrument (meter/"
        "transmitter) normally does not stop physical throughput "
        "by itself — the consequence below is a structural isolation in the "
        "DATA graph, not necessarily a real process consequence, unless "
        "the instrument is part of an interlock that actually closes a "
        "valve."
    ),
    "Actuators": (
        "◐ **Partially relevant.** An actuator typically controls a valve — if "
        "it fails, the valve it operates can get stuck open/closed, "
        "which in turn can isolate a segment."
    ),
}
_DEFAULT_GUIDANCE = (
    "ℹ️ Physical relevance for the hydrate calculation has not been evaluated for this "
    "component type — interpret the consequence number with caution."
)


# ---------------------------------------------------------------------------
# Fluid families — groups the 25 fluid codes into intuitive categories, so
# the overview becomes scannable instead of a flat list of two-letter codes.
# The confidence level reflects the same assessment as in the report's source table
# (Table~\ref{tab:fluid_codes}) — not re-derived here, only reproduced.
# ---------------------------------------------------------------------------
_FLUID_FAMILY = {
    "PV": ("🔥 Gas", "Moderate"), "VF": ("🔥 Gas", "Moderate"),
    "VA": ("🔥 Gas", "Moderate"), "OF": ("🔥 Gas", "Low"),
    "GI": ("🔥 Gas", "Low–moderate"), "GF": ("🔥 Gas", "Low–moderate"),
    "GE": ("🔥 Gas", "Moderate"), "PT": ("🔥 Gas", "Low"),
    "PI": ("🔥 Gas", "Very low"),
    "PL": ("💧 Liquid/oil", "Moderate"), "OL": ("💧 Liquid/oil", "Low–moderate"),
    "OH": ("💧 Liquid/oil", "Low–moderate"), "CG": ("💧 Liquid/oil", "Low"),
    "WS": ("🌊 Water", "Low–moderate"), "WD": ("🌊 Water", "Low–moderate"),
    "WF": ("🌊 Water", "Low–moderate"), "WI": ("🌊 Water", "Moderate"),
    "WC": ("🌊 Water", "Low–moderate"),
    "AI": ("💨 Air", "Moderate"), "AP": ("💨 Air", "Low–moderate"),
    "CA": ("💨 Air", "Moderate"),
    "CC": ("🧪 Chemical", "Low"), "MK": ("🧪 Chemical", "Low–moderate"),
    "DC": ("🚰 Drainage", "Moderate"), "DO": ("🚰 Drainage", "Moderate"),
}


@st.cache_data(show_spinner="Linking components to fluid codes…")
def bulk_assign_fluid_codes(_xml_path: str, sub: pd.DataFrame) -> pd.DataFrame:
    """
    Fast version of lookup_fluid_code(): instead of parsing the XML
    again for EACH component (121ms per call — too slow for 100+ objects),
    the file is parsed ONLY ONCE, and all named components are linked to
    the nearest pipe segment in one combined geometric search (typically <100ms total,
    tested against real data).

    Returns the sub-copy with two new columns: 'nearest_fluid_code' and
    'dist_to_segment_mm'. Components without any pipe segment nearby (or
    on drawings without segment positions) get NaN.
    """
    root = ET.parse(_xml_path).getroot()

    def attr(el, name):
        for ga in el.findall("./GenericAttributes/GenericAttribute"):
            if ga.get("Name") == name:
                return ga.get("Value")
        return None

    seg_fluid_code = {}
    for el in root.iter("PipingNetworkSegment"):
        code = attr(el, "FluidCodeAssignmentClass")
        if code:
            seg_fluid_code[el.get("ID")] = code

    out = sub.copy()
    out["nearest_fluid_code"] = None
    out["dist_to_segment_mm"] = np.nan
    if not seg_fluid_code:
        return out

    positioned = out.dropna(subset=["x_mm", "y_mm"])
    segs = positioned[positioned["id"].isin(seg_fluid_code.keys())].copy()
    if segs.empty:
        return out
    segs["fluid_code"] = segs["id"].map(seg_fluid_code)
    # segments have their OWN known code (distance 0 — not derived/nearest-neighbor)
    out.loc[segs.index, "nearest_fluid_code"] = segs["fluid_code"].values
    out.loc[segs.index, "dist_to_segment_mm"] = 0.0

    tree = cKDTree(segs[["x_mm", "y_mm"]].values)
    named = positioned[positioned["tag_name"].notna() & ~positioned["id"].isin(seg_fluid_code.keys())]
    if named.empty:
        return out
    dists, idxs = tree.query(named[["x_mm", "y_mm"]].values, k=1)
    codes = segs.iloc[idxs]["fluid_code"].values

    out.loc[named.index, "nearest_fluid_code"] = codes
    out.loc[named.index, "dist_to_segment_mm"] = dists
    return out


# Fixed colors per fluid code, consistent per family (same visual logic
# as CATEGORY_COLORS in app_failure_explorer.py — each code gets a unique
# shade within the family's color palette).
_CODE_COLORS = {
    "PV": "#E8640F", "VF": "#F2984D", "VA": "#F7B87A", "OF": "#C94F00",
    "GI": "#D9773A", "GF": "#C25E1F", "GE": "#A84A0F", "PT": "#FFAD6B", "PI": "#FFCBA0",
    "PL": "#16233A", "OL": "#3E5A8C", "OH": "#2C4269", "CG": "#5C79A8",
    "WS": "#2E7D5B", "WD": "#4FA37F", "WF": "#7BC4A3", "WI": "#1E5E42", "WC": "#3F8F68",
    "AI": "#9AA0AC", "AP": "#BFC4CC", "CA": "#7B8290",
    "CC": "#7A3FB0", "MK": "#A375CC",
    "DC": "#A93A3A", "DO": "#C96666",
}


def plot_fluid_map(sub_full: pd.DataFrame, assigned: pd.DataFrame,
                   highlight_code: str | None = None) -> go.Figure:
    """
    Full-drawing map: every point on the drawing colored by the fluid code
    it (or the nearest pipe segment) has. Answers "where in the system
    does this happen" — same basic principle as the topology plots in
    app_failure_explorer.py / the DEXPI topology page, just colored by
    fluid code instead of object category.

    highlight_code: if set, everything EXCEPT this code is dimmed, so the
    selected fluid code clearly stands out on the full drawing.
    """
    pos = {row["id"]: (row["x_mm"], row["y_mm"]) for _, row in sub_full.iterrows()
           if pd.notna(row.get("x_mm"))}

    traces = []
    coded = assigned.dropna(subset=["nearest_fluid_code", "x_mm", "y_mm"])
    uncoded = assigned[assigned["nearest_fluid_code"].isna() & assigned["x_mm"].notna()]

    if not uncoded.empty:
        traces.append(go.Scatter(
            x=uncoded["x_mm"], y=uncoded["y_mm"], mode="markers",
            name="Unknown/no fluid code",
            marker=dict(size=4, color="#3A3F4B"),
            hovertext=uncoded["tag_name"].fillna(uncoded["category"]), hoverinfo="text",
            opacity=0.35,
        ))

    for code, grp in coded.groupby("nearest_fluid_code"):
        dimmed = highlight_code is not None and code != highlight_code
        traces.append(go.Scatter(
            x=grp["x_mm"], y=grp["y_mm"], mode="markers",
            name=str(code),
            marker=dict(size=7 if not dimmed else 5,
                       color=_CODE_COLORS.get(code, "#9AA0AC"),
                       line=dict(width=0.5, color="white")),
            hovertext=grp["tag_name"].fillna(grp["category"]) + " · " + grp["nearest_fluid_code"],
            hoverinfo="text",
            opacity=1.0 if not dimmed else 0.15,
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        height=480, hovermode="closest", plot_bgcolor="#FAFAF7",
        xaxis=dict(visible=False), yaxis=dict(visible=False, autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10)),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


@st.cache_data(show_spinner="Calculating consequence for all components on the drawing…")
def rank_failure_impacts(_G, sub: pd.DataFrame, drawing: str) -> pd.DataFrame:
    """
    Runs simulate_failure() for EVERY named component on the drawing, and
    ranks them by how many objects are isolated. Fast (typically <1s
    for a whole drawing, ~3ms per component) since each simulation only
    copies and removes one node from an already loaded graph.

    The solution to "randomly selected components mostly yield 0 affected":
    typically, fewer than HALF the components yield a visible consequence (the rest
    have 0 registered connections in the DEXPI data, see the data quality caveat
    elsewhere on the page). By ranking in advance and showing the most
    critical ones first, the user avoids "guessing blindly" and hitting the
    boring cases repeatedly.
    """
    named = sub[sub["tag_name"].notna()].copy()
    named["type_group"] = named.apply(
        lambda r: classify_component_type(r["category"], r["component_class"]), axis=1
    )
    rows = []
    for _, row in named.iterrows():
        tag = row["tag_name"]
        try:
            r = simulate_failure(_G, sub, tag)
        except ValueError:
            continue
        rows.append({
            "tag_name": tag,
            "type_group": row["type_group"],
            "n_affected": len(r["affected_ids"]),
            "own_degree": _G.degree(r["fail_id"]),
        })
    return pd.DataFrame(rows).sort_values("n_affected", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading DEXPI tag register…")
def load_dexpi_tables():
    tags_path = PROCESSED_DIR / "dexpi_tags.csv"
    if not tags_path.exists():
        return None, None, None
    tags = pd.read_csv(tags_path)
    conns_path = PROCESSED_DIR / "dexpi_connections.csv"
    assocs_path = PROCESSED_DIR / "dexpi_associations.csv"
    conns = pd.read_csv(conns_path) if conns_path.exists() else pd.DataFrame()
    assocs = pd.read_csv(assocs_path) if assocs_path.exists() else pd.DataFrame()
    return tags, conns, assocs


@st.cache_data(show_spinner="Calculating fluid properties (NeqSim)…")
def cached_properties(fluid_codes: tuple[str, ...], pressure: float, temperature: float):
    return compute_neqsim_properties(list(fluid_codes), pressure, temperature)


tags_all, conns_all, assocs_all = load_dexpi_tables()

from ui import page_header
page_header("NeqSim simulation",
            "DEXPI topology → NeqSim physics via FluidCodeAssignmentClass")
st.caption(
    "Connects the DEXPI topology to physical NeqSim calculations via "
    "`FluidCodeAssignmentClass`. Only drawings with a DEXPI export are supported — "
    "standard PDF drawings have no machine-readable fluid identification."
)

if tags_all is None:
    st.error(
        "Could not find `data/processed/dexpi_tags.csv`. Run this first:\n\n"
        "```\npython -m analysis.parse_dexpi_data\n```\n\nfrom the `src/` folder."
    )
    st.stop()

drawings = sorted(tags_all["drawing"].unique())
if not drawings:
    st.warning("No DEXPI drawings found in the tag register.")
    st.stop()

st.sidebar.title("NeqSim simulation")
drawing = st.sidebar.selectbox("Drawing (DEXPI-covered only)", drawings)
pressure = st.sidebar.number_input("Representative pressure [bara]", value=60.0, step=5.0,
                                   help="The DEXPI export does not contain actual operating pressure — "
                                        "this is an assumed value you can adjust.")
temperature = st.sidebar.number_input("Representative temperature [°C]", value=20.0, step=5.0)

tab1, tab2 = st.tabs(["🧯 Fluid overview", "🎯 Fault simulation + hydrate consequence"])


# ---------------------------------------------------------------------------
# Tab 1: fluid overview for the entire drawing
# ---------------------------------------------------------------------------

with tab1:
    xml_path = find_xml_for_drawing(drawing)
    if xml_path is None:
        st.error(f"Found no DEXPI XML file for '{drawing}' under {RAW_DIR}.")
        st.stop()

    summary = summarize_fluid_codes(xml_path)
    if summary.empty:
        st.info("No fluid codes found in this drawing.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Unique fluid codes", len(summary))
        c2.metric("Pipe segments with fluid code", int(summary["n_segments"].sum()))

        # --- Bulk-linking: which NAMED components (valves, instruments...)
        #     belong to each fluid code? Fast (<100ms), unlike
        #     lookup_fluid_code() which parses the XML per component. ---
        G_dummy, sub_full = load_graph(tags_all, conns_all, assocs_all, drawing)
        assigned = bulk_assign_fluid_codes(str(xml_path), sub_full)
        assigned["type_group"] = assigned.apply(
            lambda r: classify_component_type(r["category"], r["component_class"])
            if pd.notna(r.get("category")) else None, axis=1
        )

        st.divider()
        st.subheader("🗺️ Where in the system are the different fluid codes found?")
        st.caption(
            "The entire drawing, each point colored by the nearest fluid code. "
            "Pipe segments have their own registered code; other components "
            "(valves, instruments) are colored by the nearest pipe segment."
        )
        st.plotly_chart(plot_fluid_map(sub_full, assigned), use_container_width=True)

        st.subheader("🧭 Fluid codes in the drawing — what they are, and where they are found")
        st.caption(
            "Each box is one fluid code found in the DEXPI data. Expand to see "
            "description, confidence level of the interpretation, which named "
            "components are closest, and where exactly THIS code "
            "is located on the drawing (the rest is dimmed)."
        )

        try:
            from neqsim_tools.fluid_lookup import get_preset
        except Exception:
            get_preset = None

        for _, row in summary.iterrows():
            code = row["fluid_code"]
            family, confidence = _FLUID_FAMILY.get(code, ("❓ Unknown family", "Unknown"))
            preset = get_preset(code) if get_preset else None
            desc = preset["description"] if preset else "(description unavailable)"

            nearby = assigned[assigned["nearest_fluid_code"] == code]
            nearby_close = nearby[nearby["dist_to_segment_mm"] < 50]  # kun rimelig naere treff

            header = (f"{family}   **{code}**   ·   {row['n_segments']} segments, "
                     f"{row['n_unique_lines']} line(s)   ·   Confidence: {confidence}")
            with st.expander(header):
                st.markdown(f"**Assumed meaning:** {desc}")
                colA, colB, colC = st.columns(3)
                colA.metric("Pipe segments", int(row["n_segments"]))
                colB.metric("Typical diameter", f"{row['typical_diameter']}\"")
                colC.metric("Piping class(es)", row["piping_classes"])

                if not nearby_close.empty:
                    st.markdown("**Nearby named components** (grouped by type):")
                    for tg, grp in nearby_close.groupby("type_group"):
                        chips = ", ".join(f"`{t}`" for t in sorted(grp["tag_name"].dropna().unique())[:12])
                        extra = "" if grp["tag_name"].nunique() <= 12 else f" … (+{grp['tag_name'].nunique()-12} more)"
                        st.markdown(f"- **{tg}** ({grp['tag_name'].nunique()} total): {chips}{extra}")
                else:
                    st.caption("No named components found geometrically near a "
                              "segment with this fluid code (could be due to the same "
                              "connection gap described in the DEXPI caveat).")

                st.markdown(f"**Where on the drawing `{code}` is located:**")
                st.plotly_chart(plot_fluid_map(sub_full, assigned, highlight_code=code),
                                use_container_width=True, key=f"map_{code}")

        st.divider()
        st.subheader("Distribution of pipe segments per fluid code")
        chart_df = summary.copy()
        chart_df["Family"] = chart_df["fluid_code"].map(lambda c: _FLUID_FAMILY.get(c, ("❓",""))[0])
        st.bar_chart(chart_df.set_index("fluid_code")["n_segments"])

        st.subheader(f"NeqSim properties at {pressure:.0f} bara / {temperature:.0f} °C")
        with st.spinner("Running NeqSim (JVM may take a few seconds on first call)…"):
            try:
                props = cached_properties(tuple(summary["fluid_code"]), pressure, temperature)
            except Exception as e:  # noqa: BLE001
                props = pd.DataFrame()
                st.error(f"NeqSim/JVM error: {e}")

        if not props.empty:
            st.dataframe(props, use_container_width=True, hide_index=True)
            if props["density_kg_m3"].notna().any():
                st.bar_chart(props.set_index("fluid_code")["density_kg_m3"])
            if (~props["matched"]).any():
                unknowns = ", ".join(props[~props["matched"]]["fluid_code"])
                st.warning(f"Fluid code(s) without explicit preset (using standard gas): {unknowns}")
        st.caption(
            "⚠️ Fluid code → composition is **assumed** (Norwegian Continental Shelf convention), "
            "not verified against a Huldra-specific line list — see "
            "`neqsim_tools/fluid_lookup.py`. Pressure/temperature are representative "
            "values, not actual operating data (does not exist in the DEXPI export)."
        )


# ---------------------------------------------------------------------------
# Tab 2: fault simulation + hydrate consequence for the affected segment
# ---------------------------------------------------------------------------

with tab2:
    G, sub = load_graph(tags_all, conns_all, assocs_all, drawing)
    named = sub[sub["tag_name"].notna()].copy()
    if named.empty:
        st.info("No named components on this drawing.")
        st.stop()

    # --- Pre-calculated ranking: the most critical components first,
    #     so the user avoids clicking through boring "0 affected"
    #     cases to find something interesting. ---
    ranking = rank_failure_impacts(G, sub, drawing)
    n_critical = (ranking["n_affected"] > 0).sum()

    st.subheader("🏆 Most critical components on this drawing")
    st.caption(
        f"{n_critical} out of {len(ranking)} components isolate at least one other "
        f"object if they fail. Pre-calculated for the entire drawing — "
        f"select one of them below for full detail and hydrate consequence."
    )
    top10 = ranking[ranking["n_affected"] > 0].head(10)
    if not top10.empty:
        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            st.bar_chart(top10.set_index("tag_name")["n_affected"])
        with col_table:
            st.dataframe(
                top10[["tag_name", "type_group", "n_affected"]],
                use_container_width=True, hide_index=True, height=380,
            )
    else:
        st.info("No components on this drawing isolate anything according to the "
                "explicit DEXPI connections — see the data quality caveat at the bottom.")

    st.divider()

    named["type_group"] = named.apply(
        lambda r: classify_component_type(r["category"], r["component_class"]), axis=1
    )
    impact_by_tag = dict(zip(ranking["tag_name"], ranking["n_affected"]))
    type_max_impact = named["type_group"].map(
        lambda t: ranking[ranking["type_group"] == t]["n_affected"].max()
    )
    counts = named["type_group"].value_counts()
    max_by_type = ranking.groupby("type_group")["n_affected"].max()
    type_options = [
        f"{t} ({counts[t]} total, up to {int(max_by_type.get(t, 0))} affected)"
        for t in counts.index
    ]
    type_display_to_raw = {opt: t for opt, t in zip(type_options, counts.index)}

    chosen_display = st.selectbox(
        "1️⃣ Type of component to fail",
        type_options,
        help="Select WHICH TYPE of component first — the dropdown menu below "
             "is then filtered to only show components of this type, "
             "sorted with the most critical first."
    )
    chosen_type = type_display_to_raw[chosen_display]
    st.caption(_TYPE_GUIDANCE.get(chosen_type, _DEFAULT_GUIDANCE))

    # sort by ACTUAL consequence (most critical first), not alphabetically
    group_tags = named[named["type_group"] == chosen_type]["tag_name"].unique()
    sorted_tags = sorted(group_tags, key=lambda t: -impact_by_tag.get(t, 0))
    tag_options = [f"{t} ({impact_by_tag.get(t, 0)} affected)" for t in sorted_tags]
    tag_display_to_raw = {opt: t for opt, t in zip(tag_options, sorted_tags)}

    chosen_tag_display = st.selectbox("2️⃣ Component", ["(none selected)"] + tag_options)

    if chosen_tag_display == "(none selected)":
        st.caption("Select a component above to simulate a failure and see the hydrate consequence.")
        st.stop()
    fail_tag = tag_display_to_raw[chosen_tag_display]

    try:
        result = simulate_failure(G, sub, fail_tag)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    own_degree = G.degree(result["fail_id"])
    n_affected = len(result["affected_ids"])

    if own_degree <= 1:
        st.error(
            f"📉 **Data quality:** `{fail_tag}` has only {own_degree} registered "
            "connection(s) in the DEXPI data. A low/zero result often means that "
            "the connection is missing in the data, not that the component actually hangs freely."
        )
    else:
        st.caption(f"`{fail_tag}` has {own_degree} registered connections in the dataset.")

    if n_affected == 0:
        st.info("No other objects are isolated by this failure according to the explicit "
                "DEXPI connections — no segment to calculate hydrate consequence for.")
        st.stop()

    st.warning(
        f"⚠️ **{n_affected} objects** isolated: " +
        ", ".join(f"`{t}`" for t in result["affected_tags"]["tag_name"])
    )

    st.subheader("NeqSim: hydrate risk upon blowdown of the isolated segment")

    with st.expander("ℹ️ For which fluid codes does the hydrate calculation actually yield a result?"):
        try:
            from neqsim_tools.fluid_lookup import FLUID_PRESETS
            overview = []
            for code, preset in FLUID_PRESETS.items():
                comps = {c for c, _ in preset["components"]}
                has_water = "water" in comps
                has_hc = any(c in comps for c in
                            ["methane", "ethane", "propane", "i-butane", "n-butane"])
                overview.append({
                    "Fluid code": code,
                    "Hydrate calculation possible?": "✅ Yes" if (has_water and has_hc) else "❌ No",
                    "Why": ("Has both water and hydrocarbon gas" if (has_water and has_hc)
                           else "Missing water" if not has_water
                           else "Missing hydrocarbon gas (e.g. pure air/oil)"),
                })
            st.dataframe(pd.DataFrame(overview), use_container_width=True, hide_index=True)
            st.caption(
                "Hydrate formation requires BOTH water AND light hydrocarbons to be present "
                "simultaneously. Pure water systems (WS/WD/WF/WI/WC/MK) and pure air "
                "(AI/AP/CA) therefore correctly yield 'No' — it is not an error, "
                "it is physically expected."
            )
        except Exception:
            st.caption("(Could not load the fluid code overview)")

    xml_path = find_xml_for_drawing(drawing)
    with st.spinner("Looking up fluid code and running NeqSim…"):
        try:
            fluid_code = lookup_fluid_code(xml_path, sub, result["fail_id"]) if xml_path else None
        except Exception as e:  # noqa: BLE001
            fluid_code = None
            st.caption(f"(Could not look up fluid code automatically: {e})")

        try:
            from neqsim_tools.fluid_lookup import get_preset, build_neqsim_fluid
            from neqsim.thermo import hydt

            preset = get_preset(fluid_code)
            rows = []
            for p in (90.0, 30.0, 10.0):
                f = build_neqsim_fluid(preset)
                f.setPressure(p, "bara")
                f.setTemperature(10.0, "C")
                try:
                    hydt(f)
                    rows.append({"Pressure [bara]": p,
                                "Hydrate temperature [°C]": round(f.getTemperature("C"), 1)})
                except Exception:
                    rows.append({"Pressure [bara]": p, "Hydrate temperature [°C]": None})

            match_note = (f"fluid code '{preset['code']}' found in DEXPI data"
                          if preset["matched"] else "no fluid code found — using standard gas")
            st.caption(f"Fluid: **{preset['description']}**  ({match_note})")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(
                "If the segment's actual temperature is below the values above at "
                "the given pressure, there is a risk of hydrate formation during "
                "isolation/blowdown. Composition is assumed — see caveat in tab 1."
            )
        except ImportError:
            st.error("NeqSim is not installed/available here. Run: `pip install neqsim`")
        except Exception as e:  # noqa: BLE001
            st.error(f"NeqSim/JVM error: {e}")