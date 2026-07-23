"""
src/hazop.py  —  HAZOP preparation page

Registered by src/app.py via st.navigation:
    st.Page("hazop.py", title="HAZOP-forberedelse", icon="⚠️"),

Thin shell over analysis/hazop_prep.py — same pattern as system_analysis.py:
pick a system, the pipeline runs (cached), pick nodes, get a pre-filled
HAZOP worksheet grounded in the extracted tags. Optional AI rewriting per
node when ANTHROPIC_API_KEY is set; the deterministic worksheet is always
the fallback and the source of truth.

Worksheet edits persist across sessions: the master is autosaved to
reports/hazop_store/ (analysis/hazop_store.py) on every edit, and reloaded
on the next visit. A stored worksheet is a snapshot of the extraction it was
built from; the reset button discards it and rebuilds from the current
extraction.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st

from dotenv import load_dotenv
load_dotenv()  # eksplisitt: GEMINI_API_KEY-gaten under avhenger av .env,
               # og skal ikke lene seg på at en annen import lastet den

from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph
from analysis.hazop_prep import build_worksheet, hazop_nodes, write_worksheet_csv, ai_enrich_node
from analysis.hazop_export import write_worksheet_xlsx, write_vision_xlsx
from analysis.hazop_store import (load_worksheet, save_worksheet,
                                  list_worksheets, delete_worksheet)
from utils.discovery import find_systems  # reuse discovery — one source of truth


@st.cache_data(show_spinner=False)
def _png_b64(path: str, mtime: float) -> str:
    import base64
    return base64.b64encode(Path(path).read_bytes()).decode()


def _zoomable_image(png_path: str, height: int = 620, markers=None):
    """Inline pan/zoom viewer (scrollhjul = zoom mot pekeren, dra = panorer,
    dobbeltklikk = tilbakestill). Ingen ekstra avhengigheter — ren HTML/JS i
    en components-iframe, samme teknikk som DEXPI-demoen."""
    import streamlit.components.v1 as components
    b64 = _png_b64(png_path, Path(png_path).stat().st_mtime)
    # markører i BILDE-prosent (skalerer med bredden uansett zoom):
    marker_html = ""
    if markers:
        from PIL import Image
        iw, ih = Image.open(png_path).size
        for m in markers:
            # 6-tuple (x, y, w, h, color, label) as before; an optional 7th
            # element -> dashed border (used for estimated positions).
            mx, my, mw, mh, color, label = m[:6]
            dashed = len(m) > 6 and m[6]
            # CSS: left/width i % av BREDDEN, top/height i % av HØYDEN —
            # wrap-diven har nøyaktig bildets proporsjoner (img display:block)
            l, t = 100 * mx / iw, 100 * my / ih
            w_, h_ = 100 * mw / iw, 100 * mh / ih
            style = "dashed" if dashed else "solid"
            marker_html += (
                f'<div title="{label}" style="position:absolute;'
                f'left:{l:.2f}%;top:{t:.2f}%;width:{w_:.2f}%;'
                f'height:{h_:.2f}%;border:2px {style} {color};'
                f'border-radius:3px;box-shadow:0 0 6px {color};'
                f'pointer-events:auto"></div>')
    components.html(f"""
<div id="vp" style="width:100%;height:{height - 20}px;overflow:hidden;
     border:1px solid #444;border-radius:8px;background:#1a1a1a;
     cursor:grab;position:relative;user-select:none">
  <div id="wrap" style="transform-origin:0 0;position:absolute;left:0;top:0;
       width:100%">
    <img id="im" src="data:image/png;base64,{b64}" draggable="false"
         style="max-width:none;width:100%;display:block"/>
    {marker_html}
  </div>
  <div style="position:absolute;right:8px;bottom:8px;color:#aaa;
       font:11px sans-serif;background:#0008;padding:3px 8px;
       border-radius:6px;pointer-events:none">
    scroll = zoom &nbsp;·&nbsp; dra = panorer &nbsp;·&nbsp; dobbeltklikk = reset
  </div>
</div>
<script>
const vp=document.getElementById("vp"),im=document.getElementById("wrap");
let s=1,tx=0,ty=0,drag=false,sx=0,sy=0;
function apply(){{im.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;}}
vp.addEventListener("wheel",e=>{{
  e.preventDefault();
  const r=vp.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.25:0.8,ns=Math.min(Math.max(s*f,0.5),40);
  tx=mx-(mx-tx)*(ns/s); ty=my-(my-ty)*(ns/s); s=ns; apply();
}},{{passive:false}});
vp.addEventListener("mousedown",e=>{{drag=true;sx=e.clientX-tx;sy=e.clientY-ty;
  vp.style.cursor="grabbing";}});
