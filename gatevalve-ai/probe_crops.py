#!/usr/bin/env python3
"""
probe_crops.py — Diagnoseinstrument: mat EKTE dataset-utsnitt (klippet av
make_dataset fra DEXPI-posisjonene) rett inn i CNN + verifikator, utenom
kandidatgenereringen. Skiller de to feilmodusene i deteksjonskjeden:

  * CNN-en klassifiserer utsnittene riktig  -> FORSLAGSPROBLEM
    (posisjonene foreslås aldri: mal/terskel/skala i classify_drawing)
  * CNN-en kaller utsnittene background/annet -> KLASSIFISERINGSPROBLEM
    (treningsdata: f.eks. bakgrunnsvaksine som kolliderer med symbolstilen)

Bruk (fra gatevalve-ai-mappen):
  py probe_crops.py --class CheckValve --source 25WHO64PU00101
  py probe_crops.py --class BallValve                (alle tegninger)
"""
import argparse
import glob
import os
import re
from collections import Counter

import cv2
import numpy as np

from train_classifier import canonicalize


def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def cross_candidates(args):
    """For hver fasit-posisjon av klassen: nærmeste kandidat og hva CNN-en
    sa om den. Skiller (a) aldri foreslått fra (b) foreslått men feilklassifisert."""
    import csv
    import json
    cands = json.load(open(args.candidates, encoding="utf-8"))
    want = norm(args.source) if args.source else None
    pts = []
    for r in csv.DictReader(open(os.path.join("dataset", "labels.csv"),
                                 encoding="utf-8")):
        if r["class"] != args.cls:
            continue
        if want and norm(r["source"]) != want:
            continue
        pts.append((float(r["cx_px"]), float(r["cy_px"]), float(r["win_px"])))
    if not pts:
        raise SystemExit(f"ingen {args.cls}-fasit"
                         + (f" for {args.source}" if args.source else ""))
    print(f"[+] {len(pts)} fasit-posisjoner mot {len(cands)} kandidater")
    outcome = Counter()
    for gx, gy, win in pts:
        best, bd = None, None
        for c in cands:
            x0, y0, x1, y1 = c["bbox_orig"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            d = ((gx - cx) ** 2 + (gy - cy) ** 2) ** 0.5
            if bd is None or d < bd:
                best, bd = c, d
        if best is None or bd > win:
            print(f"    ({gx:6.0f},{gy:6.0f})  ALDRI FORESLÅTT "
                  f"(nærmeste kandidat {bd:.0f}px unna)" if best else
                  f"    ({gx:6.0f},{gy:6.0f})  ALDRI FORESLÅTT")
            outcome["aldri foreslått"] += 1
        else:
            x0, y0, x1, y1 = best["bbox_orig"]
            print(f"    ({gx:6.0f},{gy:6.0f})  {bd:4.0f}px  boks "
                  f"{x1-x0}x{y1-y0}  -> {best['cls']} ({best['conf']:.2f})")
            outcome[best["cls"]] += 1
    print(f"\n    utfall: {dict(outcome)}")
    print("    Tolkning: 'aldri foreslått' -> forslagskilde/størrelsesfilter; "
          "'background' -> utsnittsgeometri (boksen fanger ikke nok kontekst); "
          "riktig klasse med lav konf -> terskel/tier.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="cls", required=True,
                    help="dataset-mappe, f.eks. CheckValve")
    ap.add_argument("--source", default=None,
                    help="begrens til én tegning (norm-stem)")
    ap.add_argument("--model", default="model_cnn.pt")
    ap.add_argument("--verifiers", default="verifiers.pt")
    ap.add_argument("--verifier-class", default=None,
                    help="verifikator å probe (standard: gjettes fra --class)")
    ap.add_argument("--candidates", default=None,
                    help="results/<stem>_candidates.json fra classify_drawing "
                         "--dump-candidates: kryss fasit-posisjonene mot alle "
                         "klassifiserte kandidater i stedet for å probe utsnitt")
    args = ap.parse_args()

    if args.candidates:
        cross_candidates(args)
        return

    import torch
    from train_cnn import build_net

    ck = torch.load(args.model, map_location="cpu")
    classes = ck["classes"]
    net = build_net(len(classes))
    net.load_state_dict(ck["state_dict"])
    net.eval()

    vnet, vthr = None, None
    vcls = args.verifier_class
    if vcls is None:
        guess = {"CheckValve": "check_valve", "BallValve": "ball_valve",
                 "GlobeValve": "globe_valve", "ButterflyValve": "butterfly_valve",
                 "PipeReducer": "reducer", "GateValve": "gate_valve"}
        vcls = guess.get(args.cls)
    if vcls and os.path.exists(args.verifiers):
        vk = torch.load(args.verifiers, map_location="cpu")
        if vcls in vk.get("state_dicts", {}):
            vnet = build_net(2)
            vnet.load_state_dict(vk["state_dicts"][vcls])
            vnet.eval()
            vthr = vk["thresholds"][vcls]

    files = sorted(glob.glob(os.path.join("dataset", args.cls, "*.png")))
    if args.source:
        want = norm(args.source)
        files = [f for f in files if norm(os.path.basename(f)).startswith(want)]
    if not files:
        raise SystemExit(f"ingen utsnitt i dataset/{args.cls}"
                         + (f" fra {args.source}" if args.source else ""))

    pred_counter = Counter()
    conf_when_right, vconfs = [], []
    for fp in files:
        img = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        x = canonicalize(img)[None, None].astype(np.float32) / 255.0
        with torch.no_grad():
            p = net(torch.tensor(x)).softmax(1).numpy()[0]
        i = int(p.argmax())
        pred_counter[classes[i]] += 1
        # "riktig" = en klasse som hører til mappen (ball har to tilstander)
        if classes[i].replace("_open", "").replace("_closed", "") in \
                args.cls.lower().replace("valve", "_valve").replace("pipereducer", "reducer"):
            conf_when_right.append(float(p[i]))
        if vnet is not None:
            with torch.no_grad():
                vconfs.append(float(vnet(torch.tensor(x)).softmax(1).numpy()[0, 1]))

    n = sum(pred_counter.values())
    print(f"[+] {n} ekte {args.cls}-utsnitt"
          + (f" fra {args.source}" if args.source else " (alle tegninger)"))
    print("    CNN-prediksjoner:")
    for cls, c in pred_counter.most_common():
        print(f"      {cls:<18} {c:>4}  ({c/n:.0%})")
    if conf_when_right:
        print(f"    median konfidens ved riktig klasse: "
              f"{np.median(conf_when_right):.2f}")
    if vconfs:
        ok = sum(1 for v in vconfs if v >= vthr)
        print(f"    verifikator ({vcls}, terskel {vthr:.2f}): "
              f"{ok}/{len(vconfs)} over terskel, median {np.median(vconfs):.2f}")
    print("\n    Tolkning: dominerer riktig klasse -> forslagsproblem "
          "(mal/terskel/skala). Dominerer background/annet -> "
          "klassifiseringsproblem (treningsdata).")


if __name__ == "__main__":
    main()