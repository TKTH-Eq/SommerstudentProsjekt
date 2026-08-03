#!/usr/bin/env python3
"""
dgn_version_check.py — Skanner mapper og forteller hvilke DGN-filer som er
V7 (kan leses direkte med dgn7_inventory.py) og hvilke som er V8 (må via DXF).
Leter samtidig etter ferdig-konverterte .dxf-filer i samme område.

Skriver to filer du kan komme tilbake til:
  dgn_versions.txt   lesbar rapport med KOMPLETTE lister, gruppert pr. mappe
  dgn_versions.csv   flat liste for regneark/videre skripting

Bruk:
  python dgn_version_check.py C:\\Appl\\SommerstudentProsjekt\\data
"""
import os, sys, struct
from collections import Counter

def classify(path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "uleselig"
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "V8"
    if len(head) >= 4:
        t = head[1] & 0x7f
        wtf = struct.unpack_from("<H", head, 2)[0]
        if t in (8, 9) and 0 < wtf < 0x8000:
            return "V7"
    return "ukjent format"

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    stats, v7, v8, other, dxf = Counter(), [], [], [], []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            low = fn.lower()
            if low.endswith(".dxf"):
                dxf.append(p); continue
            if not low.endswith(".dgn"):
                continue
            kind = classify(p)
            stats[kind] += 1
            {"V7": v7, "V8": v8}.get(kind, other).append(p)

    print(f"\nSkannet: {root}")
    print(f"  V7 (leses direkte):        {stats['V7']}")
    print(f"  V8 (trenger konvertering): {stats['V8']}")
    if stats["ukjent format"] or stats["uleselig"]:
        print(f"  ukjent/uleselig:           {stats['ukjent format'] + stats['uleselig']}")
    print(f"  ferdige .dxf funnet:       {len(dxf)}")

    # ---- Fullstendig, lesbar rapport (dgn_versions.txt) ----
    from datetime import datetime
    with open("dgn_versions.txt", "w", encoding="utf-8") as f:
        f.write(f"DGN-VERSJONSRAPPORT\n")
        f.write(f"Skannet: {os.path.abspath(root)}\n")
        f.write(f"Dato:    {datetime.now():%Y-%m-%d %H:%M}\n\n")
        f.write(f"V7 (leses direkte med dgn7_inventory.py): {stats['V7']}\n")
        f.write(f"V8 (konverter til DXF forst):             {stats['V8']}\n")
        f.write(f"Ferdige .dxf funnet:                      {len(dxf)}\n")
        if other:
            f.write(f"Ukjent/uleselig:                          {len(other)}\n")

        def section(lst, title):
            if not lst:
                return
            f.write(f"\n{'='*70}\n{title} ({len(lst)} filer)\n{'='*70}\n")
            # grupper pr. mappe for lesbarhet
            bydir = {}
            for p in sorted(lst):
                bydir.setdefault(os.path.dirname(p), []).append(os.path.basename(p))
            for d in sorted(bydir):
                f.write(f"\n  {d}\n")
                for name in bydir[d]:
                    f.write(f"    {name}\n")

        section(v7,   "V7 — KAN KJORES DIREKTE I DAG")
        section(v8,   "V8 — TRENGER KONVERTERING (Bentley View -> DXF)")
        section(dxf,  "FERDIGE DXF-FILER (bruk dxf_inventory.py)")
        section(other,"UKJENT FORMAT / ULESELIG")

    # ---- Flat CSV for regneark/skripting ----
    with open("dgn_versions.csv", "w", encoding="utf-8") as f:
        f.write("versjon,filnavn,mappe,full_sti\n")
        for kind, lst in (("V7", v7), ("V8", v8), ("DXF", dxf), ("ukjent", other)):
            for p in sorted(lst):
                f.write(f"{kind},{os.path.basename(p)},{os.path.dirname(p)},{p}\n")

    print("\n  -> dgn_versions.txt (komplett, lesbar rapport)")
    print("  -> dgn_versions.csv (flat liste for regneark)")

if __name__ == "__main__":
    main()