#!/usr/bin/env python3
"""
list_components.py — Lager komponentoversikt fra en Model Broker DEXPI/Proteus-XML
(f.eks. C025-V-HO27-P-_E-001-01_DGN.xml).

Ingen avhengigheter utover standard Python.

Ut:
  <navn>_inventory.csv    flat liste: klasse, tag, linjenummer, dimensjon, posisjon
  <navn>_inventory.html   lesbar rapport med sammendrag + detaljtabell
  (konsoll)               sammendrag pr. komponentklasse

Bruk:
  python list_components.py C025-V-HO27-P-_E-001-01_DGN.xml
  python list_components.py *.xml            (flere filer -> én rapport pr. fil)
"""
import csv, glob, html, os, sys
import xml.etree.ElementTree as ET

# Elementtyper som regnes som "komponenter" i modellen
COMPONENT_TAGS = {
    "Equipment", "CustomEquipment", "PipingComponent", "CustomPipingComponent",
    "ProcessInstrumentationFunction", "InstrumentationLoopFunction",
    "ProcessSignalGeneratingFunction", "ActuatingFunction", "ActuatingSystem",
    "ControlledActuator", "OperatedValveReference", "ActuatingSystemComponent",
    "Nozzle", "PropertyBreak",
    "PipeOffPageConnector", "FlowInPipeOffPageConnector", "FlowOutPipeOffPageConnector",
    "FlowInSignalOffPageConnector", "FlowOutSignalOffPageConnector",
    "PipingNetworkSystem", "PipingNetworkSegment", "SignalLineFunction",
    "InformationFlow",
}

# GenericAttribute-navn som kan inneholde tag, i prioritert rekkefølge
TAG_ATTRS = ["TagNameAssignmentClass", "valveTag", "tagName",
             "PipingComponentNumberAssignmentClass",
             "ProcessInstrumentationFunctionsAssignmentClass",
             "ProcessInstrumentationFunctionNumberAssignmentClass",
             "SubTagNameAssignmentClass", "mountedOnTagName"]
LINE_ATTRS = ["LineNumberAssignmentClass", "PipelineTag"]
SIZE_ATTRS = ["NominalDiameterRepresentationAssignmentClass",
              "NominalDiameterNumericalValueRepresentationAssignmentClass"]
EXTRA_ATTRS = ["PipingClassCodeAssignmentClass", "FluidCodeAssignmentClass",
               "InstrumentType", "ProcessInstrumentationFunctionType", "SystemCode"]

def gattrs(el):
    """Alle GenericAttribute Name->Value direkte under dette elementet."""
    out = {}
    for gas in el.findall("./GenericAttributes"):
        for ga in gas.findall("./GenericAttribute"):
            n, v = ga.get("Name"), ga.get("Value")
            if n and v and n not in out:
                out[n] = v
    return out

def first(d, keys):
    for k in keys:
        if d.get(k): return d[k]
    return ""

def position(el):
    loc = el.find("./Position/Location")
    if loc is not None:
        return float(loc.get("X", 0)), float(loc.get("Y", 0))
    # fallback: senter av samlet Extent
    xs, ys = [], []
    for ext in el.iter("Extent"):
        mn, mx = ext.find("Min"), ext.find("Max")
        if mn is not None and mx is not None:
            xs += [float(mn.get("X", 0)), float(mx.get("X", 0))]
            ys += [float(mn.get("Y", 0)), float(mx.get("Y", 0))]
    if xs:
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return None, None

def walk(el, ctx, rows):
    """Rekursiv traversering; ctx bærer arvet linjenummer m.m. nedover."""
    tag = el.tag
    if tag in COMPONENT_TAGS:
        a = gattrs(el)
        line = first(a, LINE_ATTRS) or ctx.get("line", "")
        size = first(a, SIZE_ATTRS) or ctx.get("size", "")
        x, y = position(el)
        rows.append({
            "class": el.get("ComponentClass", tag),
            "tag": el.get("TagName") or first(a, TAG_ATTRS),
            "line": line,
            "size": size,
            "extra": "; ".join(f"{k}={a[k]}" for k in EXTRA_ATTRS if a.get(k)),
            "x": f"{x:.1f}" if x is not None else "",
            "y": f"{y:.1f}" if y is not None else "",
            "id": el.get("ID", ""),
        })
        # segment/system: send linjenr videre til barna
        if tag in ("PipingNetworkSystem", "PipingNetworkSegment"):
            ctx = dict(ctx)
            if line: ctx["line"] = line
            if size: ctx["size"] = size
    for child in el:
        if child.tag == "ShapeCatalogue":   # symboldefinisjoner, ikke instanser
            continue
        walk(child, ctx, rows)

