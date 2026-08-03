#!/usr/bin/env python3
"""
dgn7_inventory.py — Leser DGN V7 (ISFF) DIREKTE, uten konvertering.
Lister cellenavn (= symbolkoder), posisjoner og tekster (tags).

Virkemåte:
  * V7-elementstrøm: 4-byte header (level/type + "words to follow") — veldokumentert.
  * Cellenavn lagres RAD50-kodet (6 tegn maks — derfor heter symbolene VAL001!).
    Nøyaktig byte-offset varierer i praksis, så skriptet SELVKALIBRERER:
    prøver kjente offsets og velger den som gir flest gyldige navn i hele filen.
  * Posisjon hentes fra elementets range-blokk (bytes 4–27) — alltid samme sted.
  * Tekster (type 17) høstes som lengste ASCII-sekvens i elementet.

Begrensninger (ærlige):
  * KUN DGN V7. V8-filer (OLE-container, starter med D0 CF 11 E0) kan ikke
    leses i ren Python — skriptet oppdager det og sier fra. Bruk da ODA-konvertering.
  * Posisjoner rapporteres i UOR (tegningens interne enheter); relative
    posisjoner stemmer, absolutt skala krever --uor-scale (UOR pr. mm).
  * Første kjøring på ekte fil er kalibreringstesten — kjør gjerne med
    --debug 3 og send utskriften tilbake hvis navnene ser rare ut.

Bruk:
  python dgn7_inventory.py tegning.dgn [--mapping dexpi_mapping.json] [--debug 3]
"""
import argparse, csv, html, json, os, re, struct, sys
from collections import Counter

RAD50 = " ABCDEFGHIJKLMNOPQRSTUVWXYZ$.%0123456789"
TAG_RE = re.compile(r"^\d{2}-(?:[A-Z]{1,4}[- ]?\d{2,5}[A-Z]{0,2}|\d{2,5}[A-Z]{1,3})$")
NAME_OK = re.compile(r"^[A-Z0-9][A-Z0-9$.% ]{0,5}$")

CELL_TYPES = {2: "CellHeader", 34: "SharedCellDef", 35: "SharedCellInst"}
# Navn ligger på offset 38 (verifisert mot ekte fil). 36 er totlength og kan
# TILFELDIGVIS dekode som gyldig RAD50 — derfor er 36 bevisst utelatt her.
NAME_OFFSETS = [38, 40, 42, 44]

def rad50(word):
    if word >= 40**3: return None
    a, r = divmod(word, 40*40)
    b, c = divmod(r, 40)
    return RAD50[a] + RAD50[b] + RAD50[c]

def decode_name(buf, off):
    if off + 4 > len(buf): return None
    w1, w2 = struct.unpack_from("<HH", buf, off)
    p1, p2 = rad50(w1), rad50(w2)
    if p1 is None or p2 is None: return None
    name = (p1 + p2).strip()
    return name if name and NAME_OK.fullmatch(name) else None

def walk_elements(data):
    pos = 0
    while pos + 4 <= len(data):
        b0, b1 = data[pos], data[pos+1]
        wtf = struct.unpack_from("<H", data, pos+2)[0]
        if wtf == 0xFFFF:                     # end-of-design
            return
        size = wtf*2 + 4
        if size < 4 or pos + size > len(data):
            return
        yield {"type": b1 & 0x7f, "level": b0 & 0x3f,
               "deleted": bool(b1 & 0x80), "complex": bool(b0 & 0x80),
               "raw": data[pos:pos+size], "pos": pos}
        pos += size

def i32(raw, off):
    """V7 lagrer int32 som to LE-ord med MEST signifikante ord først."""
    hi, lo = struct.unpack_from("<HH", raw, off)
    return ((hi << 16) | lo) - 2**31

def range_center(raw):
    """Bytes 4–27: xlo ylo zlo xhi yhi zhi (word-swapped int32, 2^31-bias, UOR).
    Verifisert mot ekte V7-fil (Huldra-arkivet)."""
    if len(raw) < 28: return None, None
    return (i32(raw, 4) + i32(raw, 16)) / 2, (i32(raw, 8) + i32(raw, 20)) / 2

def longest_ascii(raw, minlen=2):
    best, cur = b"", b""
    for byte in raw[36:]:                     # hopp over header+range
        if 32 <= byte < 127:
            cur += bytes([byte])
        else:
            if len(cur) > len(best): best = cur
            cur = b""
    if len(cur) > len(best): best = cur
    s = best.decode("ascii", "ignore").strip()
    return s if len(s) >= minlen else ""

