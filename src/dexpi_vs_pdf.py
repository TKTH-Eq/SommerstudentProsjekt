"""
src/dexpi_vs_pdf.py  —  the format argument, computed live

Registered in nav_pages.py.

WHAT CHANGED AND WHY. This page used to be a thin wrapper that loaded a
hand-authored HTML file (demos/DEXPI_VS_PDF.html, since deleted) with the
data frozen inside it: 46 components, 45 connections, 34 found in the PDF.
That snapshot had drifted — the same drawing, run through today's pipeline,
gives 50 / 53 / 37. The extractor improved and the demo did not, because
nothing connected them.

A demo whose whole point is "here is what the numbers really are" cannot be
the one page in the app that quotes stale ones. So the data is now computed
on load, by the SAME modules the rest of the app uses:

    extraction.dexpi_parser.parse_dexpi   components, positions, connections
    extraction.tag_extractor.extract_tags what the PDF text layer yields

That also makes it work for EVERY drawing that has both a DEXPI XML and a
PDF, not just the one the snapshot was built from — so a sceptical viewer
can pick their own sheet instead of being shown the flattering one.

The standalone-file benefit is kept, not dropped: the download button emits
the CURRENT view as a self-contained HTML file. Same "attach it to an
e-mail, open it without Streamlit" property as before, without the drift.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PID_DIR
from ui import page_header

RAW_DIR = Path(PID_DIR).parent

# Category -> colour. Mirrors the drawing's own vocabulary rather than the
# app's input/logic/output taxonomy, because on this page the viewer is
# comparing SHAPES on a sheet, not reasoning about signal flow.
CAT_COLOR = {
    "valve": "#8f2d56", "transmitter": "#2d7dd2", "indicator": "#3f8f4f",
    "controller": "#f4a259", "relay": "#7b1fa2", "position": "#0f8b8d",
    "equipment": "#5d4037", "other": "#5c6f7c",
}


def _categorise(tag: str) -> str:
    """Coarse class from the tag's function letters — enough to colour by."""
    core = tag.split("-")[-1].upper()
    if re.fullmatch(r"N\d+", core) or re.fullmatch(r"\d+[A-Z]{1,3}", core):
        return "valve"
    m = re.match(r"([A-Z]{2,4})", core)
    code = m.group(1) if m else ""
    if code.endswith("IC"):
        return "controller"
    if code.startswith("Z"):
        return "position"
    if code.endswith("Y"):
        return "relay"
    if code.endswith("T"):
        return "transmitter"
    if code.endswith("I"):
        return "indicator"
    if code in {"KA", "PA", "VG", "VD"}:
        return "equipment"
    return "other"


def _norm(tag: str) -> str:
    return tag.upper().replace(" ", "").replace("-", "")


@st.cache_data(show_spinner=False)
def _pairs() -> dict:
    """label -> (xml, pdf) for every drawing that has BOTH."""
    out = {}
    for xml in sorted(RAW_DIR.rglob("*.DGN.xml")):
        stem = re.sub(r"\.DGN$", "", xml.stem, flags=re.I)
        pdf = next((p for p in (PID_DIR / f"{stem}.PDF", PID_DIR / f"{stem}.pdf")
                    if p.exists()), None)
        if pdf:
            m = re.search(r"H[A-Z](\d{2})", stem)
            out[f"{m.group(1) if m else '??'}  ·  {stem}"] = (str(xml), str(pdf))
    return out


