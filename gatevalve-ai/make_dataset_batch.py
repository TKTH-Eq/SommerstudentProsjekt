#!/usr/bin/env python3
"""
make_dataset_batch.py — Kjører make_dataset.py for ALLE XML+tegning-par den
finner: skanner en mappe for *_DGN.xml / *.xml, finner tilhørende PDF (eller
JPG/PNG) ved navne-matching (ignorerer bindestreker/understreker, så
'C025-V-HO27-P-_E-001-01_DGN.xml' matcher både 'C025-V-HO27-P-_E-001-01.PDF'
og 'C025VHO27P_E00101.PDF'), og bygger ett samlet datasett.

Bruk:
  python make_dataset_batch.py --xml-dir data\\xml --drawings-dir data\\raw --dpi 200
"""
import argparse, glob, os, re, subprocess, sys
from collections import Counter

def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml-dir", required=True)
    ap.add_argument("--drawings-dir", required=True)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--out", default="dataset")
    args = ap.parse_args()

    xmls = sorted(glob.glob(os.path.join(args.xml_dir, "**", "*.xml"), recursive=True))
    if not xmls:
        sys.exit(f"fant ingen .xml i {args.xml_dir}")

    drawings = {}
    for ext in ("pdf", "jpg", "jpeg", "png"):
        for fp in glob.glob(os.path.join(args.drawings_dir, "**", f"*.{ext}"), recursive=True) + \
                  glob.glob(os.path.join(args.drawings_dir, "**", f"*.{ext.upper()}"), recursive=True):
            drawings.setdefault(norm(os.path.splitext(os.path.basename(fp))[0]), fp)

    here = os.path.dirname(os.path.abspath(__file__))
    ok, miss = 0, []
    for xml in xmls:
        stem = os.path.splitext(os.path.basename(xml))[0]
        key = norm(re.sub(r"_?DGN$", "", stem, flags=re.I))
        hit = drawings.get(key)
        if not hit:   # prøv prefiks-match (revisjonssuffiks o.l.)
            hit = next((fp for k, fp in drawings.items()
                        if k.startswith(key) or key.startswith(k)), None)
        if not hit:
            miss.append(stem); continue
        print(f"[+] {stem}  <->  {os.path.basename(hit)}")
        r = subprocess.run([sys.executable, os.path.join(here, "make_dataset.py"),
                            xml, hit, "--dpi", str(args.dpi), "--out", args.out])
        ok += (r.returncode == 0)

    print(f"\n[✓] {ok}/{len(xmls)} tegninger prosessert")
    if miss:
        print(f"[!] fant ikke tegning for: {', '.join(miss[:8])}"
              + (" ..." if len(miss) > 8 else ""))

    # totaloversikt
    counts = Counter()
    for d in glob.glob(os.path.join(args.out, "*")):
        if os.path.isdir(d) and os.path.basename(d) != "yolo":
            counts[os.path.basename(d)] = len(glob.glob(os.path.join(d, "*.png")))
    if counts:
        print("\nDatasett totalt:")
        for c, n in counts.most_common():
            print(f"  {n:4d}  {c}")

if __name__ == "__main__":
    main()
