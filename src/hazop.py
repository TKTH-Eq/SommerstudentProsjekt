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

from dotenv import load_dotenv
load_dotenv()  # eksplisitt: GEMINI_API_KEY-gaten under avhenger av .env,
               # og skal ikke lene seg på at en annen import lastet den

from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph
from analysis.hazop_prep import build_worksheet, hazop_nodes, write_worksheet_csv, ai_enrich_node
from analysis.hazop_export import write_worksheet_xlsx, write_vision_xlsx
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

from config import PID_DIR
from ui import chips as _ui_chips, page_header


def _chips(tags):
    by = {o.tag: o for o in objs}
    return _ui_chips(tags, by)


page_header(f"System {system} — HAZOP-forberedelse",
            f"P&ID {Path(pid_path).stem[-14:]} · SCD "
            f"{Path(scd_path).stem[-14:]} · {len(objs)} tags i uttrekket")
st.caption("Ferdig utfylt arbeidsark fra AI-uttrukket P&ID/SCD-data. Noder er "
           "funksjonelle løkker (ekte HAZOP-noder er prosessseksjoner — det "
           "krever DEXPI, se ⚖️-siden). Hver tag som refereres finnes i "
           "uttrekket; ingenting er funnet på. For HAZOP-team-gjennomgang — "
           "ikke en fullført studie.")

nodes = sorted({r["node"] for r in all_rows})
if not nodes:
    st.warning("Ingen løkke i systemet har instrumenter som gir en "
               "prosessparameter — ingenting å foreslå.")
    st.stop()

# nøkkeltall for hele systemet (master om den finnes, ellers råforslagene)
_state_key = f"hazop_master_{system}"
_df_all = st.session_state.get(_state_key, pd.DataFrame(all_rows))
_n_rows = len(_df_all)
_with_sg = int((~_df_all["safeguards"].str.startswith("(none")).sum())
_done = int((_df_all["status"] != "proposed").sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Noder", len(nodes),
          help="Funksjonelle løkker med minst én prosessparameter.")
m2.metric("Avviksrader", _n_rows,
          help="Én rad per (node, guideword-avvik).")
m3.metric("Rader med funnet barriere", f"{_with_sg}/{_n_rows}",
          help="Avviksrader der minst én ekte, uttrukket safeguard-tag ble "
               "identifisert. Gapet er der forberedelsesarbeidet ligger — "
               "og der recall-taket på 55 % koster (se ⚖️-siden).")
m4.metric("Gjennomgått", f"{_done}/{_n_rows}",
          help="Rader satt til reviewed eller rejected i arbeidsarket.")
st.progress(_done / _n_rows if _n_rows else 0.0)

tab_ark, tab_vision, tab_funn, tab_ai = st.tabs(
    ["📋 Arbeidsark", "👁️ Vision-utdrag", "📐 Regelfunn på tegningen",
     "🤖 AI-utkast per node"])

with tab_ark:
    f1, f2 = st.columns([2, 1])
    with f1:
        sel_all = st.checkbox(f"Velg alle noder i systemet ({len(nodes)})")
        if sel_all:
            picked = nodes
            st.multiselect("Noder (funksjonelle løkker)", nodes, default=nodes,
                           disabled=True,
                           help="Alle noder valgt — fjern haken for manuelt valg.")
        else:
            picked = st.multiselect("Noder (funksjonelle løkker)", nodes,
                                    default=nodes[:3])
    with f2:
        only_gap = st.toggle("Kun rader uten funnet barriere",
                             help="Filtrer til avvikene som mangler en "
                                  "identifisert safeguard — det er disse et "
                                  "HAZOP-team må bruke tid på.")
        status_f = st.multiselect("Status", ["proposed", "reviewed", "rejected"],
                                  default=["proposed", "reviewed", "rejected"])

    if picked:
        with st.expander("Komponentene i valgte noder"):
            by_node_rows = pd.DataFrame(all_rows)
            for nd in picked:
                mem = by_node_rows[by_node_rows["node"] == nd]["node_members"]
                tags = sorted(set(mem.iloc[0].split(", "))) if len(mem) else []
                st.markdown(f"**{nd}**  \n" + _chips(tags),
                            unsafe_allow_html=True)

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
if not view.empty and only_gap:
    view = view[view["safeguards"].str.startswith("(none")]
