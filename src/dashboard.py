"""
Generate a self-contained HTML dashboard from the pipeline results.

    python src/dashboard.py 27      -> reports/index.html  (double-click to open)

Everything (styles + graph image) is inlined, so the file opens in any browser
with no server and no internet. Reuses the same extraction/analysis modules as
main.py, so the dashboard and the pipeline can never disagree.
"""
from __future__ import annotations
import sys, os, json, html
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PID_DIR, SCD_DIR, REPORTS, CATEGORY_COLORS
from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph, save_png, interactive_svg
from analysis.consistency_check import check_consistency
from analysis.kpi_analysis import compute_kpis, quality_flags
from analysis.analyze_scd import safety_register, failure_map
from ai.operator_brief import briefs_for
from main import resolve_inputs


def _chip(tag: str, objs_by_tag: dict) -> str:
    cat = objs_by_tag.get(tag).category if tag in objs_by_tag else "other"
    col = CATEGORY_COLORS.get(cat, "#9aa0a6")
    return f'<span class="chip" style="--c:{col}">{html.escape(tag)}</span>'


def build_dashboard(system: str) -> Path:
    pid_pdf, scd_pdf, system = resolve_inputs(["dashboard.py", system])
    pid = create_objects(extract_tags(pid_pdf), "P&ID")
    scd = create_objects(extract_tags(scd_pdf), "SCD")
    allo = sorted(set(pid) | set(scd), key=lambda o: o.tag)
    by_tag = {o.tag: o for o in allo}

    g = build_graph(allo)
    REPORTS.mkdir(parents=True, exist_ok=True)
    save_png(g, REPORTS / "system_dependency_graph.png", f"System {system}")  # keep static copy
    graph_svg = interactive_svg(g)
    fmap = failure_map(g, allo)
    briefs = briefs_for(fmap, allo)          # template unless ANTHROPIC_API_KEY is set
    ai_on = bool(os.getenv("ANTHROPIC_API_KEY"))
    pick_options = "".join(f'<option value="{html.escape(t)}">{html.escape(t)}</option>'
                           for t in sorted(fmap))
    fail_json = json.dumps(fmap)
    briefs_json = json.dumps(briefs)
    colors_json = json.dumps(CATEGORY_COLORS)

    cons = check_consistency(pid, scd)
    kpis = compute_kpis(g, allo)
    flags = quality_flags(allo)
    safety = safety_register(allo, REPORTS / "safety_register.csv")
    c = kpis["by_category"]

    def chips(tags): return "".join(_chip(t, by_tag) for t in tags) or "<em>none</em>"

    flag_rows = "".join(
        f"<tr><td class='mono'>{html.escape(t)}</td>"
        f"<td>logic reference not found on P&amp;ID</td>"
        f"<td><span class='pill review'>verify</span></td></tr>"
        for t in cons["scd_only"])
    quality_rows = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
    safety_chips = chips(sorted(o.tag for o in safety))

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System {system} — drawing analysis</title>
<style>{_CSS}</style></head><body>
<header class="titleblock">
  <div class="tb-grid">
    <div class="tb-left">
      <div class="eyebrow">Huldra Haleproduksjon · Drawing analysis</div>
      <h1>System {system}<span>Export Booster Compressor</span></h1>
    </div>
    <div class="tb-right">
      <div><span>P&amp;ID</span><code>{html.escape(pid_pdf.stem)}</code></div>
      <div><span>SCD</span><code>{html.escape(scd_pdf.stem)}</code></div>
    </div>
  </div>
  <div class="disclaimer">Extracted automatically from legacy PDFs — a draft for engineer review, not an authoritative source.</div>
</header>

