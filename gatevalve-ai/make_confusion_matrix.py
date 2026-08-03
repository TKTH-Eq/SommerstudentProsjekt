#!/usr/bin/env python3
"""
make_confusion_matrix.py — Deteksjonsnivå-forvekslingsmatrise fra ALLEREDE
PRODUSERTE resultater: leser results/<stem>_detections.json (fra
make_report/classify_drawing) og krysser mot fasiten i dataset/labels.csv.
Kjører på sekunder — ingen klassifisering, ingen modell.

Matching er KLASSE-AGNOSTISK (hvert fasitpunkt mot nærmeste ledige funn
uansett klasse), i motsetning til make_report som matcher innen klasse.
Dermed skilles tre feil P/R-tabellen klumper sammen:
  * diagonalen        = riktig funnet
  * «ikke funnet»     = aldri detektert (forslags-/datamangel)
  * feil kolonne      = detektert, men forvekslet med annen klasse
  * «(ingen fasit)»   = rene feiltreff per predikert klasse
    (NB: kan også være ekte komponenter som mangler i DEXPI-fasiten)

Bruk (fra gatevalve-ai-mappen, ETTER en make_report/classify-kjøring):
  py make_confusion_matrix.py
  py make_confusion_matrix.py --tier alle          (sikre + mulige)
  py make_confusion_matrix.py --results-dir results --out results/confusion.csv
"""
import argparse
import csv
import glob
import json
import os
import re
from collections import defaultdict

GT2CLS = {"GateValve": "gate", "BallValve": "ball",
          "GlobeValve": "globe_valve", "CheckValve": "check_valve",
          "ButterflyValve": "butterfly_valve", "PipeReducer": "reducer",
          "NeedleValve": "other_valve", "PlugValve": "other_valve",
          "AngleValve": "other_valve"}


def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def det_bucket(cls):
    if cls in ("gate_open", "gate_closed"):
        return "gate"
    if cls in ("ball_open", "ball_closed", "ball_valve"):
        return "ball"
    return cls


def find_source_key(stem, gt):
    nk = norm(stem)
    exact = [k for k in gt if nk.endswith(k) or k.endswith(nk)]
    if exact:
        return max(exact, key=len)
    tail = nk[-14:]
    part = [k for k in gt if k in nk or tail in k]
    return max(part, key=len) if part else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="dataset/labels.csv")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--radius", type=float, default=1.5,
                    help="som i make_report: radius * boksstørrelse")
    ap.add_argument("--tier", choices=["sikre", "alle"], default="sikre")
    ap.add_argument("--only", default="",
                    help="begrens til disse tegningene (komma, norm-stems)")
    ap.add_argument("--out", default=None,
                    help="CSV-utfil (standard: <results-dir>/confusion.csv)")
    args = ap.parse_args()

    gt = {}
    for r in csv.DictReader(open(args.labels, encoding="utf-8")):
        gt.setdefault(norm(r["source"]), {}).setdefault(r["class"], []).append(
            (float(r["cx_px"]), float(r["cy_px"])))
    only = {norm(s) for s in args.only.split(",") if s.strip()}

    det_files = sorted(glob.glob(os.path.join(args.results_dir,
                                              "*_detections.json")))
    if not det_files:
        raise SystemExit(f"ingen *_detections.json i {args.results_dir} — "
                         f"kjør make_report eller classify_drawing først")

    confusion = defaultdict(int)
    n_drawings = 0
    for dp in det_files:
        stem = os.path.basename(dp)[:-len("_detections.json")]
        key = find_source_key(stem, gt)
        if key is None or (only and key not in only):
            continue
        n_drawings += 1
        dets = json.load(open(dp, encoding="utf-8"))
        if args.tier == "sikre":
            dets = [d for d in dets if d.get("tier", "sikker") == "sikker"]

        used = set()
        for gname, gpts in gt[key].items():
            gcls = GT2CLS.get(gname)
            if gcls is None:
                continue
            for gx, gy in gpts:
                best, bi = None, None
                for i, d in enumerate(dets):
                    if i in used:
                        continue
                    x0, y0, x1, y1 = d["bbox_orig"]
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                    R = args.radius * max(x1 - x0, y1 - y0)
                    dist2 = (gx - cx) ** 2 + (gy - cy) ** 2
                    if dist2 <= R * R and (best is None or dist2 < best):
                        best, bi = dist2, i
                if bi is None:
                    confusion[(gcls, "ikke funnet")] += 1
                else:
                    used.add(bi)
                    confusion[(gcls, det_bucket(dets[bi]["cls"]))] += 1
        for i, d in enumerate(dets):
            if i not in used:
                confusion[("(ingen fasit)", det_bucket(d["cls"]))] += 1

    if not confusion:
        raise SystemExit("ingen tegninger med både detections og fasit")

    row_names = sorted({r for r, _ in confusion} - {"(ingen fasit)"}) + ["(ingen fasit)"]
    col_names = sorted({c for _, c in confusion} - {"ikke funnet"}) + ["ikke funnet"]
    w0 = max(len(r) for r in row_names) + 2
    print(f"[+] {n_drawings} tegninger, lag: {args.tier}")
    print("FORVEKSLING på deteksjonsnivå (rader=fasit, kolonner=predikert):")
    print(" " * w0 + "  ".join(f"{c[:9]:>9}" for c in col_names))
    for r in row_names:
        print(f"{r:<{w0}}"
              + "  ".join(f"{confusion.get((r, c), 0):>9}" for c in col_names))

    out = args.out or os.path.join(args.results_dir, "confusion.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fasit\\predikert"] + col_names)
        for r in row_names:
            w.writerow([r] + [confusion.get((r, c), 0) for c in col_names])
    print(f"\n[✓] -> {out}")
    print("    NB: «(ingen fasit)» kan inneholde ekte komponenter som mangler "
          "i DEXPI-en — sjekk mot proof-bildene før de dømmes som feiltreff.")


if __name__ == "__main__":
    main()