if not view.empty and status_f:
    view = view[view["status"].isin(status_f)]

with tab_ark:
 if not view.empty:
    st.caption("Redigerbart: juster tekst, fyll inn anbefaling/ansvarlig og "
               "sett status per rad. Endringer huskes i økten og følger med "
               "i eksporten — også for rader som er filtrert bort akkurat nå.")
    edited = st.data_editor(
        view[["node", "parameter", "deviation", "causes", "consequences",
              "safeguards", "recommendation", "action_party", "status"]],
        use_container_width=True, hide_index=True, num_rows="fixed",
        disabled=["node", "parameter", "deviation"],
        column_config={
            "node": st.column_config.TextColumn("node", width="small"),
            "parameter": st.column_config.TextColumn("param.", width="small"),
            "deviation": st.column_config.TextColumn(
                "avvik", width="small",
                help="Guideword-avvik (High/Low/No/Reverse …)"),
            "causes": st.column_config.TextColumn(
                "årsaker", width="large",
                help="Feilmodi fra løkkas reguleringselementer (ekte tags) + "
                     "generiske prosessårsaker merket (generic)."),
            "consequences": st.column_config.TextColumn(
                "konsekvenser", width="large"),
            "safeguards": st.column_config.TextColumn(
                "barrierer", width="medium",
                help="Kun tags som faktisk finnes i uttrekket. «(none found)» "
                     "betyr: ikke funnet i tekstlaget — sjekk tegningen."),
            "recommendation": st.column_config.TextColumn("anbefaling",
                                                          width="medium"),
            "action_party": st.column_config.TextColumn("ansvarlig",
                                                        width="small"),
            "status": st.column_config.SelectboxColumn(
                "status", options=["proposed", "reviewed", "rejected"],
                required=True, width="small"),
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

    # ---- nodegrenser på tegningen (HAZOP-pakkens tegningsvedlegg) ----------
    st.divider()
    st.subheader("🗺️ Noder markert på tegningen")
    st.caption("Standard HAZOP-forberedelse markerer nodegrensene på "
               "tegningspakken — her gjøres det automatisk: hver valgt "
               "nodes medlemmer rammes inn i nodens farge. Medlemmer uten "
               "ramme er enten symbol-only på P&ID-en (recall-gapet) eller "
               "finnes kun på SCD-en — begge deler ærlig fravær, ikke feil.")
    _NODE_COLORS = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8",
                    "#c98a1b", "#5aa8a0", "#a83a5f", "#6b705c"]
    node_map_pick = picked[:8]
    if len(picked) > 8:
        st.caption("Viser de 8 første valgte nodene (flere blir uleselig).")
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
        st.caption(f"📍 {loc} av {tot} nodemedlemmer lokalisert på tegningen.")
        npng = st.session_state.get(f"vision_png_{system}")
        if not (npng and Path(npng).exists()):
            try:
                from extraction.vision_extract import _render_png
                npng = _render_png(Path(pid_path), 200)
                st.session_state[f"vision_png_{system}"] = npng
            except Exception as e:  # noqa: BLE001
                npng = None
                st.caption(f"Kunne ikke rasterisere tegningen: {e}")
        if npng and nmarkers:
            _zoomable_image(str(npng), markers=nmarkers)

with tab_funn:
    st.caption("Regelbasert screening av DEXPI-modellen: funn som handler om "
               "det som ser ut til å MANGLE (avlastning, aksjonsvei, "
               "overvåking) — en kapabilitet som beviselig krever "
               "strukturert data, siden fravær ikke kan skilles fra "
               "uttrekkstap i en PDF. Standardreferansene er VEILEDENDE: "
               "fagingeniør må bekrefte både funn og klausul. Markørene "
               "viser hvor på tegningen funnets tags står (kun tags "
               "tekstlaget kan lese får boks).")

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
        st.info("Tegningen mangler DEXPI-XML — regelscreening krever "
                "strukturert data (det er selve poenget).")
    elif not findings:
        st.success("Ingen funn fra reglene på denne tegningen.")
    else:
        # Fargekode etter alvorlighet, to nivåer:
        #   RØD  = mest sannsynlig et reelt avvik (strukturelt fravær i
        #          selve modellen — R1/R2, severity "høy").
        #   GUL  = mulig avvik som MÅ verifiseres mot et dokument (typisk
        #          SCD-en eller tilstøtende ark — R3–R7, "middels"/"lav").
        _SEV = {"høy": "#c0392b", "middels": "#e0a800", "lav": "#e0a800"}
        st.markdown(
            "<span style='color:#c0392b;font-weight:700'>🔴 Rød</span> = mest "
            "sannsynlig et reelt avvik (strukturelt fravær i modellen). &nbsp; "
            "<span style='color:#e0a800;font-weight:700'>🟡 Gul</span> = mulig "
            "avvik — må verifiseres mot et dokument (SCD-en eller tilstøtende "
            "ark). &nbsp; <span style='color:#888'>⬚ stiplet boks</span> = "
            "estimert posisjon på tegningen.",
            unsafe_allow_html=True)
        rules = sorted({f["rule"] for f in findings})
        pick_rules = st.multiselect("Vis regler", rules, default=rules,
                                    help="R1 avlastning · R2 aksjonsvei · "
                                         "R3 trykkovervåking · R4-R7 "
                                         "I-005 Annex B-dekning P&ID↔SCD "
                                         "(verifiserte klausuler)")
        shown = [f for f in findings if f["rule"] in pick_rules]

        for f in shown:
            with st.expander(f"{'🔴' if f['severity']=='høy' else '🟡'} "
                             f"[{f['rule']}] {f['title']} — "
                             f"{', '.join(f['tags'][:3])}"):
                st.write(f["description"])
                st.write("**Anbefalt oppfølging:** " + f["recommendation"])
                st.caption("📖 " + f["standard"])
                if f["rule"] in ("R1", "R2", "R3") and _dx:
                    from analysis.rule_screening import (fluids_for_tags,
                                                         FLUID_MEANINGS)
                    if True:
                        _fc = fluids_for_tags(_dx[0], f["tags"])
                        if _fc:
                            st.caption("🧪 Fluid på tilknyttede linjer "
                                       "(fra linjetags, antatt betydning): "
                                       + " · ".join(
                                           f"{c} = {FLUID_MEANINGS.get(c, 'ukjent')}"
                                           for c in _fc))
                if os.getenv("GEMINI_API_KEY"):
                    ck = f"vcheck_{f['rule']}_{'_'.join(f['tags'][:2])}"
                    target_pdf = scd_path if f["rule"] in ("R4", "R5", "R6", "R7") \
                        else pid_path
                    if st.button("👁️ Andre-opinion fra vision "
                                 f"({'SCD' if f['rule'] in ('R4','R5','R6') else 'P&ID'}-arket)",
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
                            with st.spinner("Ser på tegningen…"):
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
                                         "verdict": f"Feilet: {e}"}
                    vr = st.session_state.get(ck + "_r")
                    if vr:
                        if vr.get("cached_at"):
                            st.caption(f"🗂️ Cachet svar fra {vr['cached_at']} "
                                       "— slett reports/ai_cache/vc_*.json "
                                       "for ny kjøring.")
                        st.write(vr["verdict"])
                        if vr.get("evidence"):
                            st.caption(f"Modellens observasjon: {vr['evidence']}")
                        if vr.get("tags"):
                            st.caption(f"Nevnte tags: {vr['tags']}")
                        st.caption("Kun frikjennende: et syn kan svekke "
                                   "funnet; fravær styrker det aldri.")

        _exp = pd.DataFrame([{
            "rule": f["rule"], "severity": f["severity"],
            "title": f["title"], "section": f.get("section", ""),
            "tags": ", ".join(f["tags"]), "description": f["description"],
            "recommendation": f["recommendation"], "standard": f["standard"],
        } for f in shown])
        st.download_button("⬇️ Last ned funnene (CSV)",
                           _exp.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"regelfunn_system_{system}.csv",
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
                                            f"[{f['rule']}] {t} — estimert "
                                            f"posisjon fra DEXPI-geometri "
                                            f"(stiplet = kan være unøyaktig)",
                                            True))          # dashed = estimated
                boxes = {**boxes, **_fb}
        if _fb_info.get("ok"):
            st.caption(f"⬚ {len([t for t in _missing if t in boxes])} "
                       f"symbol-only-tags vist med STIPLET boks — posisjon "
                       f"estimert fra DEXPI-geometri (kalibrert mot "
                       f"{_fb_info['anchors']} felles tags, residual "
                       f"{_fb_info['residual']} px). Fargen betyr fortsatt "
                       f"alvorlighet (rød/gul).")
        located = sum(1 for f in shown for t in f["tags"] if t in boxes)
        total = sum(len(f["tags"]) for f in shown)
        st.caption(f"📍 {located} av {total} funn-tags lokalisert på "
                   f"tegningen (hold musen over en boks for funnet). "
                   f"Ulokaliserte tags er typisk symbol-only eller på "
                   f"tilstøtende ark.")
        png = st.session_state.get(f"vision_png_{system}")
        if not (png and Path(png).exists()):
            try:
                from extraction.vision_extract import _render_png
                png = _render_png(Path(pid_path), 200)
                st.session_state[f"vision_png_{system}"] = png
            except Exception as e:  # noqa: BLE001
                png = None
                st.caption(f"Kunne ikke rasterisere tegningen: {e}")
        if png and markers:
            _zoomable_image(str(png), markers=markers)
        elif png:
            st.caption("Ingen av funn-tagene kunne lokaliseres i tekstlaget "
                       "— viser tegningen uten markører.")
            _zoomable_image(str(png))