<main>
  <section class="kpis">
    <div class="kpi"><div class="num">{kpis['components']}</div><div class="lab">components</div></div>
    <div class="kpi"><div class="num">{kpis['functional_loops']}</div><div class="lab">functional loops</div></div>
    <div class="kpi"><div class="num">{len(safety)}</div><div class="lab">safety-related tags</div></div>
    <div class="kpi flag"><div class="num">{len(cons['scd_only'])}</div><div class="lab">to verify</div></div>
  </section>

  <section class="panel">
    <h2>P&amp;ID ↔ SCD consistency</h2>
    <p class="sub">Do the physical drawing and the control logic agree on which tags exist?</p>
    <div class="cols3">
      <div><h3>On both <b>{len(cons['both'])}</b></h3><div class="chips">{chips(cons['both'])}</div></div>
      <div><h3>P&amp;ID only <b>{len(cons['pid_only'])}</b></h3><p class="note">usually expected — local indicators, position switches, relief valves</p><div class="chips">{chips(cons['pid_only'])}</div></div>
      <div class="verify"><h3>SCD only <b>{len(cons['scd_only'])}</b></h3><p class="note">logic references not on the P&amp;ID — check these</p><div class="chips">{chips(cons['scd_only'])}</div></div>
    </div>
  </section>

  <section class="two">
    <div class="panel">
      <h2>Flagged for review</h2>
      <table><thead><tr><th>tag</th><th>issue</th><th></th></tr></thead>
      <tbody>{flag_rows or '<tr><td colspan=3><em>none</em></td></tr>'}</tbody></table>
      <h3 class="mt">Quality flags</h3><ul class="quality">{quality_rows}</ul>
    </div>
    <div class="panel">
      <h2>Safety register</h2>
      <p class="sub">Tags carrying a shutdown / protection role.</p>
      <div class="chips">{safety_chips}</div>
    </div>
  </section>

  <section class="panel">
    <h2>Failure explorer</h2>
    <p class="sub">Pick a tag (or click a node in the graph) to see what can go wrong,
    what it affects, and where a symptom here could come from. Structural, from the
    loop model — a prompt for the engineer, not a probability or a diagnosis.</p>
    <select id="pick"><option value="">— select a tag —</option>{pick_options}</select>
    <button id="fxreset" type="button">clear</button>
    <div id="fxbody" class="fx" hidden>
      <div class="fxhead"><span class="chip" id="fx-tagchip"></span>
        <span id="fx-cat" class="fx-cat"></span>
        <span class="brief-badge">{"AI briefing" if ai_on else "operator briefing · template"}</span></div>
      <pre id="fx-brief" class="brief"></pre>
      <div class="fxgrid">
        <div><h3>What can go wrong</h3><ul id="fx-modes" class="modes"></ul></div>
        <div class="fx-cons"><h3>If it fails → affected</h3>
          <div class="fxlab">safety functions</div><div id="fx-safety" class="chips"></div>
          <div class="fxlab">all downstream</div><div id="fx-down" class="chips"></div></div>
        <div class="fx-cause"><h3>Possible cause of a symptom here</h3>
          <div class="fxlab">upstream candidates</div><div id="fx-up" class="chips"></div></div>
      </div>
    </div>
  </section>

  <section class="panel">
    <h2>Dependency graph</h2>
    <p class="sub">Tags grouped into functional loops (input → logic → output). Loop-based, not traced piping.</p>
    <div class="legend">
      <span style="--c:{CATEGORY_COLORS['input']}">input</span>
      <span style="--c:{CATEGORY_COLORS['logic']}">logic</span>
      <span style="--c:{CATEGORY_COLORS['output']}">output</span>
      <span style="--c:{CATEGORY_COLORS['equipment']}">equipment</span>
      <span class="hl-sel">selected</span>
      <span class="hl-down">downstream (consequence)</span>
      <span class="hl-up">upstream (possible cause)</span>
    </div>
    {graph_svg}
  </section>
