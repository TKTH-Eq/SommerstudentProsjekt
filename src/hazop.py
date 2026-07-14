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
from analysis.hazop_export import write_worksheet_xlsx, write_vision_xlsx
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

sel_all = st.checkbox(f"Velg alle noder i systemet ({len(nodes)})")
if sel_all:
    picked = nodes
    st.multiselect("Nodes (functional loops)", nodes, default=nodes,
                   disabled=True,
                   help="Alle noder valgt — fjern haken over for å velge manuelt.")
else:
    picked = st.multiselect("Nodes (functional loops)", nodes, default=nodes[:3])

# ---- editable worksheet with review status ---------------------------------
# Master copy lives in session state (per system) so edits survive reruns and
# node-filter changes; the editor shows a filtered view and edits are merged
# back by the stable row key (node, parameter, deviation).
KEY = ["node", "parameter", "deviation"]
state_key = f"hazop_master_{system}"
if state_key not in st.session_state:
    st.session_state[state_key] = pd.DataFrame(all_rows)
master: pd.DataFrame = st.session_state[state_key]

view = master[master["node"].isin(set(picked))] if picked else master.iloc[0:0]

if not view.empty:
    st.caption("Arbeidsarket er redigerbart: juster tekst, fyll inn "
               "anbefaling/ansvarlig og sett status per rad "
               "(proposed → reviewed/rejected). Endringer huskes i økten "
               "og følger med i eksporten.")
    edited = st.data_editor(
        view[["node", "parameter", "deviation", "causes", "consequences",
              "safeguards", "recommendation", "action_party", "status"]],
        use_container_width=True, hide_index=True, num_rows="fixed",
        disabled=["node", "parameter", "deviation"],
        column_config={
            "status": st.column_config.SelectboxColumn(
                "status", options=["proposed", "reviewed", "rejected"],
                required=True),
            "recommendation": st.column_config.TextColumn("recommendation"),
            "action_party": st.column_config.TextColumn("action party"),
        },
        key=f"editor_{system}")

    # merge the edited view back into the master by row key
    m = master.set_index(KEY)
    m.update(edited.set_index(KEY))
    st.session_state[state_key] = m.reset_index()[master.columns]
    rows_out = st.session_state[state_key].to_dict("records")

    c = st.session_state[state_key]["status"].value_counts().to_dict()
    st.caption(f"Status hele systemet: {c.get('proposed', 0)} proposed · "
               f"{c.get('reviewed', 0)} reviewed · {c.get('rejected', 0)} rejected")

    # ---- exports (full worksheet incl. edits, all nodes) -------------------
    out_dir = Path("reports"); out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / "hazop_worksheet.csv"
    write_worksheet_csv(rows_out, csv_path)
    xlsx_path = out_dir / f"hazop_system_{system}.xlsx"
    write_worksheet_xlsx(rows_out, xlsx_path,
                         title=f"HAZOP preparation — System {system}")
    d1, d2 = st.columns(2)
    d1.download_button("Last ned Excel-arbeidsark (per node)",
                       xlsx_path.read_bytes(), file_name=xlsx_path.name,
                       mime="application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet")
    d2.download_button("Last ned CSV (rå)", csv_path.read_bytes(),
                       file_name=f"hazop_system_{system}.csv", mime="text/csv")
    if st.button("Tilbakestill redigeringer for systemet"):
        del st.session_state[state_key]
        st.rerun()

    # optional AI passes — both gated on the Gemini key the project uses
    st.divider()
    if os.getenv("GEMINI_API_KEY"):
        node_ai = st.selectbox("AI-omskriving av én node", picked or nodes)
        if st.button("Generer AI-utkast for noden"):
            node_rows = [r for r in all_rows if r["node"] == node_ai]
            with st.spinner("Spør modellen…"):
                st.markdown(ai_enrich_node(node_rows))

        st.divider()
        st.subheader("👁️ Vision-utdrag fra selve tegningen")
        st.caption("Gemini SER på P&ID-en og foreslår HAZOP-observasjoner. "
                   "Hver tag den nevner verifiseres mot tag-registeret: "
                   "✅ finnes i uttrekket · 🟠 velformet men ikke uttrukket "
                   "(mulig symbol-only-funn — sjekk tegningen) · ❓ matcher "
                   "ikke kjent tagformat (mulig hallusinasjon). Krever "
                   "pypdfium2.")
        if st.button("Generer vision-utdrag for P&ID-en"):
            from ai.hazop_vision import vision_hazop_excerpt
            try:
                with st.spinner("Rasteriserer og spør Gemini…"):
                    st.session_state[f"vision_{system}"] = vision_hazop_excerpt(
                        Path(pid_path), [o.tag for o in objs])
            except ImportError as e:
                st.error(f"Mangler avhengighet: {e} — "
                         f"`uv add pypdfium2 google-genai`")
            except Exception as e:  # noqa: BLE001
                st.error(f"Vision-kallet feilet: {e}")

        # render + export from session state so the excerpt survives reruns
        # (any click, incl. a download button, reruns the whole page)
        ex = st.session_state.get(f"vision_{system}")
        if ex:
            from ai.hazop_vision import to_markdown
            st.markdown(to_markdown(ex))
            vx = Path("reports") / f"hazop_vision_system_{system}.xlsx"
            write_vision_xlsx(ex, vx,
                              title=f"Vision HAZOP excerpt — System {system}")
            st.download_button("Last ned vision-utdrag (Excel)",
                               vx.read_bytes(), file_name=vx.name,
                               mime="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")
    else:
        st.caption("Sett GEMINI_API_KEY for valgfri AI-omskriving og "
                   "vision-utdrag — arbeidsarket over er deterministisk og "
                   "komplett uten.")
if view.empty:
    st.info("Velg minst én node.")