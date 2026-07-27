#!/usr/bin/env python3
"""
line_labels.py — Tekstsporet, gjenåpnet ETTER klassifiseringen:
leser linjekodene fra PDF-ens tekstlag (som bildesporet med vilje maskerer
bort), tolker dem til strukturerte attributter, og knytter hvert
symbolfunn til nærmeste linjekode.

En Huldra-linjekode som   10"-PV-274506-ED200-8   betyr:
    10"      dimensjon (nominell diameter, tommer)
    PV       væske-/servicekode
    274506   linjenummer — de to første sifrene er SYSTEMET (27)
    ED200    rørklasse (piping class / spec)
    8        suffiks (isolasjon/trace-kode)

FLUID_CODES under er en STARTTABELL utledet av tegningskonteksten —
fullfør den mot linjenummerstandarden når den er tilgjengelig; ukjente
koder rapporteres som "ukjent kode" i stedet for å gjettes.

Bruk:
  py line_labels.py tegning.pdf --dpi 200
  py line_labels.py tegning.pdf --dpi 200 --detections results/<stem>_detections.json
Ut:
  results/<stem>_lines.json   (alle linjekoder + kobling til funn)
"""
import argparse, json, os, re, sys
from pathlib import Path

# Startverdier — utvid mot prosjektets linjenummerstandard
FLUID_CODES = {
    "WF": "brannvann (fire water)",
    "DC": "drenering, lukket (drain closed) (antatt)",
    "PV": "prosess/vent (antatt)",
    "VF": "vent til fakkel (antatt)",
    "PL": "prosessvæske (antatt)",
    "AS": "instrumentluft/air supply (antatt)",
}

LINE_RE = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)"'
    r'\s*[-x]\s*(?P<fluid>[A-Z]{1,3})'
    r'\s*-\s*(?P<lineno>\d{4,6})'
    r'\s*-\s*(?P<spec>[A-Z]{1,2}\d{3,4})'
    r'(?:\s*-\s*(?P<suffix>\w{1,3}))?')
SIZE_RE = re.compile(r'^(?P<a>\d+(?:\.\d+)?)"(?:x(?P<b>\d+(?:\.\d+)?)")?$')


def decode(m: re.Match) -> dict:
    lineno = m.group("lineno")
    fluid = m.group("fluid")
    return {
        "raw": m.group(0),
        "size_in": float(m.group("size")),
        "fluid": fluid,
        "fluid_desc": FLUID_CODES.get(fluid, "ukjent kode"),
        "line_no": lineno,
        "system": lineno[:2] if len(lineno) >= 5 else None,
        "spec": m.group("spec"),
        "suffix": m.group("suffix") or "",
    }


def extract_line_labels(pdf_path: str, dpi: int):
    """(linjekoder, størrelsesmerker) med posisjon i piksler ved gitt dpi."""
    import pdfplumber
    s = dpi / 72.0
    labels, sizes = [], []
    with pdfplumber.open(pdf_path) as pdf:
        words = pdf.pages[0].extract_words()
    # slå sammen naboord der koden er delt over flere ord ("10\"-PV-" + "274506-...")
    joined = []
    i = 0
    while i < len(words):
        w = dict(words[i])
        while (i + 1 < len(words)
               and w["text"].endswith("-")
               and abs(words[i + 1]["top"] - w["top"]) < 2
               and 0 <= words[i + 1]["x0"] - w["x1"] < 8):
            nxt = words[i + 1]
            w["text"] += nxt["text"]
            w["x1"] = nxt["x1"]
            i += 1
        joined.append(w)
        i += 1
    for w in joined:
        cx = (w["x0"] + w["x1"]) / 2 * s
        cy = (w["top"] + w["bottom"]) / 2 * s
        m = LINE_RE.search(w["text"])
        if m:
            d = decode(m)
            d.update({"cx": cx, "cy": cy})
            labels.append(d)
            continue
        m2 = SIZE_RE.match(w["text"])
        if m2:
            sizes.append({"raw": w["text"], "size_in": float(m2.group("a")),
                          "size2_in": float(m2.group("b")) if m2.group("b") else None,
                          "cx": cx, "cy": cy})
    return labels, sizes


def attach_to_detections(labels, sizes, detections, max_dist_px=800):
    """Knytt hvert funn til nærmeste linjekode (og nærmeste størrelsesmerke)."""
    out = []
    for d in detections:
        x0, y0, x1, y1 = d["bbox_orig"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        def nearest(items):
            best, bd = None, None
            for it in items:
                dist = ((it["cx"] - cx) ** 2 + (it["cy"] - cy) ** 2) ** 0.5
                if dist <= max_dist_px and (bd is None or dist < bd):
                    best, bd = it, dist
            return best, bd

        lab, ld = nearest(labels)
        sz, sd = nearest(sizes)
        row = {**d, "line": lab,
               "line_dist_px": round(ld) if ld is not None else None,
               "size_marker": sz,
               "size_dist_px": round(sd) if sd is not None else None}
        out.append(row)
    return out


def broker_hint(row) -> str:
    """Menneskelesbar Model Broker-konfigurasjon for ett funn."""
    lab = row.get("line")
    parts = []
    if lab:
        if lab.get("system"):
            parts.append(f"System {lab['system']}")
        parts.append(f'DN {lab["size_in"]:g}"')
        parts.append(f"fluid {lab['fluid']} ({lab['fluid_desc']})")
        parts.append(f"rørklasse {lab['spec']}")
        if lab.get("suffix"):
            parts.append(f"suffiks {lab['suffix']}")
    elif row.get("size_marker"):
        sm = row["size_marker"]
        parts.append(f'DN {sm["size_in"]:g}"'
                     + (f' → {sm["size2_in"]:g}"' if sm.get("size2_in") else ""))
    return " · ".join(parts) if parts else "ingen linjekode i nærheten"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--detections", default=None,
                    help="results/<stem>_detections.json for kobling til funn")
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    labels, sizes = extract_line_labels(args.drawing, args.dpi)
    print(f"[+] {len(labels)} linjekoder og {len(sizes)} størrelsesmerker "
          f"i tekstlaget")
    for lab in labels[:8]:
        print(f'    {lab["raw"]:<28} -> system {lab["system"]}, '
              f'DN {lab["size_in"]:g}", {lab["fluid"]} ({lab["fluid_desc"]}), '
              f'klasse {lab["spec"]}')
    if len(labels) > 8:
        print(f"    ... og {len(labels)-8} til")

    attached = []
    if args.detections and os.path.exists(args.detections):
        dets = json.load(open(args.detections, encoding="utf-8"))
        attached = attach_to_detections(labels, sizes, dets)
        print(f"\n[+] koblet {sum(1 for a in attached if a['line'])} av "
              f"{len(attached)} funn til en linjekode")

    stem = Path(args.drawing).stem
    os.makedirs(args.out_dir, exist_ok=True)
    out = Path(args.out_dir) / f"{stem}_lines.json"
    json.dump({"labels": labels, "sizes": sizes, "attached": attached},
              open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[✓] -> {out}")


if __name__ == "__main__":
    main()