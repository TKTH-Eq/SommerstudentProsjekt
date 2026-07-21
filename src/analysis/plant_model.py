"""
Plant model: stitch every DEXPI drawing into ONE dependency graph.

Why: every tool in this project — failure explorer, root cause, the alarm
shower with its AI brief — operates per drawing, because that is all a
document-centric world allows. But faults do not respect sheet boundaries.
This module builds the plant-wide graph that makes cross-drawing reasoning
possible, using two stitch mechanisms the structured data provides:

  SHARED LINE NUMBERS   the same piping-line tag (e.g. 4"-PV-274599-ED200-4)
                        appearing on two drawings IS the same physical line;
                        the tagged elements nearest to it on each sheet are
                        connected with kind="cross_drawing" edges.

  SHARED COMPONENT TAGS the same component tag on two drawings is the same
                        physical component; its nodes merge into one, which
                        fuses the per-drawing graphs at that point.

Direction across a line stitch is not stated in the export (off-page
connectors carry FlowIn/FlowOut but no names), so cross-drawing edges are
added BOTH ways and marked as such — reachability is preserved, direction
is approximate. That is a documentable limitation, and itself an input to
the minimum-requirement set: consistent line numbering and named off-page
references are what make a plant model cheap to build.

Everything downstream (failure_map, root_cause, control_room, the Streamlit
pages) takes an arbitrary graph, so the plant model plugs in unchanged —
same tools, whole plant.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

if __name__ == "__main__" and __package__ is None:      # direct run support
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction.dexpi_parser import parse_dexpi
from analysis.hazop_dexpi import load_dexpi_model

MAX_STITCH_TAGS = 3        # nearest tags per drawing-side of a line stitch
NEAR_HOPS = 4              # how far from a segment we look for tagged anchors


def _line_anchor_tags(xml_path: Path, tagged: set[str]) -> dict[str, list[str]]:
    """{line tag: [nearest component tags on this drawing]}.

    Uses the raw ID-level connection graph: from each piping segment that
    carries the line tag, walk outward a few hops and collect the first
    tagged elements met — the components that physically sit on that line.
    """
    tags_df, conn_df, _ = parse_dexpi(xml_path)
    id2tag = dict(zip(tags_df[tags_df.tag_name.notna()].id,
                      tags_df[tags_df.tag_name.notna()].tag_name))
    g = nx.Graph()
    for r in conn_df.itertuples():
        if r.from_id and r.to_id:
            g.add_edge(r.from_id, r.to_id)
    # containment: a segment's components are its CHILDREN in the XML —
    # connections alone never reference the segment ID itself (same lesson
    # as hazop_dexpi's section building)
    import xml.etree.ElementTree as ET
    _PHYS = {"Equipment", "ActuatingSystem", "PipingNetworkSegment",
             "PipingNetworkSystem", "ProcessInstrumentationFunction",
             "ActuatingFunction", "InstrumentationLoopFunction"}

    def _walk(el, pid, pkind):
        eid = el.get("ID")
        if eid and pid and pkind in _PHYS:
            g.add_edge(pid, eid)
        if eid:
            pid, pkind = eid, el.tag
        for ch in el:
            _walk(ch, pid, pkind)

    _walk(ET.parse(xml_path).getroot(), None, None)

    segs = tags_df[(tags_df.category == "piping_segment") & tags_df.tag_name.notna()]
    by_line: dict[str, list[str]] = defaultdict(list)
    for r in segs.itertuples():
        if r.id not in g:
            continue
        seen, frontier, found = {r.id}, [r.id], []
        for _ in range(NEAR_HOPS):
            nxt = []
            for n in frontier:
                for m in g.neighbors(n):
                    if m in seen:
                        continue
                    seen.add(m)
                    t = id2tag.get(m)
                    if t and t in tagged:
                        found.append(t)
                    else:
                        nxt.append(m)
            frontier = nxt
            if len(found) >= MAX_STITCH_TAGS:
                break
        for t in found[:MAX_STITCH_TAGS]:
            if t not in by_line[r.tag_name]:
                by_line[r.tag_name].append(t)
    return by_line


def build_plant_model(raw_dir: Path) -> dict:
    """Load every DEXPI file, merge on shared tags, stitch on shared lines.

    Returns {graph, objects, drawings_of, stitches, stats}:
      graph      nx.DiGraph over tags; cross-drawing edges have
                 kind="cross_drawing" and line=<line tag>
      objects    [EngineeringObject] — one per unique tag
      drawings_of {tag: [drawing stems]} — provenance for the UI
      stitches   [(line, drawing_a, drawing_b, tags_a, tags_b)]
    """
    files = sorted(Path(raw_dir).rglob("*.DGN.xml"))
    G = nx.DiGraph()
    objects: dict[str, object] = {}
    drawings_of: dict[str, list[str]] = defaultdict(list)
    line_anchors: dict[str, dict[str, list[str]]] = {}   # drawing -> line -> tags

    all_stems = []
    for x in files:
        stem = x.stem.replace(".DGN", "")
        all_stems.append(stem)
        m = load_dexpi_model(x)
        for o in m["objects"]:
            if o.tag not in objects:
                objects[o.tag] = o
            drawings_of[o.tag].append(stem)
        for n, data in m["tag_graph"].nodes(data=True):
            if n not in G:
                G.add_node(n, **data)
        for u, v in m["tag_graph"].edges():
            G.add_edge(u, v, kind="in_drawing", drawing=stem)
        line_anchors[stem] = _line_anchor_tags(x, {o.tag for o in m["objects"]})

    # ---- line-number stitches ----------------------------------------------
    stitches = []
    stems = list(line_anchors)
    for i, a in enumerate(stems):
        for b in stems[i + 1:]:
            for line in set(line_anchors[a]) & set(line_anchors[b]):
                ta, tb = line_anchors[a][line], line_anchors[b][line]
                if not ta or not tb:
                    continue
                stitches.append((line, a, b, ta, tb))
                for x1 in ta:
                    for x2 in tb:
                        if x1 == x2:
                            continue        # same component: already merged
                        G.add_edge(x1, x2, kind="cross_drawing", line=line)
                        G.add_edge(x2, x1, kind="cross_drawing", line=line)

    shared_tags = sum(1 for t, ds in drawings_of.items() if len(set(ds)) > 1)
    cross_edges = sum(1 for _, _, d in G.edges(data=True)
                      if d.get("kind") == "cross_drawing")
    return {
        "graph": G,
        "drawings": all_stems,
        "objects": list(objects.values()),
        "drawings_of": {t: sorted(set(ds)) for t, ds in drawings_of.items()},
        "stitches": stitches,
        "stats": {"drawings": len(files), "tags": len(objects),
                  "edges": G.number_of_edges(), "cross_edges": cross_edges,
                  "line_stitches": len(stitches), "shared_tags": shared_tags},
    }


if __name__ == "__main__":
    # quick check:  python src/analysis/plant_model.py [data/raw]
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")
    M = build_plant_model(raw)
    print("Anleggsmodell:", M["stats"], "\n")
    print("Eksempler på sømmer (linje: tegning A <-> tegning B):")
    for line, a, b, ta, tb in M["stitches"][:6]:
        print(f"  {line}\n    {a[-14:]}: {ta}\n    {b[-14:]}: {tb}")
    # finn en kaskade som faktisk krysser tegninger
    from analysis.control_room import scenario_order
    best = None
    for n in M["graph"].nodes:
        order = scenario_order(M["graph"], n)
        drawn = {d for t in order for d in M["drawings_of"].get(t, [])}
        if len(drawn) > 1 and (best is None or len(order) > len(best[1])):
            best = (n, order, drawn)
    if best:
        n, order, drawn = best
        print(f"\nStørste kryss-tegnings-kaskade: feil i {n} -> "
              f"{len(order)} alarmer over {len(drawn)} tegninger:")
        for d in sorted(drawn):
            print(f"  {d[-14:]}")

# ---------------------------------------------------------------------------
# Metro map: the plant at DRAWING level — 17 readable nodes, not 885
# ---------------------------------------------------------------------------

def metro_svg(model: dict, w: int = 980, h: int = 560) -> str:
    """Self-contained SVG of the drawing-level metagraph: one node per
    drawing (coloured by system), one edge per drawing pair that shares at
    least one line number, edge width by number of shared lines, hover
    title listing them. Readable in three seconds — the establishing shot
    before any plant-wide demo."""
    import html as _html
    import math
    from collections import defaultdict

    # drawings and their pairwise stitches
    stitched = defaultdict(list)
    for line, a, b, _, _ in model["stitches"]:
        stitched[tuple(sorted((a, b)))].append(line)
    drawings = sorted(model.get("drawings") or
                      {d for ds in model["drawings_of"].values() for d in ds})

    palette = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8", "#c98a1b",
               "#12233b", "#5aa8a0", "#a83a5f"]
    systems = sorted({d[-14:-12] if len(d) >= 14 else "??" for d in drawings})
    sys_color = {s: palette[i % len(palette)] for i, s in enumerate(systems)}

    # circle layout, grouped by system so related sheets sit together
    order = sorted(drawings, key=lambda d: d[-14:])
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 70
    pos = {d: (cx + r * math.cos(2 * math.pi * i / len(order) - math.pi / 2),
               cy + r * math.sin(2 * math.pi * i / len(order) - math.pi / 2))
           for i, d in enumerate(order)}

    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
             f'style="width:100%;height:auto;font-family:sans-serif">']
    for (a, b), lines in sorted(stitched.items()):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        title = _html.escape("; ".join(lines))
        parts.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="#8a93a0" stroke-width="{1 + 1.5 * len(lines):.1f}" '
            f'opacity="0.8"><title>{len(lines)} delt(e) linje(r): {title}'
            f'</title></line>')
    for d, (x, y) in pos.items():
        s = d[-14:-12] if len(d) >= 14 else "??"
        n_tags = sum(1 for ds in model["drawings_of"].values() if d in ds)
        label = _html.escape(d[-14:])
        parts.append(
            f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="16" '
            f'fill="{sys_color[s]}"><title>{label} — {n_tags} tags'
            f'</title></circle>'
            f'<text x="{x:.0f}" y="{y - 22:.0f}" text-anchor="middle" '
            f'font-size="11" fill="#e8e8e8">{label}</text>'
            f'<text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" '
            f'font-size="10" fill="#fff" font-weight="bold">{s}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


_METRO_HTML = (
    '<div id="metro-__UID__" style="position:relative;width:100%;'
    'height:__H__px;background:#141820;border-radius:10px;overflow:hidden;'
    'user-select:none;font-family:sans-serif">'
    '<svg id="svg-__UID__" width="100%" height="100%" viewBox="0 0 __W__ __H__" '
    'preserveAspectRatio="xMidYMid meet" style="cursor:grab;display:block">'
    '<g id="scene-__UID__"><g id="edges-__UID__"></g>'
    '<g id="nodes-__UID__"></g></g></svg>'
    '<div id="legend-__UID__" style="position:absolute;left:10px;top:8px;'
    'font-size:12px;color:#cfd6df;background:#000000aa;padding:6px 9px;'
    'border-radius:8px;max-width:72%;line-height:1.7"></div>'
    '<div id="tip-__UID__" style="position:absolute;pointer-events:none;'
    'opacity:0;font-size:12px;color:#fff;background:#000000e0;padding:5px 8px;'
    'border-radius:6px;transform:translate(10px,-130%);white-space:nowrap;'
    'z-index:5;transition:opacity .08s"></div>'
    '<div style="position:absolute;right:10px;bottom:8px;font-size:11px;'
    'color:#8a93a0;background:#00000088;padding:3px 8px;border-radius:6px;'
    'pointer-events:none">scroll = zoom &middot; dra bakgrunn = panorer '
    '&middot; dra node = flytt &middot; dobbeltklikk = reset</div>'
    '</div><script>__JS__</script>')

_METRO_JS = r"""
(function(){
  var D = /*DATA*/;
  var U="__UID__";
  var g=function(id){return document.getElementById(id+"-"+U);};
  var svg=g("svg"),scene=g("scene"),eG=g("edges"),nG=g("nodes"),
      wrap=g("metro"),tip=g("tip"),legend=g("legend");
  var NS="http://www.w3.org/2000/svg";
  var nodes=D.nodes,edges=D.edges,byId={};
  nodes.forEach(function(n){byId[n.id]=n;});
  var nbr={}; nodes.forEach(function(n){nbr[n.id]={};});
  edges.forEach(function(e){nbr[e.a][e.b]=1;nbr[e.b][e.a]=1;});
  function clamp(v,a,b){return Math.min(Math.max(v,a),b);}

  var eEl={};
  edges.forEach(function(e,i){
    var l=document.createElementNS(NS,"line");
    l.setAttribute("stroke","#8a93a0");
    l.setAttribute("stroke-linecap","round");
    l.style.cursor="pointer";
    l.addEventListener("mouseenter",function(){showEdge(e);});
    l.addEventListener("mousemove",moveTip);
    l.addEventListener("mouseleave",hideTip);
    eG.appendChild(l); eEl[i]=l;
  });
  var nEl={};
  nodes.forEach(function(n){
    var gg=document.createElementNS(NS,"g"); gg.style.cursor="grab";
    var c=document.createElementNS(NS,"circle");
    c.setAttribute("r","16"); c.setAttribute("fill",n.color);
    c.setAttribute("stroke","#0c0f14"); c.setAttribute("stroke-width","2");
    var t1=document.createElementNS(NS,"text");
    t1.setAttribute("text-anchor","middle"); t1.setAttribute("font-size","11");
    t1.setAttribute("fill","#e8e8e8"); t1.textContent=n.label;
    var t2=document.createElementNS(NS,"text");
    t2.setAttribute("text-anchor","middle"); t2.setAttribute("font-size","10");
    t2.setAttribute("fill","#fff"); t2.setAttribute("font-weight","bold");
    t2.textContent=n.sys;
    gg.appendChild(c); gg.appendChild(t1); gg.appendChild(t2);
    gg.addEventListener("mouseenter",function(){hoverN=n.id;refresh();showNode(n);});
    gg.addEventListener("mousemove",moveTip);
    gg.addEventListener("mouseleave",function(){hoverN=null;refresh();hideTip();});
    gg.addEventListener("mousedown",function(ev){dragN=n;dragMoved=false;ev.stopPropagation();});
    gg.addEventListener("click",function(ev){ev.stopPropagation();
      if(dragMoved){dragMoved=false;return;}
      pin=(pin===n.id?null:n.id); refresh();});
    nG.appendChild(gg); nEl[n.id]={g:gg,c:c,t1:t1,t2:t2};
  });

  function place(n){var e=nEl[n.id];
    e.c.setAttribute("cx",n.x); e.c.setAttribute("cy",n.y);
    e.t1.setAttribute("x",n.x); e.t1.setAttribute("y",n.y-22);
    e.t2.setAttribute("x",n.x); e.t2.setAttribute("y",n.y+4);}
  function placeEdge(e,i){var A=byId[e.a],B=byId[e.b],l=eEl[i];
    l.setAttribute("x1",A.x); l.setAttribute("y1",A.y);
    l.setAttribute("x2",B.x); l.setAttribute("y2",B.y);}
  nodes.forEach(place); edges.forEach(placeEdge);

  var k=1,tx=0,ty=0;
  function applyT(){scene.setAttribute("transform","translate("+tx+","+ty+") scale("+k+")");}
  applyT();
  function rootPt(ev){var m=svg.getScreenCTM().inverse();var p=svg.createSVGPoint();
    p.x=ev.clientX;p.y=ev.clientY;return p.matrixTransform(m);}
  function scenePt(ev){var m=scene.getScreenCTM().inverse();var p=svg.createSVGPoint();
    p.x=ev.clientX;p.y=ev.clientY;return p.matrixTransform(m);}
  svg.addEventListener("wheel",function(ev){ev.preventDefault();var r=rootPt(ev);
    var f=ev.deltaY<0?1.2:0.83,nk=clamp(k*f,0.3,6);
    tx=r.x-(r.x-tx)*(nk/k);ty=r.y-(r.y-ty)*(nk/k);k=nk;applyT();},{passive:false});
  var panning=false,sR=null,tx0=0,ty0=0,dragN=null,dragMoved=false;
  svg.addEventListener("mousedown",function(ev){panning=true;sR=rootPt(ev);
    tx0=tx;ty0=ty;svg.style.cursor="grabbing";});
  window.addEventListener("mousemove",function(ev){
    if(dragN){var s=scenePt(ev);dragN.x=s.x;dragN.y=s.y;dragMoved=true;place(dragN);
      edges.forEach(function(e,i){if(e.a===dragN.id||e.b===dragN.id)placeEdge(e,i);});return;}
    if(panning){var c=rootPt(ev);tx=tx0+(c.x-sR.x);ty=ty0+(c.y-sR.y);applyT();}});
  window.addEventListener("mouseup",function(){panning=false;dragN=null;svg.style.cursor="grab";});
  svg.addEventListener("dblclick",function(){k=1;tx=0;ty=0;applyT();});

  var hoverN=null,pin=null,activeSys={};
  function anySys(){for(var s in activeSys)return true;return false;}
  function refresh(){
    var focus=(pin!=null?pin:hoverN);
    nodes.forEach(function(n){
      var vis=!anySys()||activeSys[n.sys];var op=vis?1:0.12;
      if(focus!=null && !(n.id===focus||nbr[focus][n.id])) op=Math.min(op,0.14);
      nEl[n.id].g.setAttribute("opacity",op);});
    edges.forEach(function(e,i){
      var A=byId[e.a],B=byId[e.b];
      var vis=!anySys()||activeSys[A.sys]||activeSys[B.sys];
      var op=vis?0.75:0.06,w=1+1.4*e.n,col="#8a93a0";
      if(focus!=null){ if(e.a===focus||e.b===focus){op=0.95;w+=1.6;col="#cfd6df";}
        else {op=Math.min(op,0.05);} }
      eEl[i].setAttribute("opacity",op);
      eEl[i].setAttribute("stroke-width",w.toFixed(1));
      eEl[i].setAttribute("stroke",col);});
  }

  function moveTip(ev){var r=wrap.getBoundingClientRect();
    tip.style.left=(ev.clientX-r.left)+"px";tip.style.top=(ev.clientY-r.top)+"px";}
  function showNode(n){tip.innerHTML="<b>"+n.label+"</b><br>system "+n.sys+" &middot; "
    +n.tags+" tags &middot; "+Object.keys(nbr[n.id]).length+" naboer";tip.style.opacity=1;}
  function showEdge(e){var A=byId[e.a],B=byId[e.b];var x=(e.n>e.lines.length?" \u2026":"");
    tip.innerHTML="<b>"+A.label+" \u2194 "+B.label+"</b><br>"+e.n
    +" delt(e) linje(r): "+e.lines.join(", ")+x;tip.style.opacity=1;}
  function hideTip(){tip.style.opacity=0;}

  var badges=[];
  D.systems.forEach(function(s){
    var b=document.createElement("span");
    b.style.cssText="display:inline-flex;align-items:center;gap:4px;"
      +"margin:1px 9px 1px 0;cursor:pointer";
    b.innerHTML='<span style="width:11px;height:11px;border-radius:50%;'
      +'background:'+s.color+';display:inline-block"></span>'+s.sys;
    b.addEventListener("click",function(){
      if(activeSys[s.sys])delete activeSys[s.sys];else activeSys[s.sys]=1;
      sync();refresh();});
    legend.appendChild(b);badges.push([s.sys,b]);});
  var hint=document.createElement("div");
  hint.style.cssText="color:#8a93a0;margin-top:3px;font-size:11px";
  hint.textContent="klikk et system for \u00e5 framheve \u00b7 klikk en node for \u00e5 l\u00e5se";
  legend.appendChild(hint);
  function sync(){badges.forEach(function(p){
    p[1].style.opacity=(!anySys()||activeSys[p[0]])?1:0.4;});}
  refresh();
})();
"""


def metro_html(model: dict, w: int = 980, h: int = 600) -> str:
    """Interactive, dependency-free drawing-level metagraph (same inline-JS
    approach as hazop._zoomable_image): one node per drawing (colour =
    system), one edge per drawing pair sharing a line number (width =
    #shared lines). Wheel-zoom, background-pan, node drag, hover-highlight
    of a node's neighbours, real tooltips, and a clickable system legend.

    Layout is a deterministic networkx spring layout so the map is stable
    between runs; the interactivity does the rest. Falls back to the static
    metro_svg only if a caller wants a plain image.
    """
    import html as _html  # noqa: F401  (kept for parity; labels are safe)
    import json
    import math
    import secrets
    from collections import defaultdict

    stitched = defaultdict(list)
    for line, a, b, _, _ in model["stitches"]:
        stitched[tuple(sorted((a, b)))].append(line)
    drawings = sorted(model.get("drawings") or
                      {d for ds in model["drawings_of"].values() for d in ds})
    if not drawings:
        return ("<div style='color:#8a93a0;padding:20px;font-family:sans-serif'>"
                "Ingen tegninger i modellen.</div>")

    palette = ["#2d7dd2", "#b8442c", "#3a7d44", "#8e5aa8", "#c98a1b",
               "#5aa8a0", "#a83a5f", "#6b705c", "#3f6d9e", "#9e6b3f"]

    def _sys(d):
        return d[-14:-12] if len(d) >= 14 else "??"

    systems = sorted({_sys(d) for d in drawings})
    sys_color = {s: palette[i % len(palette)] for i, s in enumerate(systems)}
    tag_count = {d: sum(1 for ds in model["drawings_of"].values() if d in ds)
                 for d in drawings}

    # deterministic layout in viewBox coordinates
    gr = nx.Graph()
    gr.add_nodes_from(drawings)
    for (a, b), lines in stitched.items():
        gr.add_edge(a, b, weight=len(lines))
    if len(drawings) > 2 and gr.number_of_edges():
        raw = nx.spring_layout(gr, seed=7, weight="weight", iterations=200)
    else:
        raw = {d: (math.cos(2 * math.pi * i / len(drawings)),
                   math.sin(2 * math.pi * i / len(drawings)))
               for i, d in enumerate(drawings)}
    xs = [p[0] for p in raw.values()]
    ys = [p[1] for p in raw.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    m = 60

    def _sx(x):
        return m + (x - x0) / ((x1 - x0) or 1) * (w - 2 * m)

    def _sy(y):
        return m + (y - y0) / ((y1 - y0) or 1) * (h - 2 * m)

    id_of = {d: i for i, d in enumerate(drawings)}
    nodes = [{"id": id_of[d], "label": d[-14:], "sys": _sys(d),
              "color": sys_color[_sys(d)], "tags": tag_count[d],
              "x": round(_sx(raw[d][0]), 1), "y": round(_sy(raw[d][1]), 1)}
             for d in drawings]
    edges = [{"a": id_of[a], "b": id_of[b], "n": len(lines), "lines": lines[:20]}
             for (a, b), lines in sorted(stitched.items())]
    data = {"nodes": nodes, "edges": edges,
            "systems": [{"sys": s, "color": sys_color[s]} for s in systems]}

    uid = secrets.token_hex(3)
    js = (_METRO_JS.replace("__UID__", uid)
                   .replace("/*DATA*/", json.dumps(data)))
    return (_METRO_HTML.replace("__UID__", uid)
                       .replace("__W__", str(w))
                       .replace("__H__", str(h))
                       .replace("__JS__", js))


def plant_criticality(model: dict, top: int = 10) -> list[dict]:
    """Most structurally connected components across the WHOLE plant —
    the exposure ranking no per-drawing view can produce. Degree counts
    in-drawing edges only, so bidirectional cross-stitches don't inflate."""
    G = model["graph"]
    deg = {}
    for n in G.nodes:
        d = sum(1 for _, _, e in G.edges(n, data=True)
                if e.get("kind") != "cross_drawing")
        d += sum(1 for _, _, e in G.in_edges(n, data=True)
                 if e.get("kind") != "cross_drawing")
        deg[n] = d
    by_tag = {o.tag: o for o in model["objects"]}
    out = []
    for t in sorted(deg, key=deg.get, reverse=True)[:top]:
        out.append({"tag": t, "koblinger": deg[t],
                    "kategori": by_tag[t].category if t in by_tag else "?",
                    "tegninger": ", ".join(d[-14:] for d in
                                           model["drawings_of"].get(t, []))})
    return out