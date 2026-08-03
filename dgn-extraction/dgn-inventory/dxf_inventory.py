#!/usr/bin/env python3
"""
dxf_inventory.py — Lager komponentoversikt direkte fra en DXF-fil
(typisk konvertert fra DGN med ODA File Converter eller MicroStation-eksport).

Ideen: i DGN/DXF er hvert symbol en NAVNGITT blokk (celle). En INSERT-entitet
er én plassering av blokken. Å liste komponentene = å liste INSERT-ene.
Ingen bildeanalyse, ingen gjetting — navnet står i filen.

Ingen avhengigheter utover standard Python (egen liten DXF-parser, ASCII-DXF).

Ut:
  <navn>_inventory.csv    blokknavn, DEXPI-klasse, tag, rotasjon, posisjon
  <navn>_inventory.html   rapport: sammendrag pr. symbol + detaljtabell
  (konsoll)               sammendrag + liste over blokknavn uten DEXPI-mapping

Bruk:
  python dxf_inventory.py tegning.dxf [--mapping dexpi_mapping.json]
"""
import argparse, csv, html, json, os, re, sys
from collections import Counter

TAG_RE = re.compile(r"^\d{2}-(?:[A-Z]{1,4}[- ]?\d{2,5}[A-Z]{0,2}|\d{2,5}[A-Z]{1,3})$")  # 27-4542PV, 24-AE2060, 27-KA50