with tab_ai:
    st.caption("LLM-omskriving av én nodes deterministiske rader til flytende "
               "arbeidsark-tekst — kun tags fra noden, generisk merkes. "
               "Utkast caches til disk (demo-sikring).")
    if os.getenv("GEMINI_API_KEY"):
        node_ai = st.selectbox("AI-omskriving av én node", picked or nodes)
        from ai.ai_cache import load_rewrite, save_rewrite
        cached_rw = load_rewrite(system, node_ai)
        rw_label = ("🔄 Nytt AI-utkast (overskriver cache)" if cached_rw
                    else "Generer AI-utkast for noden")
        if st.button(rw_label):
            node_rows = [r for r in all_rows if r["node"] == node_ai]
            with st.spinner("Spør modellen…"):
                text = ai_enrich_node(node_rows)
            save_rewrite(system, node_ai, text)
            cached_rw = {"text": text, "saved_at": "nå (live)"}
        if cached_rw:
            st.caption(f"🗂️ Utkast generert: {cached_rw['saved_at']}")
            st.markdown(cached_rw["text"])

    else:
        st.caption("Sett GEMINI_API_KEY for AI-utkast — arbeidsarket i første "
                   "fane er deterministisk og komplett uten.")

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
            register, reg_name = _dexpi_tags, "DEXPI-modellen (strukturert fasit)"
            st.caption("Gemini SER på P&ID-en og foreslår HAZOP-observasjoner. "
                       "Hver tag verifiseres mot **DEXPI-modellen** — den "
                       "strukturerte fasiten for tegningen: ✅/☑️ bekreftet "
                       "reell komponent · 🟠 velformet men IKKE i modellen — "
                       "enten feillesning eller noe som mangler i leveransen "
                       "(begge verdt å sjekke) · ❓ matcher ikke kjent "
                       "tagformat. Krever pypdfium2.")
        else:
            register, reg_name = [o.tag for o in objs], \
                "PDF-tekstlaget (ingen DEXPI for tegningen)"
            st.caption("Gemini SER på P&ID-en og foreslår HAZOP-observasjoner. "
                       "Tegningen mangler DEXPI, så verifiseringen bruker "
                       "PDF-tekstlagets register: ✅ finnes i uttrekket · "
                       "🟠 velformet men ikke uttrukket (mulig "
                       "symbol-only-funn) · ❓ matcher ikke kjent tagformat.")
        st.caption(f"🔎 Verifiseringsregister: {reg_name}")
        from ai.ai_cache import load_vision, save_vision
        # demoforsikring: hent cachet utdrag fra disk om det finnes
        if f"vision_{system}" not in st.session_state:
            cached = load_vision(Path(pid_path).stem)
            if cached:
                st.session_state[f"vision_{system}"] = cached["excerpt"]
                st.session_state[f"vision_png_{system}"] = cached["png"]
                st.session_state[f"vision_ts_{system}"] = cached["saved_at"]
        focus = st.text_input(
            "Ekstra fokus (valgfritt)",
            placeholder="F.eks.: fokuser på erosjon/sand og noter om "
                        "midlertidig utstyr",
            help="Styrer modellens oppmerksomhet. JSON-formatet og "
                 "tag-reglene kan IKKE overstyres — verifiseringslaget "
                 "avhenger av dem. Nytt fokus krever ny API-kjøring.")
        with st.expander("Vis den faste prompten (skrivebeskyttet)"):
            from ai.hazop_vision import PROMPT as _VISION_PROMPT
            st.code(_VISION_PROMPT, language="text")
            st.caption("Gjenbrukbar prompt — se også README «Gjenbrukbare "
                       "prompts». Fokusfeltet over settes inn som en merket "
                       "tilleggsseksjon; reglene består.")
        btn_label = ("🔄 Kjør på nytt mot API (overskriver cache)"
                     if st.session_state.get(f"vision_{system}")
                     else "Generer vision-utdrag for P&ID-en")
        if st.button(btn_label):
            from ai.hazop_vision import vision_hazop_excerpt
            try:
                with st.spinner("Rasteriserer og spør Gemini…"):
                    st.session_state[f"vision_{system}"] = vision_hazop_excerpt(
                        Path(pid_path), register, focus=focus)
                    # gjenbruk rasteret til visning ved siden av utdraget
                    from extraction.vision_extract import _render_png
                    st.session_state[f"vision_png_{system}"] = _render_png(
                        Path(pid_path), 200)
                    st.session_state[f"vision_ts_{system}"] = "nå (live)"
                    save_vision(Path(pid_path).stem,
                                st.session_state[f"vision_{system}"],
                                st.session_state[f"vision_png_{system}"])
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
            ts = st.session_state.get(f"vision_ts_{system}")
            if ts:
                st.caption(f"🗂️ Resultat generert: {ts} — bruk knappen over "
                           f"for en fersk API-kjøring.")
            png = st.session_state.get(f"vision_png_{system}")
            if png and Path(png).exists():
                # markører per observasjon (case) med hver sin farge —
                # slik at operatøren ser på arket hvor hvert HAZOP-punkt
                # er forankret; ulokaliserte tags nevnes ærlig under.
                _OBS_COLORS = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8",
                               "#c98a1b", "#5aa8a0", "#a83a5f", "#6b705c"]
                obs_list = ex.get("observations", [])[:8]
                obs_tags = []
                for i, o in enumerate(obs_list):
                    ts_i = sorted({(t["tag"] if isinstance(t, dict) else t)
                                   for t in o.get("tags", [])})
                    obs_tags.append(ts_i)

                _labels = [f"Punkt {i+1} — "
                           f"{(o.get('deviation') or o.get('observation',''))[:40]}"
                           for i, o in enumerate(obs_list)]
                _sel = st.multiselect(
                    "Vis markører for punkt(er)", _labels, default=_labels,
                    key=f"obsmarks_{system}",
                    help="Skru enkeltpunkter av/på — nyttig når tegningen "
                         "blir travel eller når du vil fokusere på ett punkt.")
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
                                             f"Punkt {i+1}: {t}"))
                img_col, txt_col = st.columns([1, 1])
                with img_col:
                    _zoomable_image(str(png), markers=_markers)
                    _hit = sum(1 for i, ts_i in enumerate(obs_tags)
                               if i in _active_idx for t in ts_i
                               if t in _boxes)
                    _tot = sum(len(ts_i) for i, ts_i in enumerate(obs_tags)
                               if i in _active_idx)
                    st.caption(f"📍 {_hit} av {_tot} punkt-tags lokalisert "
                               "på tegningen. Ulokaliserte tags er typisk "
                               "symbol-only (recall-gapet) eller nevnt "
                               "utenfor tegningsflaten.")
                with txt_col:
                    st.markdown(to_markdown(ex, obs_colors=_OBS_COLORS), unsafe_allow_html=True)
            else:
                st.markdown(to_markdown(ex, obs_colors=_OBS_COLORS), unsafe_allow_html=True)
            vx = Path("reports") / f"hazop_vision_system_{system}.xlsx"
            write_vision_xlsx(ex, vx,
                              title=f"Vision HAZOP excerpt — System {system}")
            st.download_button("Last ned vision-utdrag (Excel)",
                               vx.read_bytes(), file_name=vx.name,
                               mime="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")
    else:
        st.caption("Sett GEMINI_API_KEY for vision-utdrag — arbeidsarket i "
                   "første fane er deterministisk og komplett uten.")

with tab_ark:
 if view.empty:
    st.info("Velg minst én node.")