@st.cache_data(show_spinner="Reading the DEXPI model and the PDF text layer…")
def _build(xml_path: str, pdf_path: str) -> dict:
    """Both sides of the comparison, from the two sources independently.

    The node set is the tagged components that actually PARTICIPATE in the
    connectivity graph. That is the honest set for this page: the claim is
    about topology, so a component with no stated connection would pad the
    left panel without supporting the argument.
    """
    from extraction.dexpi_parser import parse_dexpi
    from extraction.tag_extractor import extract_tags

    tags_df, conn_df, _ = parse_dexpi(Path(xml_path))
    placed = tags_df[tags_df.tag_name.notna() & tags_df.x_mm.notna()]
    id2tag = dict(zip(placed.id, placed.tag_name))

    # Contract untagged intermediates (nozzle -> pipe segment -> nozzle) into
    # direct tag-to-tag edges. Without this the graph is almost all invisible
    # plumbing — the finding written up in PID_TO_STRUCTURE.md.
    gid = nx.DiGraph()
    for r in conn_df.itertuples():
        if getattr(r, "from_id", None) and getattr(r, "to_id", None):
            gid.add_edge(r.from_id, r.to_id)
    edges: set[tuple[str, str]] = set()
    for u in id2tag:
        if u not in gid:
            continue
        seen, stack = set(), list(gid.successors(u))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in id2tag:
                if id2tag[u] != id2tag[n]:
                    edges.add(tuple(sorted((id2tag[u], id2tag[n]))))  # type: ignore[arg-type]
            else:
                stack.extend(gid.successors(n))

    connected = sorted({t for e in edges for t in e})
    # One position per tag: the centroid, since a tag can occur as several
    # DEXPI elements (an instrument and its function, say).
    pos = (placed[placed.tag_name.isin(connected)]
           .groupby("tag_name")[["x_mm", "y_mm"]].mean())

    found = {_norm(t) for t in extract_tags(Path(pdf_path))}

    nodes = []
    for t in connected:
        if t not in pos.index:
            continue
        nodes.append({"tag": t, "cat": _categorise(t),
                      "x": float(pos.loc[t, "x_mm"]),
                      "y": float(pos.loc[t, "y_mm"]),
                      "pdf": _norm(t) in found})
    keep = {n["tag"] for n in nodes}
    edges = {e for e in edges if e[0] in keep and e[1] in keep}

    return {"nodes": nodes, "edges": sorted(edges),
            "n_found": sum(1 for n in nodes if n["pdf"])}


