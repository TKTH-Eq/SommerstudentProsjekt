#!/usr/bin/env python3
"""
mine_hard_negatives.py — klasse-spesifikk hard-negative mining
for andretrinnsverifikatorene.

Viktig forskjell fra den gamle versjonen:
  * Vi trener IKKE gate-modellen på nytt.
  * Et ball-valve-feilfunn lagres som et negativt eksempel KUN for
    ball-verifikatoren, ikke som global "background".
  * Dermed kan en reducer, check valve eller gate valve brukes som
    "ikke ball valve" uten å ødelegge merkingen til den egentlige klassen.

Ut:
  dataset/HardNegativeByClass/ball_valve/*.png
  dataset/HardNegativeByClass/globe_valve/*.png
  dataset/HardNegativeByClass/check_valve/*.png
  dataset/HardNegativeByClass/butterfly_valve/*.png

Bruk:
  py mine_hard_negatives.py ^
      --drawings-dir "C:\\Appl\\SommerstudentProsjekt\\data\\raw" ^
      --model model_cnn.pt --dpi 200 ^
      --exclude "25VHO64PU00101,25VHO71PW00101,25WHO71PW00101"
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

import cv2
import numpy as np


def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


DET2GT = {
    "gate_open": "GateValve",
    "gate_closed": "GateValve",
    "ball_valve": "BallValve",      # bakoverkompatibelt med gammel modell
    "ball_open": "BallValve",
    "ball_closed": "BallValve",
    "globe_valve": "GlobeValve",
    "check_valve": "CheckValve",
    "butterfly_valve": "ButterflyValve",
    "reducer": "PipeReducer",
}

# feiltreff lagres i mappen til VERIFIKATOREN som skal trene på dem:
# begge ball-tilstandene mater den ene ball-verifikatoren
HN_BUCKET = {"ball_open": "ball_valve", "ball_closed": "ball_valve",
             "gate_open": "gate_valve", "gate_closed": "gate_valve"}

DEFAULT_CLASSES = ("ball_open,ball_closed,gate_open,gate_closed,"
                   "globe_valve,check_valve,butterfly_valve,reducer")


def find_source_key(stem, gt):
    nk = norm(stem)
    exactish = [k for k in gt if nk.endswith(k) or k.endswith(nk)]
    if exactish:
        return max(exactish, key=len)
    tail = nk[-14:]
    partial = [k for k in gt if k in nk or tail in k]
    return max(partial, key=len) if partial else None


def load_like_classifier(path, dpi):
    """Samme tekstmaskering og arkmaske som inferens, slik at utsnittene
    verifikatoren trener på ser ut som utsnittene den møter senere."""
    from classify_drawing import load, detect_content_box

    img = load(path, dpi, mask_text=True)
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    x0, y0, x1, y1 = detect_content_box(bw)
    img = img.copy()
    img[:y0, :] = 255
    img[y1:, :] = 255
    img[:, :x0] = 255
    img[:, x1:] = 255
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings-dir", required=True)
    ap.add_argument("--labels", default="dataset/labels.csv")
    ap.add_argument("--model", default="model_cnn.pt")
    ap.add_argument("--dpi", type=int, default=200,
                    help="må være samme dpi som make_dataset")
    ap.add_argument("--exclude", default="", help="kommaseparerte holdout-stems")
    ap.add_argument("--classes", default=DEFAULT_CLASSES,
                    help="deteksjonsklasser som skal mines")
    ap.add_argument("--radius", type=float, default=1.5,
                    help="samme-klasse-fasit innen radius*boksstørrelse = korrekt funn")
    ap.add_argument("--max-per-class-per-drawing", type=int, default=30)
    ap.add_argument("--min-conf", type=float, default=0.55)
    ap.add_argument("--out", default="dataset/HardNegativeByClass")
    ap.add_argument("--results-dir", default="results",
                    help="hvor classify_drawing legger detections-filene")
    # videresendes til classify_drawing — mining må se SAMME kandidater
    # som produksjonskonfigurasjonen, ellers høstes aldri det nye søppelet
    ap.add_argument("--cand-threshold", type=float, default=None)
    ap.add_argument("--cand-scales", default=None)
    ap.add_argument("--cand-mirror", action="store_true")
    ap.add_argument("--cand-components", action="store_true")
    args = ap.parse_args()

    wanted = {s.strip() for s in args.classes.split(",") if s.strip()}
    unknown = wanted - set(DET2GT)
    if unknown:
        raise SystemExit(f"ukjente klasser i --classes: {sorted(unknown)}")
    exclude = {norm(s) for s in args.exclude.split(",") if s.strip()}

    if not os.path.exists(args.labels):
        raise SystemExit(f"fant ikke {args.labels}; bygg dataset/labels.csv først")

    gt = {}
    with open(args.labels, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gt.setdefault(norm(r["source"]), {}).setdefault(r["class"], []).append(
                (float(r["cx_px"]), float(r["cy_px"])))
    print(f"[+] fasit for {len(gt)} tegninger fra {args.labels}")

    files = []
    for ext in ("pdf", "PDF", "jpg", "jpeg", "png"):
        files.extend(glob.glob(os.path.join(args.drawings_dir, "**", f"*.{ext}"), recursive=True))

    here = os.path.dirname(os.path.abspath(__file__))
    classifier = os.path.join(here, "classify_drawing.py")
    if not os.path.exists(classifier):
        raise SystemExit(f"fant ikke {classifier}")

    totals = defaultdict(int)
    seen_hashes = defaultdict(set)
    for bucket in {HN_BUCKET.get(c, c) for c in wanted}:
        os.makedirs(os.path.join(args.out, bucket), exist_ok=True)

    for fp in sorted(set(files)):
        stem = os.path.splitext(os.path.basename(fp))[0]
        key = find_source_key(stem, gt)
        if key is None:
            continue
        if key in exclude:
            print(f"    {stem}: holdout — hoppet over")
            continue

        cmd = [sys.executable, classifier, fp,
               "--dpi", str(args.dpi), "--model", args.model,
               "--out-dir", args.results_dir,
               "--dump-detections", "--no-non-gate-verifier"]
        if args.cand_threshold is not None:
            cmd += ["--cand-threshold", str(args.cand_threshold)]
        if args.cand_scales:
            cmd += ["--cand-scales", args.cand_scales]
        if args.cand_mirror:
            cmd += ["--cand-mirror"]
        if args.cand_components:
            cmd += ["--cand-components"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        det_path = os.path.join(args.results_dir, f"{stem}_detections.json")
        if not os.path.exists(det_path):
            print(f"    {stem}: ingen detections-fil (retur {r.returncode})")
            if r.stderr.strip():
                print("      " + r.stderr.strip().splitlines()[-1])
            continue

        with open(det_path, encoding="utf-8") as f:
            dets = json.load(f)
        dets = [d for d in dets if d.get("cls") in wanted and d.get("conf", 0) >= args.min_conf]
        dets.sort(key=lambda d: d.get("conf", 0), reverse=True)
        if not dets:
            continue

        img = load_like_classifier(fp, args.dpi)
        per_cls = defaultdict(int)
        pts = gt[key]

        for d in dets:
            cls = d["cls"]
            bucket = HN_BUCKET.get(cls, cls)
            if per_cls[bucket] >= args.max_per_class_per_drawing:
                continue
            gt_cls = DET2GT[cls]
            x0, y0, x1, y1 = map(int, d["bbox_orig"])
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            radius = args.radius * max(x1 - x0, y1 - y0)
            true_same_class = any(
                (gx - cx) ** 2 + (gy - cy) ** 2 <= radius ** 2
                for gx, gy in pts.get(gt_cls, [])
            )
            if true_same_class:
                continue

            # Samme padding som classify_drawing bruker før CNN/verifikator.
            pw, ph = int(0.35 * (x1 - x0)), int(0.35 * (y1 - y0))
            a0, b0 = max(x0 - pw, 0), max(y0 - ph, 0)
            a1, b1 = min(x1 + pw, img.shape[1]), min(y1 + ph, img.shape[0])
            crop = img[b0:b1, a0:a1]
            if crop.size == 0:
                continue

            digest = hashlib.sha1(crop.tobytes()).hexdigest()[:12]
            if digest in seen_hashes[bucket]:
                continue
            seen_hashes[bucket].add(digest)

            conf = float(d.get("conf", 0))
            name = f"{key}_{cls}_{conf:.3f}_{digest}.png"
            cv2.imwrite(os.path.join(args.out, bucket, name), crop)
            per_cls[bucket] += 1
            totals[bucket] += 1

        summary = ", ".join(f"{b}={per_cls[b]}"
                            for b in sorted({HN_BUCKET.get(c, c) for c in wanted})
                            if per_cls[b])
        if summary:
            print(f"    {stem}: {summary}")

    print(f"\n[✓] klasse-spesifikke harde negativer -> {args.out}")
    for bucket in sorted({HN_BUCKET.get(c, c) for c in wanted}):
        print(f"    {bucket:18s} {totals[bucket]:4d}")
    print("    neste: py train_verifiers.py --real dataset --synth synth")


if __name__ == "__main__":
    main()