</main>
<footer>Generated by the Huldra P&amp;ID/SCD analysis tool · summer-student project</footer>
<script>(function(){{
 const FAIL={fail_json}, COLORS={colors_json}, BRIEFS={briefs_json};
 const pick=document.getElementById('pick'), body=document.getElementById('fxbody');
 function chip(t){{const cat=(FAIL[t]||{{}}).category||'other';
   return '<span class="chip" style="--c:'+(COLORS[cat]||'#9aa0a6')+'">'+t+'</span>';}}
 function chips(a){{return a.length?a.map(chip).join(''):'<em>none in loop model</em>';}}
 function hl(tag,f){{const d=new Set(f.downstream),u=new Set(f.upstream);
   document.querySelectorAll('#gsvg circle.node').forEach(function(c){{
     const t=c.getAttribute('data-tag');
     if(t===tag){{c.setAttribute('stroke','#12233b');c.setAttribute('stroke-width','3.5');c.style.opacity=1;}}
     else if(d.has(t)){{c.setAttribute('stroke','#b8442c');c.setAttribute('stroke-width','2.5');c.style.opacity=1;}}
     else if(u.has(t)){{c.setAttribute('stroke','#2d7dd2');c.setAttribute('stroke-width','2.5');c.style.opacity=1;}}
     else{{c.setAttribute('stroke','#fff');c.setAttribute('stroke-width','1.5');c.style.opacity=0.12;}}
   }});}}
 function reset(){{document.querySelectorAll('#gsvg circle.node').forEach(function(c){{
   c.setAttribute('stroke','#fff');c.setAttribute('stroke-width','1.5');c.style.opacity=1;}});}}
 function select(tag){{const f=FAIL[tag];if(!f){{body.hidden=true;reset();return;}}
   pick.value=tag;body.hidden=false;
   document.getElementById('fx-tagchip').outerHTML='<span class="chip" id="fx-tagchip" style="--c:'+(COLORS[f.category]||'#9aa0a6')+'">'+tag+'</span>';
   document.getElementById('fx-cat').textContent=f.category;
   document.getElementById('fx-brief').textContent=BRIEFS[tag]||'';
   document.getElementById('fx-modes').innerHTML=f.modes.map(function(m){{return '<li>'+m+'</li>';}}).join('');
   document.getElementById('fx-safety').innerHTML=chips(f.safety);
   document.getElementById('fx-down').innerHTML=chips(f.downstream);
   document.getElementById('fx-up').innerHTML=chips(f.upstream);
   hl(tag,f);}}
 pick.addEventListener('change',function(){{this.value?select(this.value):(body.hidden=true,reset());}});
 document.getElementById('fxreset').addEventListener('click',function(){{pick.value='';body.hidden=true;reset();}});
 document.getElementById('gsvg').addEventListener('click',function(e){{
   const c=e.target.closest('circle.node');if(c)select(c.getAttribute('data-tag'));}});
}})();</script>
</body></html>"""

    out = REPORTS / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out


_CSS = """
:root{--ink:#12233b;--paper:#f7f6f2;--rule:#d7d3c8;--muted:#5f6b7a;
--blue:#2d7dd2;--amber:#e08a1e;--review:#b8442c;--panel:#ffffff}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5}
.mono,code,.chip{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
main{max-width:1100px;margin:0 auto;padding:0 20px 40px}
/* title block */
.titleblock{border-bottom:3px solid var(--ink);background:var(--panel)}
.tb-grid{max-width:1100px;margin:0 auto;padding:22px 20px 14px;display:flex;
justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{margin:.15em 0 0;font-size:40px;font-weight:800;letter-spacing:-.02em}
h1 span{display:block;font-size:16px;font-weight:500;color:var(--muted);letter-spacing:0}
.tb-right{font-size:12px;text-align:right}
.tb-right div{padding:3px 0;border-top:1px solid var(--rule)}
.tb-right span{display:inline-block;width:44px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}
.tb-right code{font-size:12px}
.disclaimer{max-width:1100px;margin:0 auto;padding:8px 20px;font-size:12.5px;
color:var(--muted);background:var(--paper)}
/* kpis */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0}
.kpi{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:18px 20px}
.kpi .num{font-size:38px;font-weight:800;line-height:1}
.kpi .lab{font-size:12.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:6px}
.kpi.flag{border-color:var(--review)}
.kpi.flag .num{color:var(--review)}
/* panels */
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
padding:22px 24px;margin:16px 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.two .panel{margin:0}
h2{margin:0 0 2px;font-size:19px}
.sub,.note{color:var(--muted);font-size:13px;margin:.2em 0 14px}
.note{margin:.3em 0 10px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 10px}
h3 b{color:var(--ink);font-size:15px;margin-left:6px}
.cols3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.cols3 .verify h3 b{color:var(--review)}
/* chips */
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;padding:3px 8px;border-radius:20px;color:#fff;background:var(--c,#9aa0a6);white-space:nowrap}
/* table */
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--rule)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.pill{font-size:11px;padding:2px 8px;border-radius:20px}
.pill.review{background:#fbe9e4;color:var(--review)}
.quality{margin:6px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}
.mt{margin-top:18px}
/* graph */
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin:4px 0 12px}
.legend span::before{content:"";display:inline-block;width:11px;height:11px;border-radius:50%;
background:var(--c);margin-right:6px;vertical-align:-1px}
.graph{width:100%;border:1px solid var(--rule);border-radius:8px}
.hint{font-size:11.5px;color:var(--muted);margin-top:8px;text-align:center}
.nd text{pointer-events:none;user-select:none}
/* failure explorer */
#pick{font:inherit;padding:7px 10px;border:1px solid var(--rule);border-radius:8px;min-width:220px}
#fxreset{font:inherit;margin-left:8px;padding:7px 12px;border:1px solid var(--rule);
background:#fff;border-radius:8px;cursor:pointer}
.fx{margin-top:16px;border-top:1px solid var(--rule);padding-top:16px}
.fxhead{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.fx-cat{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.brief-badge{margin-left:auto;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
color:var(--muted);border:1px solid var(--rule);border-radius:20px;padding:2px 10px}
.brief{background:#f4f6f8;border:1px solid var(--rule);border-left:3px solid var(--blue);
border-radius:8px;padding:14px 16px;margin:0 0 16px;font-size:12.5px;line-height:1.55;
white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#25313f}
.fxgrid{display:grid;grid-template-columns:1fr 1.3fr 1.3fr;gap:20px}
.fxlab{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin:8px 0 5px}
.modes{margin:0;padding-left:18px;font-size:13px}
.fx-cons h3{color:var(--review)}.fx-cause h3{color:var(--blue)}
.legend .hl-sel::before{background:var(--ink)}
.legend .hl-down::before{background:var(--review)}
.legend .hl-up::before{background:var(--blue)}
footer{max-width:1100px;margin:0 auto;padding:20px;color:var(--muted);font-size:12px;text-align:center}
@media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)}.cols3,.two{grid-template-columns:1fr}}
"""


if __name__ == "__main__":
    system = sys.argv[1] if len(sys.argv) > 1 else "27"
    out = build_dashboard(system)
    print(f"Dashboard written to {out}\nOpen it in a browser (double-click).")