def _render_html(data: dict, w: int = 820, h: int = 520) -> str:
    """Both panels as one self-contained HTML fragment.

    Generated rather than templated from a file, so what you see is what the
    pipeline just produced. Also downloadable as-is.
    """
    xs = [n["x"] for n in data["nodes"]] or [0]
    ys = [n["y"] for n in data["nodes"]] or [0]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 44

    def sx(x):
        return pad + (x - x0) / max(x1 - x0, 1e-9) * (w - 2 * pad)

    def sy(y):                      # DEXPI y runs bottom-up, SVG top-down
        return pad + (y1 - y) / max(y1 - y0, 1e-9) * (h - 2 * pad)

    plotted = [{**n, "px": round(sx(n["x"]), 1), "py": round(sy(n["y"]), 1)}
               for n in data["nodes"]]
    payload = json.dumps({"nodes": plotted, "edges": data["edges"],
                          "colors": CAT_COLOR})
    n_pdf = data["n_found"]
    n_all = len(data["nodes"])

    return f"""
<style>
 .vs-wrap{{font-family:Inter,-apple-system,'Segoe UI',Roboto,sans-serif;color:#243746}}
 .vs-panels{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
 .vs-panel{{background:#fff;border:1px solid #e3e8ec;border-radius:10px;overflow:hidden}}
 .vs-head{{padding:10px 14px;border-bottom:1px solid #e3e8ec}}
 .vs-title{{font-weight:700;font-size:14px}}
 .vs-stat{{font-size:12px;color:#5c6f7c;font-family:IBM Plex Mono,ui-monospace,Consolas,monospace}}
 .vs-edge{{stroke:#b9c4cc;stroke-width:1.2}}
 .vs-edge.on{{stroke:#007079;stroke-width:2.6}}
 .vs-dot{{cursor:pointer}}
 .vs-lab{{font-size:9px;fill:#5c6f7c;font-family:IBM Plex Mono,ui-monospace,monospace;
   pointer-events:none;opacity:0}}
 .vs-lab.on{{opacity:1;fill:#243746;font-weight:600}}
 .vs-miss{{font-size:11px;fill:#c0392b;font-family:IBM Plex Mono,monospace;
   text-anchor:middle;pointer-events:none}}
 .vs-wm{{font-size:15px;fill:#b0bcc4;text-anchor:middle;font-weight:600}}
 .vs-read{{margin-top:10px;padding:9px 13px;background:#fff;border:1px solid #e3e8ec;
   border-radius:8px;font-size:12.5px;min-height:20px}}
 .vs-read b{{font-family:IBM Plex Mono,ui-monospace,monospace}}
</style>
<div class="vs-wrap">
 <div class="vs-panels">
  <div class="vs-panel">
   <div class="vs-head"><div class="vs-title">From the DEXPI model</div>
    <div class="vs-stat">{n_all} components · {len(data['edges'])} stated connections</div></div>
   <svg id="vsA" viewBox="0 0 {w} {h}" style="width:100%;height:auto"></svg>
  </div>
  <div class="vs-panel">
   <div class="vs-head"><div class="vs-title">From the PDF text layer</div>
    <div class="vs-stat">{n_pdf} of {n_all} components · 0 connections</div></div>
   <svg id="vsB" viewBox="0 0 {w} {h}" style="width:100%;height:auto"></svg>
  </div>
 </div>
 <div class="vs-read" id="vsRead">Hover a component to trace what it connects to.</div>
</div>
<script>
(function(){{
 const D = {payload};
 const byTag = Object.fromEntries(D.nodes.map(n=>[n.tag,n]));
 const adj = {{}}; D.nodes.forEach(n=>adj[n.tag]=new Set());
 D.edges.forEach(([a,b])=>{{ if(adj[a]&&adj[b]){{adj[a].add(b);adj[b].add(a);}} }});
 const NS="http://www.w3.org/2000/svg";
 const el=(t,at)=>{{const e=document.createElementNS(NS,t);
   for(const k in at)e.setAttribute(k,at[k]);return e;}};
 const A=document.getElementById("vsA"), B=document.getElementById("vsB");
 const read=document.getElementById("vsRead");

 // left: full topology
 const edgeEls=[];
 D.edges.forEach(([a,b])=>{{
   const p=byTag[a],q=byTag[b]; if(!p||!q) return;
   const e=el("line",{{x1:p.px,y1:p.py,x2:q.px,y2:q.py,class:"vs-edge"}});
   e.dataset.a=a; e.dataset.b=b; A.appendChild(e); edgeEls.push(e);
 }});
 const dotsA={{}}, labsA={{}};
 D.nodes.forEach(n=>{{
   const c=el("circle",{{cx:n.px,cy:n.py,r:5.5,class:"vs-dot",
     fill:D.colors[n.cat]||D.colors.other,stroke:"#fff","stroke-width":1.5}});
   const l=el("text",{{x:n.px+8,y:n.py+3,class:"vs-lab"}}); l.textContent=n.tag;
   c.addEventListener("mouseenter",()=>hi(n.tag));
   c.addEventListener("mouseleave",()=>hi(null));
   A.appendChild(c); A.appendChild(l); dotsA[n.tag]=c; labsA[n.tag]=l;
 }});

 // right: only what the text layer yielded, and no connections at all
 B.appendChild(Object.assign(el("text",{{x:{w}/2,y:{h}-16,class:"vs-wm"}}),
   {{textContent:"no connectivity in the PDF text layer"}}));
 const dotsB={{}}, labsB={{}};
 D.nodes.forEach(n=>{{
   if(n.pdf){{
     const c=el("circle",{{cx:n.px,cy:n.py,r:5.5,class:"vs-dot",
       fill:D.colors[n.cat]||D.colors.other,stroke:"#fff","stroke-width":1.5}});
     const l=el("text",{{x:n.px+8,y:n.py+3,class:"vs-lab"}}); l.textContent=n.tag;
     c.addEventListener("mouseenter",()=>hi(n.tag));
     c.addEventListener("mouseleave",()=>hi(null));
     B.appendChild(c); B.appendChild(l); dotsB[n.tag]=c; labsB[n.tag]=l;
   }} else {{
     const q=el("text",{{x:n.px,y:n.py+4,class:"vs-miss"}}); q.textContent="?";
     B.appendChild(q);
   }}
 }});

 function hi(tag){{
   edgeEls.forEach(e=>e.classList.toggle("on",
     !!tag && (e.dataset.a===tag||e.dataset.b===tag)));
   const near = tag ? new Set([tag,...adj[tag]]) : new Set();
   for(const t in labsA) labsA[t].classList.toggle("on", near.has(t));
   for(const t in labsB) labsB[t].classList.toggle("on", near.has(t));
   for(const t in dotsA) dotsA[t].setAttribute("r", near.has(t)?7.5:5.5);
   for(const t in dotsB) dotsB[t].setAttribute("r", near.has(t)?7.5:5.5);
   if(!tag){{ read.textContent="Hover a component to trace what it connects to."; return; }}
   const n=byTag[tag], ns=[...adj[tag]];
   const inPdf = n.pdf ? "present in the PDF text layer"
                       : "NOT in the PDF text layer — symbol only";
   read.innerHTML = "<b>"+tag+"</b> — "+inPdf+". DEXPI states "+ns.length+
     " connection(s)"+(ns.length?": <b>"+ns.join("</b>, <b>")+"</b>":"")+
     ". From the PDF alone, none of this is recoverable.";
 }}
}})();
</script>"""