# ---------------------------------------------------------------- DXF-lesing
def read_pairs(path):
    """DXF er (gruppekode, verdi)-par på annenhver linje."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            lines = open(path, encoding=enc).read().splitlines()
            break
        except UnicodeDecodeError:
            continue
    if lines and lines[0].strip() == "AutoCAD Binary DXF":
        sys.exit("Dette er binær DXF. Eksporter som ASCII DXF (velg 'ASCII' i "
                 "ODA File Converter), så leser skriptet den.")
    it = iter(lines)
    for code in it:
        val = next(it, "")
        try:
            yield int(code.strip()), val
        except ValueError:
            continue

def parse(path):
    """Returnerer (inserts, texts). Kun ENTITIES-seksjonen (= plasseringer);
    BLOCKS-seksjonen er definisjoner og hoppes over — samme skille som
    ShapeCatalogue vs. instanser i DEXPI-XML."""
    inserts, texts = [], []
    section = None
    ent = None            # pågående entitet {type, data{code:[values]}}
    pending_attribs = None  # INSERT som venter på ATTRIB-er

    def flush(e):
        nonlocal pending_attribs
        if e is None or section != "ENTITIES":
            return
        t = e["type"]; d = e["data"]
        g = lambda c, default="": d.get(c, [default])[0]
        if t == "INSERT":
            ins = {"name": g(2).upper(), "x": float(g(10, "0")), "y": float(g(20, "0")),
                   "rot": float(g(50, "0")), "attribs": {}, "tag": ""}
            inserts.append(ins)
            pending_attribs = ins if g(66, "0").strip() == "1" else None
        elif t == "ATTRIB" and pending_attribs is not None:
            pending_attribs["attribs"][g(2)] = g(1)
        elif t == "SEQEND":
            pending_attribs = None
        elif t in ("TEXT", "MTEXT"):
            s = "".join(d.get(3, [])) + g(1)
            s = re.sub(r"\\[A-Za-z][^;]*;|[{}]", "", s)   # strip MTEXT-formatkoder
            if s.strip():
                texts.append({"text": s.strip(), "x": float(g(10, "0")),
                              "y": float(g(20, "0"))})

    for code, val in read_pairs(path):
        if code == 0:
            flush(ent)
            v = val.strip().upper()
            if v == "SECTION":
                ent = {"type": "SECTION", "data": {}}
            elif v == "ENDSEC":
                section, ent = None, None
            else:
                ent = {"type": v, "data": {}}
        elif ent is not None:
            if ent["type"] == "SECTION" and code == 2:
                section = val.strip().upper(); ent = None
            else:
                ent["data"].setdefault(code, []).append(val.strip())
    flush(ent)
    return inserts, texts

# ------------------------------------------------------------- berikelse
def associate_tags(inserts, texts):
    """Nærmeste tekst som ser ut som en tag; ATTRIB-verdier vinner om de finnes."""
    tags = [t for t in texts if TAG_RE.fullmatch(t["text"])]
    for ins in inserts:
        for v in ins["attribs"].values():
            if TAG_RE.fullmatch(v.strip()):
                ins["tag"] = v.strip(); break
        if ins["tag"] or not tags:
            continue
        best = min(tags, key=lambda t: (t["x"]-ins["x"])**2 + (t["y"]-ins["y"])**2)
        dist = ((best["x"]-ins["x"])**2 + (best["y"]-ins["y"])**2) ** 0.5
        if dist < 25:                     # mm på arket — juster ved behov
            ins["tag"] = best["text"]

def load_mapping(path):
    if not path or not os.path.exists(path):
        return {}
    m = json.load(open(path, encoding="utf-8"))
    return {k.upper(): v for k, v in m.items() if not k.startswith("_")}

# ---------------------------------------------------------------- rapport
HTML_HEAD = """<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Komponentoversikt — {title}</title><style>
:root {{ --ink:#1a1d21; --line:#8a8f98; --accent:#0b5cad; --paper:#fdfdfb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:14px/1.5 "Segoe UI",system-ui,sans-serif; }}
.sheet {{ max-width:1100px; margin:24px auto; border:2px solid var(--ink); }}
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
.warn {{ background:#fff6e5; }}
footer {{ padding:10px 20px; border-top:2px solid var(--ink);
  font:11px/1 monospace; color:var(--line); }}
</style></head><body><div class="sheet">
<div class="tblock">
  <div class="title"><div class="k">Komponentoversikt (DXF)</div><div class="v">{title}</div></div>
  <div><div class="k">Symbolinstanser</div><div class="v">{n}</div></div>
  <div style="border-right:none"><div class="k">Unike symboler</div><div class="v">{nc}</div></div>
</div>"""

def write_html(path, title, rows, summary, mapping):
    with open(path, "w", encoding="utf-8") as f:
        f.write(HTML_HEAD.format(title=html.escape(title), n=len(rows), nc=len(summary)))
        f.write('<section><h2>Sammendrag pr. symbol</h2><table>'
                '<tr><th>Blokknavn (celle)</th><th>DEXPI-klasse</th>'
                '<th>Beskrivelse</th><th class="count">Antall</th></tr>')
        for name, n in summary:
            m = mapping.get(name, {})
            cls = m.get("class", "")
            f.write(f'<tr{" class=warn" if not cls else ""}>'
                    f'<td>{html.escape(name)}</td>'
                    f'<td{"" if cls else " class=muted"}>{html.escape(cls or "ikke mappet")}</td>'
                    f'<td class="muted">{html.escape(m.get("desc",""))}</td>'
                    f'<td class="count">{n}</td></tr>')
        f.write('</table></section>')
        f.write('<section><h2>Alle instanser</h2><table>'
                '<tr><th>Symbol</th><th>DEXPI-klasse</th><th>Tag</th>'
                '<th>Rot</th><th>X</th><th>Y</th></tr>')
        for r in sorted(rows, key=lambda r: (r["name"], r["tag"])):
            f.write("<tr>" + "".join(
                f'<td{" class=muted" if not str(r[k]) else ""}>{html.escape(str(r[k]) or "—")}</td>'
                for k in ("name", "class", "tag", "rot", "x", "y")) + "</tr>")
        f.write('</table></section>')
        f.write(f'<footer>Generert av dxf_inventory.py · kilde: {html.escape(title)}</footer>')
        f.write('</div></body></html>')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--mapping", default="dexpi_mapping.json")
    args = ap.parse_args()

    inserts, texts = parse(args.dxf)
    associate_tags(inserts, texts)
    mapping = load_mapping(args.mapping)

    rows = []
    for ins in inserts:
        m = mapping.get(ins["name"], {})
        rows.append({"name": ins["name"], "class": m.get("class", ""),
                     "tag": ins["tag"], "rot": f'{ins["rot"]:g}',
                     "x": f'{ins["x"]:.1f}', "y": f'{ins["y"]:.1f}',
                     "attribs": "; ".join(f"{k}={v}" for k, v in ins["attribs"].items())})

    summary = Counter(r["name"] for r in rows).most_common()
    stem = os.path.splitext(os.path.basename(args.dxf))[0]

    print(f"\n=== {stem}: {len(rows)} symbolinstanser, {len(summary)} unike symboler ===")
    for name, n in summary:
        cls = mapping.get(name, {}).get("class", "")
        print(f"  {n:4d}  {name:<20} {cls or '(ikke mappet)'}")
    unmapped = [n for n, _ in summary if n not in mapping]
    if unmapped:
        print(f"\n  {len(unmapped)} blokknavn mangler i {args.mapping} — "
              f"legg dem til der for å få DEXPI-klasse:")
        print("  " + ", ".join(unmapped[:20]) + (" ..." if len(unmapped) > 20 else ""))

    with open(f"{stem}_inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name","class","tag","rot","x","y","attribs"])
        w.writeheader(); w.writerows(rows)
    write_html(f"{stem}_inventory.html", stem, rows, summary, mapping)
    print(f"  -> {stem}_inventory.csv / .html")

if __name__ == "__main__":
    main()