def summarize(rows):
    from collections import Counter
    c = Counter(r["class"] for r in rows)
    return sorted(c.items(), key=lambda kv: -kv[1])

HTML_HEAD = """<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Komponentoversikt — {title}</title><style>
:root {{ --ink:#1a1d21; --line:#8a8f98; --accent:#0b5cad; --paper:#fdfdfb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:14px/1.5 "Segoe UI",system-ui,sans-serif; }}
.sheet {{ max-width:1100px; margin:24px auto; border:2px solid var(--ink); }}
/* Tittelfelt — som på en tegning */
.tblock {{ display:flex; border-bottom:2px solid var(--ink); }}
.tblock div {{ padding:10px 14px; border-right:1px solid var(--line); }}
.tblock .title {{ flex:1; }}
.tblock .k {{ font:11px/1 monospace; color:var(--line); text-transform:uppercase;
  letter-spacing:.08em; margin-bottom:4px; }}
.tblock .v {{ font:600 16px/1.2 "Consolas",monospace; }}
section {{ padding:16px 20px; }}
h2 {{ font:600 13px/1 monospace; text-transform:uppercase; letter-spacing:.1em;
  color:var(--accent); margin:0 0 10px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th {{ text-align:left; font:600 11px/1 monospace; text-transform:uppercase;
  letter-spacing:.06em; border-bottom:2px solid var(--ink); padding:6px 8px; }}
td {{ border-bottom:1px solid #e2e2dc; padding:5px 8px; font-family:Consolas,monospace; }}
tr:hover td {{ background:#eef3f8; }}
.count {{ text-align:right; }}
.muted {{ color:var(--line); }}
footer {{ padding:10px 20px; border-top:2px solid var(--ink);
  font:11px/1 monospace; color:var(--line); }}
</style></head><body><div class="sheet">
<div class="tblock">
  <div class="title"><div class="k">Komponentoversikt</div><div class="v">{title}</div></div>
  <div><div class="k">Komponenter</div><div class="v">{n}</div></div>
  <div style="border-right:none"><div class="k">Klasser</div><div class="v">{nc}</div></div>
</div>"""

def write_html(path, title, rows, summary):
    with open(path, "w", encoding="utf-8") as f:
        f.write(HTML_HEAD.format(title=html.escape(title), n=len(rows), nc=len(summary)))
        f.write('<section><h2>Sammendrag pr. klasse</h2><table>'
                '<tr><th>ComponentClass</th><th class="count">Antall</th></tr>')
        for cls, n in summary:
            f.write(f'<tr><td>{html.escape(cls)}</td><td class="count">{n}</td></tr>')
        f.write('</table></section>')
        f.write('<section><h2>Alle komponenter</h2><table>'
                '<tr><th>Klasse</th><th>Tag</th><th>Linje</th><th>Dim</th>'
                '<th>X</th><th>Y</th><th>Annet</th></tr>')
        for r in sorted(rows, key=lambda r: (r["class"], r["tag"])):
            f.write("<tr>" + "".join(
                f'<td{" class=muted" if not r[k] else ""}>{html.escape(r[k] or "—")}</td>'
                for k in ("class", "tag", "line", "size", "x", "y", "extra")) + "</tr>")
        f.write('</table></section>')
        f.write(f'<footer>Generert av list_components.py · kilde: {html.escape(title)}</footer>')
        f.write('</div></body></html>')

def process(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    rows = []
    walk(root, {}, rows)
    # MetaData-elementet er tegneramme, ikke komponent
    rows = [r for r in rows if r["class"] != "MetaData"]
    stem = os.path.splitext(os.path.basename(xml_path))[0]
    title = stem.replace("_DGN", "")

    summary = summarize(rows)
    print(f"\n=== {title}: {len(rows)} komponenter, {len(summary)} klasser ===")
    for cls, n in summary:
        print(f"  {n:4d}  {cls}")

    with open(f"{stem}_inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["class","tag","line","size","x","y","extra","id"])
        w.writeheader(); w.writerows(rows)
    write_html(f"{stem}_inventory.html", title, rows, summary)
    print(f"  -> {stem}_inventory.csv / .html")

if __name__ == "__main__":
    paths = []
    for arg in sys.argv[1:]:
        paths += glob.glob(arg)
    if not paths:
        sys.exit("bruk: python list_components.py <fil.xml> [flere.xml]")
    for p in paths:
        process(p)