# --------------------------------------------------------------------------- page
page_header("DEXPI vs PDF — same drawing, two sources",
            "tags are text; topology is not · computed live from both sources")

pairs = _pairs()
if not pairs:
    st.error("No drawing has both a DEXPI XML and a PDF under data/raw/. "
             "The comparison needs both sources for the same sheet.")
    st.stop()

_default = next((k for k in pairs if "HO27-P-_E-001-01" in k), list(pairs)[0])
choice = st.selectbox("Drawing", list(pairs),
                      index=list(pairs).index(_default),
                      help="Every sheet that has BOTH a DEXPI export and a "
                           "PDF. Pick any of them — the comparison is "
                           "recomputed, not looked up.")
xml_path, pdf_path = pairs[choice]
data = _build(xml_path, pdf_path)

if not data["nodes"]:
    st.warning("This DEXPI export states no tag-to-tag connections, so there "
               "is no topology to compare. That is itself the finding "
               "described in PID_TO_STRUCTURE.md — connectivity can live "
               "entirely on untagged intermediate elements.")
    st.stop()

n_all = len(data["nodes"])
n_pdf = data["n_found"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Components (DEXPI)", n_all)
c2.metric("Connections (DEXPI)", len(data["edges"]))
c3.metric("Components in the PDF", f"{n_pdf}  ({n_pdf / n_all:.0%})")
c4.metric("Connections from the PDF", "0")

st.caption(
    "Both panels are the same sheet, laid out on the same coordinates. **Left** "
    "is the DEXPI export: every component, and every connection the format "
    "states outright. **Right** is what the PDF text layer gives on its own — "
    "the components whose tags are printed as readable text, and nothing "
    "joining them. A red **?** marks a component DEXPI knows about that the "
    "text layer cannot see: it is drawn as a symbol, with no text to extract. "
    "Hover anything on the left to trace what it connects to.")

html = _render_html(data)
components.html(html, height=620, scrolling=False)

# ---- the ledger ------------------------------------------------------------
missing = [n["tag"] for n in data["nodes"] if not n["pdf"]]
with st.expander(f"📋 What the PDF text layer misses on this sheet ({len(missing)})"):
    if missing:
        st.write(", ".join(f"`{t}`" for t in missing))
        st.caption(
            "These exist in the DEXPI model but not as readable text in the "
            "PDF. No text-extraction rule can recover them — measured across "
            "the validation set, 60 % of missed valve/line tags are in this "
            "category, which puts the ceiling for any pure text method at "
            "~74 % recall. See `Results.md`.")
    else:
        st.success("Every connected component on this sheet is also readable "
                   "text in the PDF. The topology is still absent — that gap "
                   "does not close with better text extraction.")

st.download_button(
    "⬇️ Download this comparison as a standalone HTML file",
    f"<!doctype html><html><head><meta charset='utf-8'>"
    f"<title>DEXPI vs PDF — {choice}</title></head><body "
    f"style='background:#f7f9fa;margin:0;padding:22px'>"
    f"<h2 style='font-family:Inter,sans-serif;color:#243746'>"
    f"DEXPI vs PDF — {choice}</h2>{html}</body></html>",
    file_name=f"dexpi_vs_pdf_{re.sub(r'[^A-Za-z0-9]+', '_', choice)}.html",
    mime="text/html",
    help="Self-contained: opens in any browser without the app, and carries "
         "the numbers you are looking at right now — not a frozen snapshot.")

st.caption(
    "Everything above is recomputed on load by the same modules the rest of "
    "the app uses (`extraction.dexpi_parser`, `extraction.tag_extractor`), so "
    "this page cannot drift from the measured pipeline.")