window.addEventListener("mousemove",e=>{{if(!drag)return;
  tx=e.clientX-sx;ty=e.clientY-sy;apply();}});
window.addEventListener("mouseup",()=>{{drag=false;vp.style.cursor="grab";}});
vp.addEventListener("dblclick",()=>{{s=1;tx=0;ty=0;apply();}});
</script>""", height=height)


systems = find_systems()
st.sidebar.title("HAZOP preparation")
if not systems:
    st.error("No system found with both a P&ID and an SCD in data/raw/.")
    st.stop()

system = st.sidebar.selectbox("System", list(systems), format_func=lambda s: f"System {s}")
pid_path, scd_path = systems[system]

# lagrede arbeidsark på tvers av systemer — synlig bevis på at arbeidet
# overlever økten (og hvilke systemer som har påbegynt HAZOP-forberedelse)
_stored_all = list_worksheets()
if _stored_all:
    with st.sidebar.expander(f"💾 Saved worksheets ({len(_stored_all)})"):
        for w in _stored_all:
            st.caption(f"**{w['key']}** — last {str(w['saved_at'])[:16]} "
                       f"({w['n_saves']} save(s))")


@st.cache_resource(show_spinner="Building worksheet…")
def load(system: str, pid: str, scd: str):
    objs = sorted(set(create_objects(extract_tags(pid), "P&ID"))
                  | set(create_objects(extract_tags(scd), "SCD")), key=lambda o: o.tag)
    g = build_graph(objs)
    return objs, g, build_worksheet(g, objs)


objs, g, all_rows = load(system, str(pid_path), str(scd_path))

from config import PID_DIR
from ui import chips as _ui_chips, page_header


def _chips(tags):
    by = {o.tag: o for o in objs}
    return _ui_chips(tags, by)


page_header(f"System {system} — HAZOP preparation",
            f"P&ID {Path(pid_path).stem[-14:]} · SCD "
            f"{Path(scd_path).stem[-14:]} · {len(objs)} tags in the extraction")
st.caption("Pre-filled worksheet from AI-extracted P&ID/SCD data. Nodes are "
           "functional loops (real HAZOP nodes are process sections — that "
           "requires DEXPI, see the ⚖️ page). Every referenced tag exists in "
           "the extraction; nothing is invented. For HAZOP-team review — "
           "not a completed study.")

nodes = sorted({r["node"] for r in all_rows})
if not nodes:
    st.warning("No loop in this system has instruments yielding a process "
               "parameter — nothing to propose.")
    st.stop()

# ---- master worksheet: load stored (survives sessions) or build fresh ------
# The master lives in session state during the session and in
# reports/hazop_store/system_<N>.json between sessions. A stored worksheet
# is a SNAPSHOT of the extraction it was built from; the reset button at the
# bottom of the ark tab discards it and rebuilds from the current extraction.
KEY = ["node", "parameter", "deviation"]
_COLS = list(all_rows[0].keys())
state_key = f"hazop_master_{system}"
_store_key = f"system_{system}"
if state_key not in st.session_state:
    _stored = load_worksheet(_store_key)
    if _stored and _stored.get("data"):
        _df = pd.DataFrame(_stored["data"])
        if set(_COLS) <= set(_df.columns):          # kolonner intakte
            st.session_state[state_key] = _df[_COLS]
            st.session_state[f"hazop_meta_{system}"] = _stored.get("meta", {})
        else:                                        # gammelt format -> nytt ark
            st.session_state[state_key] = pd.DataFrame(all_rows)
    else:
        st.session_state[state_key] = pd.DataFrame(all_rows)
_meta = st.session_state.get(f"hazop_meta_{system}")
if _meta:
    st.caption(f"💾 Loaded saved worksheet — last saved "
               f"{str(_meta.get('saved_at', '?'))[:16]} "
               f"({_meta.get('n_saves', '?')} save(s)). A saved worksheet is a "
               f"snapshot of the extraction it was built from; the reset "
               f"button at the bottom rebuilds from the current "
               f"extraction.")

# nøkkeltall for hele systemet (master — lagret ark om det finnes)
_df_all = st.session_state[state_key]
_n_rows = len(_df_all)
_with_sg = int((~_df_all["safeguards"].str.startswith("(none")).sum())
_done = int((_df_all["status"] != "proposed").sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Nodes", len(nodes),
          help="Functional loops with at least one process parameter.")
m2.metric("Deviation rows", _n_rows,
          help="One row per (node, guideword deviation).")
m3.metric("Rows with a found safeguard", f"{_with_sg}/{_n_rows}",
          help="Deviation rows where at least one real, extracted safeguard "
               "tag was identified. The gap is where the preparation work "
               "lies — and where the 55 % recall ceiling costs (see ⚖️).")
m4.metric("Reviewed", f"{_done}/{_n_rows}",
          help="Rows set to reviewed or rejected in the worksheet.")
st.progress(_done / _n_rows if _n_rows else 0.0)

tab_ark, tab_vision, tab_funn, tab_ai = st.tabs(
    ["📋 Worksheet", "👁️ Vision excerpt", "📐 Rule findings on the drawing",
     "🤖 AI draft per node"])

with tab_ark:
    f1, f2 = st.columns([2, 1])
    with f1:
        sel_all = st.checkbox(f"Select every node in the system ({len(nodes)})")
        if sel_all:
            picked = nodes
            st.multiselect("Nodes (functional loops)", nodes, default=nodes,
                           disabled=True,
                           help="All nodes selected — untick for manual choice.")
        else:
            picked = st.multiselect("Nodes (functional loops)", nodes,
                                    default=nodes[:3])
    with f2:
        only_gap = st.toggle("Only rows without a found safeguard",
                             help="Filter to the deviations that lack an "
                                  "identified safeguard — these are the ones "
                                  "a HAZOP team must spend time on.")
        status_f = st.multiselect("Status", ["proposed", "reviewed", "rejected"],
                                  default=["proposed", "reviewed", "rejected"])

    if picked:
        with st.expander("Components in the selected nodes"):
            by_node_rows = pd.DataFrame(all_rows)
            for nd in picked:
                mem = by_node_rows[by_node_rows["node"] == nd]["node_members"]
                tags = sorted(set(mem.iloc[0].split(", "))) if len(mem) else []
                st.markdown(f"**{nd}**  \n" + _chips(tags),
                            unsafe_allow_html=True)

# ---- editable worksheet with review status ---------------------------------
# Master copy lives in session state (per system) so edits survive reruns and
# node-filter changes; the editor shows a filtered view and edits are merged
# back by the stable row key (node, parameter, deviation). Every change is
# autosaved to reports/hazop_store/ so it also survives closing the tab.
master: pd.DataFrame = st.session_state[state_key]

view = master[master["node"].isin(set(picked))] if picked else master.iloc[0:0]
if not view.empty and only_gap:
    view = view[view["safeguards"].str.startswith("(none")]
if not view.empty and status_f:
    view = view[view["status"].isin(status_f)]

with tab_ark:
 if not view.empty:
    st.caption("Editable: adjust text, fill in recommendation/action party and "
               "set status per row. Changes autosave to disk and survive "
               "closing the tab — including rows that are currently "
               "filtered out.")
    edited = st.data_editor(
        view[["node", "parameter", "deviation", "causes", "consequences",
              "safeguards", "recommendation", "action_party", "status"]],
        use_container_width=True, hide_index=True, num_rows="fixed",
        disabled=["node", "parameter", "deviation"],
        column_config={
            "node": st.column_config.TextColumn("node", width="small"),
            "parameter": st.column_config.TextColumn("param.", width="small"),
            "deviation": st.column_config.TextColumn(
                "deviation", width="small",
                help="Guideword deviation (High/Low/No/Reverse …)"),
            "causes": st.column_config.TextColumn(
                "causes", width="large",
                help="Failure modes of the loop's control elements (real tags) "
                     "+ generic process causes marked (generic)."),
            "consequences": st.column_config.TextColumn(
                "consequences", width="large"),
            "safeguards": st.column_config.TextColumn(
                "safeguards", width="medium",
                help="Only tags that actually exist in the extraction. "
                     "\u00ab(none found)\u00bb means: not in the text layer — check the drawing."),
            "recommendation": st.column_config.TextColumn("recommendation",
                                                          width="medium"),
            "action_party": st.column_config.TextColumn("action party",
                                                        width="small"),
            "status": st.column_config.SelectboxColumn(
                "status", options=["proposed", "reviewed", "rejected"],
                required=True, width="small"),
        },
        key=f"editor_{system}")

    # merge the edited view back into the master by row key, and autosave
    # to disk only when something actually changed (a plain rerun is a no-op)
    m = master.set_index(KEY)
    m.update(edited.set_index(KEY))
    merged = m.reset_index()[master.columns]
    if not merged.equals(st.session_state[state_key]):
        st.session_state[state_key] = merged
        save_worksheet(_store_key, merged.to_dict("records"),
                       meta={"system": system,
                             "pid": Path(pid_path).name,
                             "scd": Path(scd_path).name})
        st.session_state[f"hazop_meta_{system}"] = \
            (load_worksheet(_store_key) or {}).get("meta", {})
    rows_out = st.session_state[state_key].to_dict("records")

    c = st.session_state[state_key]["status"].value_counts().to_dict()
    st.caption(f"Status, whole system: {c.get('proposed', 0)} proposed · "
               f"{c.get('reviewed', 0)} reviewed · {c.get('rejected', 0)} rejected")
    _meta_now = st.session_state.get(f"hazop_meta_{system}")
    if _meta_now:
        st.caption(f"💾 Autosaved to reports/hazop_store/ — last "
                   f"{str(_meta_now.get('saved_at', '?'))[:16]} "
                   f"({_meta_now.get('n_saves', 0)} save(s)).")

    # ---- exports (full worksheet incl. edits, all nodes) -------------------
    out_dir = Path("reports"); out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / "hazop_worksheet.csv"
    write_worksheet_csv(rows_out, csv_path)
    xlsx_path = out_dir / f"hazop_system_{system}.xlsx"
    write_worksheet_xlsx(rows_out, xlsx_path,
                         title=f"HAZOP preparation — System {system}")
    d1, d2 = st.columns(2)
    d1.download_button("Download Excel worksheet (per node)",
                       xlsx_path.read_bytes(), file_name=xlsx_path.name,
                       mime="application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet")
    d2.download_button("Download CSV (raw)", csv_path.read_bytes(),
                       file_name=f"hazop_system_{system}.csv", mime="text/csv")
    if st.button("Reset: discard edits and the saved worksheet, rebuild "
                 "from the current extraction"):
        delete_worksheet(_store_key)                # ellers lastes arket rett inn igjen
        st.session_state.pop(state_key, None)
        st.session_state.pop(f"hazop_meta_{system}", None)
        st.rerun()

    # ---- nodegrenser på tegningen (HAZOP-pakkens tegningsvedlegg) ----------
    st.divider()
    st.subheader("🗺️ Nodes marked on the drawing")
    st.caption("Standard HAZOP preparation marks node boundaries on the "
               "drawing package — here it happens automatically: each "
               "selected node's members are boxed in the node's colour. "
               "Members without a box are either symbol-only on the P&ID "
               "(the recall gap) or exist only on the SCD — honest absence, "
               "not an error.")
    _NODE_COLORS = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8",
                    "#c98a1b", "#5aa8a0", "#a83a5f", "#6b705c"]
    node_map_pick = picked[:8]
    if len(picked) > 8:
        st.caption("Showing the first 8 selected nodes (more becomes unreadable).")
    if node_map_pick:
        _rows_df = pd.DataFrame(all_rows)
        members_of = {}
        for nd in node_map_pick:
            mem = _rows_df[_rows_df["node"] == nd]["node_members"]
            members_of[nd] = sorted(set(mem.iloc[0].split(", "))) if len(mem) else []
        # fargelegende
        leg = ""
        for i, nd in enumerate(node_map_pick):
            c = _NODE_COLORS[i % len(_NODE_COLORS)]
            leg += (f"<span style='background:{c};color:#fff;"
                    f"border-radius:20px;padding:2px 10px;margin:2px;"
                    f"display:inline-block;font-size:12px'>{nd} "
                    f"({len(members_of[nd])})</span> ")
        st.markdown(leg, unsafe_allow_html=True)

        from extraction.tag_locator import locate_tags
        all_member_tags = sorted({t for ms in members_of.values() for t in ms})
        nboxes = locate_tags(pid_path, all_member_tags, dpi=200)
        nmarkers = []
        for i, nd in enumerate(node_map_pick):
            c = _NODE_COLORS[i % len(_NODE_COLORS)]
            for t in members_of[nd]:
                for (x, y, w, h) in nboxes.get(t, []):
                    px, py = max(14, 0.45 * w), max(14, 0.55 * h)
                    nmarkers.append((x - px, y - py, w + 2*px, h + 2*py,
                                     c, f"{nd}: {t}"))
        loc = sum(1 for ms in members_of.values() for t in ms if t in nboxes)
        tot = sum(len(ms) for ms in members_of.values())
        st.caption(f"📍 {loc} of {tot} node members located on the drawing.")
        npng = st.session_state.get(f"vision_png_{system}")
        if not (npng and Path(npng).exists()):
            try:
                from extraction.vision_extract import render_png
                npng = render_png(Path(pid_path), 200)
                st.session_state[f"vision_png_{system}"] = npng
            except Exception as e:  # noqa: BLE001
                npng = None
                st.caption(f"Could not rasterise the drawing: {e}")
        if npng and nmarkers:
            _zoomable_image(str(npng), markers=nmarkers)

with tab_funn:
    st.caption("Rule-based screening of the DEXPI model: findings about what "
               "appears to be MISSING (relief, action path, monitoring) — a "
               "capability that demonstrably requires structured data, since "
               "absence cannot be told apart from extraction loss in a PDF. "
               "Standard references are INDICATIVE: a discipline engineer "
               "must confirm both finding and clause. Markers show where the "
               "finding's tags sit on the drawing (only tags the text layer "
               "can read get a box).")

    @st.cache_resource(show_spinner="Screener DEXPI-modellen…")
    def _screen_drawing(pid_stem: str):
        hits = list(Path(PID_DIR).parent.rglob(f"{pid_stem}.DGN.xml"))
        if not hits:
            return None
        from analysis.hazop_dexpi import load_dexpi_model
        from analysis.rule_screening import screen
        m = load_dexpi_model(hits[0])
        return screen(m["tag_graph"], m["objects"], m["sections"])

    @st.cache_resource(show_spinner="Sjekker I-005-dekning P&ID↔SCD…")
    def _screen_coverage(pid: str, scd: str):
        from extraction.tag_extractor import extract_tags, create_objects
        from analysis.rule_screening import screen_scd_coverage
        return screen_scd_coverage(
            create_objects(extract_tags(pid), "P&ID"),
            create_objects(extract_tags(scd), "SCD"))

    _dx = list(Path(PID_DIR).parent.rglob(
        f"{Path(pid_path).stem}.DGN.xml"))
    findings = _screen_drawing(Path(pid_path).stem)
    coverage = _screen_coverage(str(pid_path), str(scd_path))
    findings = (findings or []) + coverage if (findings or coverage) \
        else findings
    if findings is None:
        st.info("This drawing has no DEXPI XML — rule screening requires "
                "structured data (which is the point).")
    elif not findings:
        st.success("No findings from the rules on this drawing.")
    else:
        # Fargekode etter alvorlighet, to nivåer:
        #   RØD  = mest sannsynlig et reelt avvik (strukturelt fravær i
        #          selve modellen — R1/R2, severity "høy").
        #   GUL  = mulig avvik som MÅ verifiseres mot et dokument (typisk
        #          SCD-en eller tilstøtende ark — R3–R7, "middels"/"lav").
        _SEV = {"høy": "#c0392b", "middels": "#e0a800", "lav": "#e0a800"}
        st.markdown(
            "<span style='color:#c0392b;font-weight:700'>🔴 Red</span> = most "
            "likely a real deviation (structural absence in the model). &nbsp; "
            "<span style='color:#e0a800;font-weight:700'>🟡 Amber</span> = possible "
            "deviation — must be verified against a document (the SCD or an "
            "adjacent sheet). &nbsp; <span style='color:#888'>⬚ dashed box</span> = "
            "estimated position on the drawing.",
            unsafe_allow_html=True)
        rules = sorted({f["rule"] for f in findings})
        pick_rules = st.multiselect("Show rules", rules, default=rules,
                                    help="R1 relief · R2 action path · "
                                         "R3 pressure monitoring · R4-R7 "
                                         "I-005 Annex B coverage P&ID↔SCD "
                                         "(verified clauses)")
        shown = [f for f in findings if f["rule"] in pick_rules]

        for f in shown:
            with st.expander(f"{'🔴' if f['severity']=='høy' else '🟡'} "
                             f"[{f['rule']}] {f['title']} — "
                             f"{', '.join(f['tags'][:3])}"):
                st.write(f["description"])
                st.write("**Recommended follow-up:** " + f["recommendation"])
                st.caption("📖 " + f["standard"])
                if f["rule"] in ("R1", "R2", "R3") and _dx:
                    from analysis.rule_screening import (fluids_for_tags,
                                                         FLUID_MEANINGS)
                    if True:
                        _fc = fluids_for_tags(_dx[0], f["tags"])
                        if _fc:
                            st.caption("🧪 Fluid on connected lines "
                                       "(from line tags, assumed meaning): "
                                       + " · ".join(
                                           f"{c} = {FLUID_MEANINGS.get(c, 'unknown')}"
                                           for c in _fc))
                if os.getenv("GEMINI_API_KEY"):
                    ck = f"vcheck_{f['rule']}_{'_'.join(f['tags'][:2])}"
                    target_pdf = scd_path if f["rule"] in ("R4", "R5", "R6", "R7") \
                        else pid_path
                    if st.button("👁️ Second opinion from vision "
                                 f"(the {'SCD' if f['rule'] in ('R4','R5','R6') else 'P&ID'} sheet)",
                                 key=ck):
                        from ai.ai_cache import load_vcheck, save_vcheck
                        vkey = (f"{Path(target_pdf).stem}|{f['rule']}|"
                                + ",".join(f["tags"][:4]))
                        hit = load_vcheck(vkey)
                        if hit:
                            r = hit["result"]
                            r["cached_at"] = hit["saved_at"]
                            st.session_state[ck + "_r"] = r
                        else:
                            from ai.hazop_vision import vision_check_finding
                            with st.spinner("Looking at the drawing…"):
                                try:
                                    r = vision_check_finding(
                                        Path(target_pdf), f,
                                        [o.tag for o in objs])
                                    if r.get("ok"):
                                        save_vcheck(vkey, r)
                                    st.session_state[ck + "_r"] = r
                                except Exception as e:  # noqa: BLE001
                                    st.session_state[ck + "_r"] = \
                                        {"ok": False,
                                         "verdict": f"Failed: {e}"}
                    vr = st.session_state.get(ck + "_r")
                    if vr:
                        if vr.get("cached_at"):
                            st.caption(f"🗂️ Cached answer from {vr['cached_at']} "
                                       "— delete reports/ai_cache/vc_*.json "
                                       "for a fresh run.")
                        st.write(vr["verdict"])
                        if vr.get("evidence"):
                            st.caption(f"Model's observation: {vr['evidence']}")
                        if vr.get("tags"):
                            st.caption(f"Mentioned tags: {vr['tags']}")
                        st.caption("Exculpatory only: a sighting can weaken "
                                   "the finding; absence never strengthens it.")

        _exp = pd.DataFrame([{
            "rule": f["rule"], "severity": f["severity"],
            "title": f["title"], "section": f.get("section", ""),
            "tags": ", ".join(f["tags"]), "description": f["description"],
            "recommendation": f["recommendation"], "standard": f["standard"],
        } for f in shown])
        st.download_button("⬇️ Download the findings (CSV)",
                           _exp.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"rule_findings_system_{system}.csv",
                           mime="text/csv")

        # markører: funn-tags -> bokser fra det posisjonerte tekstlaget
        from extraction.tag_locator import locate_tags
        all_tags = sorted({t for f in shown for t in f["tags"]})
        boxes = locate_tags(pid_path, all_tags, dpi=200)
        markers = []
        for f in shown:
            for t in f["tags"]:
                for (x, y, w, h) in boxes.get(t, []):
                    # romslig nok til å omslutte hele bobla/symbolet, ikke
                    # bare tekstordene — proporsjonal med tag-størrelsen
                    pad_x = max(14, 0.45 * w)
                    pad_y = max(14, 0.55 * h)
                    markers.append((x - pad_x, y - pad_y,
                                    w + 2 * pad_x, h + 2 * pad_y,
                                    _SEV[f["severity"]],
                                    f"[{f['rule']}] {f['title']}: {t}"))
        _missing = sorted({t for f in shown for t in f["tags"]
                           if t not in boxes})
        _fb_info = {}
        if _missing and _dx:
            from extraction.tag_locator import dexpi_fallback_boxes
            if True:
                _fb, _fb_info = dexpi_fallback_boxes(pid_path, _dx[0],
                                                     _missing, boxes)
                for f in shown:
                    for t in f["tags"]:
                        for (x, y, w, h) in _fb.get(t, []):
                            markers.append((x, y, w, h, _SEV[f["severity"]],
                                            f"[{f['rule']}] {t} — estimated "
                                            f"position from DEXPI geometry "
                                            f"(dashed = may be imprecise)",
                                            True))          # dashed = estimated
                boxes = {**boxes, **_fb}
        if _fb_info.get("ok"):
            st.caption(f"⬚ {len([t for t in _missing if t in boxes])} "
                       f"symbol-only tags shown with a DASHED box — position "
                       f"estimated from DEXPI geometry (calibrated against "
                       f"{_fb_info['anchors']} shared tags, residual "
                       f"{_fb_info['residual']} px). Colour still means "
                       f"severity (red/amber).")
        located = sum(1 for f in shown for t in f["tags"] if t in boxes)
        total = sum(len(f["tags"]) for f in shown)
        st.caption(f"📍 {located} of {total} finding tags located on the "
                   f"drawing (hover a box to see the finding). "
                   f"Unlocated tags are typically symbol-only or on an "
                   f"adjacent sheet.")
        png = st.session_state.get(f"vision_png_{system}")
        if not (png and Path(png).exists()):
            try:
                from extraction.vision_extract import render_png
                png = render_png(Path(pid_path), 200)
                st.session_state[f"vision_png_{system}"] = png
            except Exception as e:  # noqa: BLE001
                png = None
                st.caption(f"Could not rasterise the drawing: {e}")
        if png and markers:
            _zoomable_image(str(png), markers=markers)
        elif png:
            st.caption("None of the finding tags could be located in the text "
                       "layer — showing the drawing without markers.")
            _zoomable_image(str(png))

with tab_ai:
    st.caption("LLM rewrite of one node's deterministic rows into fluent "
               "worksheet text — only the node's tags, generic is marked. "
               "Drafts are cached to disk (demo insurance).")
    if os.getenv("GEMINI_API_KEY"):
        node_ai = st.selectbox("AI rewrite of one node", picked or nodes)
        from ai.ai_cache import load_rewrite, save_rewrite
        cached_rw = load_rewrite(system, node_ai)
        rw_label = ("🔄 New AI draft (overwrites cache)" if cached_rw
                    else "Generate AI draft for the node")
        if st.button(rw_label):
            node_rows = [r for r in all_rows if r["node"] == node_ai]
            with st.spinner("Asking the model…"):
                text = ai_enrich_node(node_rows)
            save_rewrite(system, node_ai, text)
            cached_rw = {"text": text, "saved_at": "now (live)"}
        if cached_rw:
            st.caption(f"🗂️ Draft generated: {cached_rw['saved_at']}")
            st.markdown(cached_rw["text"])

    else:
        st.caption("Set GEMINI_API_KEY for AI drafts — the worksheet in the first "
                   "tab is deterministic and complete without it.")

@st.cache_resource(show_spinner="Leser DEXPI-register…")
def _dexpi_register(pid_stem: str) -> list[str] | None:
    """Tags fra tegningens DEXPI-XML — den beste fasiten som finnes.
    None hvis tegningen ikke har DEXPI."""
    hits = list(Path(PID_DIR).parent.rglob(f"{pid_stem}.DGN.xml"))
    if not hits:
        return None
    from analysis.hazop_dexpi import load_dexpi_model
    return [o.tag for o in load_dexpi_model(hits[0])["objects"]]


with tab_vision:
    if os.getenv("GEMINI_API_KEY"):
        _dexpi_tags = _dexpi_register(Path(pid_path).stem)
        if _dexpi_tags is not None:
            register, reg_name = _dexpi_tags, "the DEXPI model (structured ground truth)"
            st.caption("Gemini LOOKS at the P&ID and proposes HAZOP observations. "
                       "Each tag is verified against the **DEXPI model** — the "
                       "structured ground truth for the drawing: ✅/☑️ confirmed "
                       "real component · 🟠 well-formed but NOT in the model — "
                       "either a misread or something missing from the delivery "
                       "(both worth checking) · ❓ does not match a known "
                       "tag format. Requires pypdfium2.")
        else:
            register, reg_name = [o.tag for o in objs], \
                "the PDF text layer (no DEXPI for this drawing)"
            st.caption("Gemini LOOKS at the P&ID and proposes HAZOP observations. "
                       "This drawing has no DEXPI, so verification uses the "
                       "PDF text-layer register: ✅ exists in the extraction · "
                       "🟠 well-formed but not extracted (possible "
                       "symbol-only find) · ❓ does not match a known tag format.")
        st.caption(f"🔎 Verification register: {reg_name}")
        from ai.ai_cache import load_vision, save_vision
        # demoforsikring: hent cachet utdrag fra disk om det finnes
        if f"vision_{system}" not in st.session_state:
            cached = load_vision(Path(pid_path).stem)
            if cached:
                st.session_state[f"vision_{system}"] = cached["excerpt"]
                st.session_state[f"vision_png_{system}"] = cached["png"]
                st.session_state[f"vision_ts_{system}"] = cached["saved_at"]
        focus = st.text_input(
            "Extra focus (optional)",
            placeholder="E.g.: focus on erosion/sand and note temporary "
                        "equipment",
            help="Steers the model's attention. The JSON format and the "
                 "tag rules can NOT be overridden — the verification layer "
                 "depends on them. A new focus requires a fresh API run.")
        with st.expander("Show the fixed prompt (read-only)"):
            from ai.hazop_vision import PROMPT as _VISION_PROMPT
            st.code(_VISION_PROMPT, language="text")
            st.caption("Reusable prompt — see also the README section on reusable "
                       "prompts. The focus field above is inserted as a marked "
                       "extra section; the rules remain.")
        btn_label = ("🔄 Re-run against the API (overwrites cache)"
                     if st.session_state.get(f"vision_{system}")
                     else "Generate vision excerpt for the P&ID")
        if st.button(btn_label):
            from ai.hazop_vision import vision_hazop_excerpt
            try:
                with st.spinner("Rasterising and asking Gemini…"):
                    st.session_state[f"vision_{system}"] = vision_hazop_excerpt(
                        Path(pid_path), register, focus=focus)
                    # gjenbruk rasteret til visning ved siden av utdraget
                    from extraction.vision_extract import render_png
                    st.session_state[f"vision_png_{system}"] = render_png(
                        Path(pid_path), 200)
                    st.session_state[f"vision_ts_{system}"] = "now (live)"
                    save_vision(Path(pid_path).stem,
                                st.session_state[f"vision_{system}"],
                                st.session_state[f"vision_png_{system}"])
            except ImportError as e:
                st.error(f"Missing dependency: {e} — "
                         f"`uv add pypdfium2 google-genai`")
            except Exception as e:  # noqa: BLE001
                st.error(f"The vision call failed: {e}")

        # render + export from session state so the excerpt survives reruns
        # (any click, incl. a download button, reruns the whole page)
        ex = st.session_state.get(f"vision_{system}")
        if ex:
            from ai.hazop_vision import to_markdown
            ts = st.session_state.get(f"vision_ts_{system}")
            if ts:
                st.caption(f"🗂️ Result generated: {ts} — use the button above "
                           f"for a fresh API run.")
            _OBS_COLORS = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8",
                           "#c98a1b", "#5aa8a0", "#a83a5f", "#6b705c"]
            png = st.session_state.get(f"vision_png_{system}")
            if png and Path(png).exists():
                # markører per observasjon (case) med hver sin farge —
                # slik at operatøren ser på arket hvor hvert HAZOP-punkt
                # er forankret; ulokaliserte tags nevnes ærlig under.
                obs_list = ex.get("observations", [])[:8]
                obs_tags = []
                for i, o in enumerate(obs_list):
                    ts_i = sorted({(t["tag"] if isinstance(t, dict) else t)
                                   for t in o.get("tags", [])})
                    obs_tags.append(ts_i)

                _labels = [f"Item {i+1} — "
                           f"{(o.get('deviation') or o.get('observation',''))[:40]}"
                           for i, o in enumerate(obs_list)]
                _sel = st.multiselect(
                    "Show markers for item(s)", _labels, default=_labels,
                    key=f"obsmarks_{system}",
                    help="Toggle single items on/off — useful when the drawing "
                         "gets busy or you want to focus on one item.")
                _active_idx = {_labels.index(l) for l in _sel}

                all_o_tags = sorted({t for i, ts_i in enumerate(obs_tags)
                                     if i in _active_idx for t in ts_i})
                from extraction.tag_locator import locate_tags
                _boxes = locate_tags(pid_path, all_o_tags, dpi=200) \
                    if all_o_tags else {}
                _markers = []
                for i, ts_i in enumerate(obs_tags):
                    if i not in _active_idx:
                        continue
                    c = _OBS_COLORS[i % len(_OBS_COLORS)]
                    for t in ts_i:
                        for (x, y, w, h) in _boxes.get(t, []):
                            px, py = max(14, 0.45 * w), max(14, 0.55 * h)
                            _markers.append((x - px, y - py,
                                             w + 2 * px, h + 2 * py, c,
                                             f"Item {i+1}: {t}"))
                img_col, txt_col = st.columns([1, 1])
                with img_col:
                    _zoomable_image(str(png), markers=_markers)
                    _hit = sum(1 for i, ts_i in enumerate(obs_tags)
                               if i in _active_idx for t in ts_i
                               if t in _boxes)
                    _tot = sum(len(ts_i) for i, ts_i in enumerate(obs_tags)
                               if i in _active_idx)
                    st.caption(f"📍 {_hit} of {_tot} item tags located "
                               "on the drawing. Unlocated tags are typically "
                               "symbol-only (the recall gap) or mentioned "
                               "outside the drawing area.")
                with txt_col:
                    st.markdown(to_markdown(ex, obs_colors=_OBS_COLORS), unsafe_allow_html=True)
            else:
                st.markdown(to_markdown(ex, obs_colors=_OBS_COLORS), unsafe_allow_html=True)
            vx = Path("reports") / f"hazop_vision_system_{system}.xlsx"
            write_vision_xlsx(ex, vx,
                              title=f"Vision HAZOP excerpt — System {system}")
            st.download_button("Download vision excerpt (Excel)",
                               vx.read_bytes(), file_name=vx.name,
                               mime="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")
    else:
        st.caption("Set GEMINI_API_KEY for vision excerpts — the worksheet in "
                   "the first tab is deterministic and complete without it.")

with tab_ark:
 if view.empty:
    st.info("Select at least one node.")