def calibrate(cells):
    """Offset 38 er verifisert mot ekte V7-fil. Kalibrering brukes kun som
    nødfall hvis 38 forklarer under 30 % av cellene (navn eller blank)."""
    chosen = {}
    for t in set(c["type"] for c in cells):
        sample = [c for c in cells if c["type"] == t]
        def explained(off):
            n = 0
            for c in sample:
                if decode_name(c["raw"], off) or c["raw"][off:off+4] == b"\x00\x00\x00\x00":
                    n += 1
            return n / max(len(sample), 1)
        if explained(38) >= 0.30:
            chosen[t] = 38
            continue
        scores = []
        for off in NAME_OFFSETS[1:]:
            names = [decode_name(c["raw"], off) for c in sample]
            score = sum(len(n) for n in names if n)
            scores.append((score, -off))
        best_score, neg_off = max(scores)
        chosen[t] = -neg_off if best_score > 0 else None
    return chosen

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dgn")
    ap.add_argument("--mapping", default="dexpi_mapping.json")
    ap.add_argument("--uor-scale", type=float, default=None,
                    help="UOR pr. mm — deler posisjoner for å få mm")
    ap.add_argument("--debug", type=int, default=0,
                    help="hexdump av de N første celle-elementene")
    args = ap.parse_args()

    data = open(args.dgn, "rb").read()
    if data[:4] == b"\xd0\xcf\x11\xe0":
        sys.exit("Dette er DGN V8 (OLE-container). V8 kan ikke leses i ren Python "
                 "— konverter til DXF med gratis ODA File Converter og bruk "
                 "dxf_inventory.py i stedet. (V7-filer leses direkte.)")

    elements = list(walk_elements(data))
    if not elements:
        sys.exit("Fant ingen gyldig V7-elementstrøm — er dette en DGN-fil?")

    type_counts = Counter(e["type"] for e in elements if not e["deleted"])
    cells = [e for e in elements if e["type"] in CELL_TYPES and not e["deleted"]]
    texts = [e for e in elements if e["type"] in (17,) and not e["deleted"]]

    if args.debug:
        for c in cells[:args.debug]:
            print(f"--- {CELL_TYPES[c['type']]} @byte {c['pos']}, {len(c['raw'])}B:")
            hx = c["raw"][:72].hex()
            print("   " + " ".join(hx[i:i+4] for i in range(0, len(hx), 4)))

    offsets = calibrate(cells)
    scale = args.uor_scale or 1.0

    rows, unresolved = [], 0
    for c in cells:
        off = offsets.get(c["type"])
        name = decode_name(c["raw"], off) if off else None
        if not name:
            # tomt navnefelt = ekte navnløs celle (lovlig i MicroStation)
            if off and c["raw"][off:off+4] in (b"\x00\x00\x00\x00",):
                name = "(uten navn)"
            else:
                unresolved += 1; continue
        x, y = range_center(c["raw"])
        rows.append({"name": name, "kind": CELL_TYPES[c["type"]],
                     "x": f"{x/scale:.1f}" if x is not None else "",
                     "y": f"{y/scale:.1f}" if y is not None else ""})

    tag_texts = []
    for t in texts:
        s = longest_ascii(t["raw"])
        if s and TAG_RE.fullmatch(s):
            x, y = range_center(t["raw"])
            tag_texts.append({"text": s, "x": x, "y": y})

    # nærmeste tag-tekst pr. celle (i UOR; radius = 5 % av tegningsbredden)
    if tag_texts and rows:
        xs = [float(r["x"]) for r in rows if r["x"]]
        radius = (max(xs) - min(xs)) * 0.05 if len(xs) > 1 else float("inf")
        for r in rows:
            if not r["x"]: r["tag"] = ""; continue
            rx, ry = float(r["x"]), float(r["y"])
            best = min(tag_texts, key=lambda t: (t["x"]/scale-rx)**2 + (t["y"]/scale-ry)**2)
            d = ((best["x"]/scale-rx)**2 + (best["y"]/scale-ry)**2) ** 0.5
            r["tag"] = best["text"] if d < radius else ""
    else:
        for r in rows: r["tag"] = ""

    mapping = {}
    if os.path.exists(args.mapping):
        mapping = {k.upper(): v for k, v in json.load(open(args.mapping, encoding="utf-8")).items()
                   if not k.startswith("_")}
    for r in rows:
        r["class"] = mapping.get(r["name"], {}).get("class", "")

    stem = os.path.splitext(os.path.basename(args.dgn))[0]
    summary = Counter(r["name"] for r in rows).most_common()

    print(f"\n=== {stem} (DGN V7) ===")
    print(f"  {len(elements)} elementer totalt; typefordeling (topp 8): "
          + ", ".join(f"{t}:{n}" for t, n in type_counts.most_common(8)))
    print(f"  {len(cells)} celle-elementer, {len(rows)} med gyldig navn"
          + (f" ({unresolved} uleselige — kjør --debug og send meg utskriften)" if unresolved else ""))
    print(f"  navne-offset valgt pr. type: { {CELL_TYPES[k]: v for k, v in offsets.items()} }")
    print(f"  {len(tag_texts)} tag-tekster funnet blant {len(texts)} tekstelementer\n")
    for name, n in summary:
        cls = mapping.get(name, {}).get("class", "")
        print(f"  {n:4d}  {name:<8} {cls or '(ikke mappet)'}")

    with open(f"{stem}_inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "class", "kind", "tag", "x", "y"])
        w.writeheader(); w.writerows(rows)
    print(f"\n  -> {stem}_inventory.csv")

if __name__ == "__main__":
    main()
