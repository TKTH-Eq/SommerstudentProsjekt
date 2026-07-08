"""Build a dependency graph from extracted objects and export it.

Honest scope: we do NOT trace piping/signal lines here (that needs the vector
geometry step). Instead we group tags into functional loops by shared loop id
(system+number) and connect input -> logic -> output within each loop. That is
a defensible first-order structure, and it is clearly labelled as loop-based.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict
import networkx as nx
from config import CATEGORY_COLORS

_ORDER = {"input": 0, "logic": 1, "output": 2, "equipment": 1, "other": 1}


def build_graph(objects) -> nx.DiGraph:
    g = nx.DiGraph()
    for o in objects:
        g.add_node(o.tag, category=o.category, type_code=o.type_code,
                   loop=o.loop, source=o.source)
    loops = defaultdict(list)
    for o in objects:
        loops[o.loop].append(o)
    for members in loops.values():
        members.sort(key=lambda o: _ORDER.get(o.category, 1))
        for a, b in zip(members, members[1:]):
            if a.tag != b.tag:
                g.add_edge(a.tag, b.tag, kind="loop")
    return g


def save_json(g: nx.DiGraph, path: Path):
    path.write_text(json.dumps(nx.node_link_data(g), indent=2))


def save_png(g: nx.DiGraph, path: Path, title="System dependency graph"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = [CATEGORY_COLORS.get(g.nodes[n].get("category", "other"), "#9aa0a6") for n in g]
    try:
        pos = nx.nx_agraph.graphviz_layout(g, prog="dot")
    except Exception:
        pos = nx.spring_layout(g, seed=7, k=0.9)
    fig, ax = plt.subplots(figsize=(16, 11))
    nx.draw_networkx_edges(g, pos, ax=ax, edge_color="#9098a0", arrows=True, arrowsize=10)
    nx.draw_networkx_nodes(g, pos, ax=ax, node_color=colors, node_size=650,
                           edgecolors="white", linewidths=1)
    nx.draw_networkx_labels(g, pos, ax=ax, font_size=6)
    ax.set_title(title, fontsize=15, fontweight="bold"); ax.axis("off")
    fig.tight_layout(); fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)


def interactive_svg(g: nx.DiGraph, w: int = 1000, h: int = 680) -> str:
    """Self-contained pan/zoom SVG (no CDN, works offline). Returns markup."""
    import html as _html
    pos = nx.spring_layout(g, seed=7, k=0.9)
    xs = [p[0] for p in pos.values()] or [0]
    ys = [p[1] for p in pos.values()] or [0]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 40

    def sx(x): return pad + (x - minx) / (maxx - minx + 1e-9) * (w - 2 * pad)
    def sy(y): return pad + (maxy - y) / (maxy - miny + 1e-9) * (h - 2 * pad)

    edges = "".join(
        f'<line x1="{sx(pos[a][0]):.1f}" y1="{sy(pos[a][1]):.1f}" '
        f'x2="{sx(pos[b][0]):.1f}" y2="{sy(pos[b][1]):.1f}" '
        f'stroke="#c3c9d0" stroke-width="1"/>'
        for a, b in g.edges)
    nodes = ""
    for n in g.nodes:
        x, y = sx(pos[n][0]), sy(pos[n][1])
        col = CATEGORY_COLORS.get(g.nodes[n].get("category", "other"), "#9aa0a6")
        lab = _html.escape(str(n))
        nodes += (f'<g class="nd"><title>{lab}</title>'
                  f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{col}" '
                  f'stroke="#fff" stroke-width="1.5"/>'
                  f'<text x="{x:.1f}" y="{y-12:.1f}" text-anchor="middle" '
                  f'font-size="7" fill="#25313f">{lab}</text></g>')

    return f'''<svg id="gsvg" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
 style="width:100%;height:560px;border:1px solid var(--rule);border-radius:8px;
 background:#fcfcfb;cursor:grab;touch-action:none">
<g id="gvp">{edges}{nodes}</g></svg>
<div class="hint">scroll to zoom · drag to pan · double-click to reset</div>
<script>(function(){{
 const svg=document.getElementById('gsvg'),vp=document.getElementById('gvp');
 const VBW={w},VBH={h};let s=1,tx=0,ty=0;
 function apply(){{vp.setAttribute('transform',`translate(${{tx}},${{ty}}) scale(${{s}})`);}}
 function u(e){{const r=svg.getBoundingClientRect();
   return [(e.clientX-r.left)*VBW/r.width,(e.clientY-r.top)*VBH/r.height];}}
 svg.addEventListener('wheel',function(e){{e.preventDefault();
   const [mx,my]=u(e),f=e.deltaY<0?1.1:1/1.1;
   tx=mx-(mx-tx)*f;ty=my-(my-ty)*f;s*=f;apply();}},{{passive:false}});
 let drag=false,px,py;
 svg.addEventListener('pointerdown',function(e){{drag=true;[px,py]=u(e);svg.style.cursor='grabbing';}});
 window.addEventListener('pointermove',function(e){{if(!drag)return;
   const [cx,cy]=u(e);tx+=cx-px;ty+=cy-py;px=cx;py=cy;apply();}});
 window.addEventListener('pointerup',function(){{drag=false;svg.style.cursor='grab';}});
 svg.addEventListener('dblclick',function(){{s=1;tx=0;ty=0;apply();}});
}})();</script>'''


def save_html(g: nx.DiGraph, path: Path, title="System dependency graph"):
    """Self-contained interactive graph (vis-network from CDN)."""
    nodes = [{"id": n, "label": n,
              "color": CATEGORY_COLORS.get(g.nodes[n].get("category", "other"), "#9aa0a6")}
             for n in g.nodes]
    edges = [{"from": a, "to": b} for a, b in g.edges]
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>#net{{width:100%;height:90vh;border:1px solid #ddd}}body{{font-family:sans-serif}}</style>
</head><body><h3>{title}</h3><div id="net"></div><script>
const nodes=new vis.DataSet({json.dumps(nodes)});
const edges=new vis.DataSet({json.dumps(edges)});
new vis.Network(document.getElementById('net'),{{nodes,edges}},
 {{physics:{{stabilization:true}},edges:{{arrows:'to'}}}});
</script></body></html>"""
    path.write_text(html)