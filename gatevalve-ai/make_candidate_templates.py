#!/usr/bin/env python3
"""
make_candidate_templates.py — Lager kandidat-prototyper for trinn én:
én renset symbolkjerne per ventilklasse, hentet fra legendemalene.
Kandidatgeneratoren i classify_drawing.py plukker dem opp automatisk.

Bruk (én gang):
  py make_candidate_templates.py --templates ..\\symbol-ai\\pid-symbol-ai\\templates
"""
import argparse, os
import cv2
from make_synthetic import load_tpl   # samme rensing som i syntetisk trening

# VERIFISERT mot legendeteksten (PT-111)
CODES = {"ball": "VAL022", "globe": "VAL017",
         "check": "VAL033", "butterfly": "VAL028",
         "reducer": "FIT005"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", required=True)
    args = ap.parse_args()
    for name, code in CODES.items():
        t = load_tpl(os.path.join(args.templates, f"{code}.png"))
        if t is None:
            print(f"[!] fant ikke {code}"); continue
        out = f"cand_{name}.png"
        cv2.imwrite(out, t)
        print(f"[✓] {name:10s} ({code}) -> {out}  {t.shape[1]}x{t.shape[0]} px")

if __name__ == "__main__":
    main()