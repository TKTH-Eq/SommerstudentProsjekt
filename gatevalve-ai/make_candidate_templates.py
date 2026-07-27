#!/usr/bin/env python3
"""
make_candidate_templates.py — Lager kandidat-prototyper for trinn én
(malmatch-sveipet i classify_drawing.py). To kilder:

  1. LEGENDEN (--templates): én renset symbolkjerne per ventilklasse
     fra legendemalene (VAL022/VAL027/... via load_tpl-rensingen).
  2. EKTE TEGNINGER (--check2-source): tegningsstil-maler for symboler
     som tegnes annerledes på tegningene enn i legenden. I dag: check
     valve (klaff-stilen på utility-tegningene), fra dataset/CheckValve-
     utsnittene som make_dataset alt har klippet fra DEXPI-posisjonene.

En mal dekker en TEGNESTIL, ikke en klasse: matcher ingen mal stilen,
foreslås posisjonen aldri, og CNN-en får aldri se symbolet (jf. lukkede
ball valves og check-klaffene, begge målt som deteksjonsgap i foldene).

Bruk:
  py make_candidate_templates.py --templates templates
      (legende-malene + cand_check2 fra standardtegningen)
  py make_candidate_templates.py --check2-source 25WHO64PU00101
      (kun tegningsstil-malen, fra annen tegning)
  py make_candidate_templates.py --check2-file dataset/CheckValve/<fil>.png
      (velg utsnitt manuelt hvis autovalget traff dårlig)
SJEKK ALLTID de genererte cand_*.png visuelt.
"""
import argparse
import csv
import glob
import os
import re

import cv2
import numpy as np

# VERIFISERT mot legendeteksten (PT-111)
CODES = {"ball": "VAL022", "ball_closed": "VAL027",
         "globe": "VAL017",
         "check": "VAL033", "butterfly": "VAL028",
         "reducer": "FIT005"}

CHECK_DIR = os.path.join("dataset", "CheckValve")


def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def isolate_symbol(crop):
    """Svart-på-hvitt tegningsutsnitt -> hvitt-på-svart symbolkjerne uten
    gjennomgående rør. Returnerer None hvis ingenting brukbart står igjen."""
    _, ink = cv2.threshold(255 - crop, 0, 255,
                           cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    H, W = ink.shape
    n, lab, stats, cents = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8))
    work = ink.copy()
    for i in range(1, n):                     # fjern gjennomgående rørlinjer
        x, y, w, h, a = stats[i]
        if w > 0.9 * W and h <= max(4, 0.08 * H):
            work[lab == i] = 0
        if h > 0.9 * H and w <= max(4, 0.08 * W):
            work[lab == i] = 0
    n2, lab2, stats2, cents2 = cv2.connectedComponentsWithStats((work > 0).astype(np.uint8))
    best, bd = None, None
    for i in range(1, n2):                    # komponenten nærmest sentrum
        if stats2[i, cv2.CC_STAT_AREA] < 15:
            continue
        d = (cents2[i][0] - W / 2) ** 2 + (cents2[i][1] - H / 2) ** 2
        if bd is None or d < bd:
            best, bd = i, d
    if best is None:
        return None
    keep = np.zeros_like(work)
    bx, by, bw, bh, _ = stats2[best]
    # naboer (sete o.l.) må OVERLAPPE klaffens boks (15 % slingring) —
    # tag-tekst over/under linjen faller da utenfor
    pad = 0.15 * max(bw, bh)
    for i in range(1, n2):
        x, y, w, h, a = stats2[i]
        overlaps = (x < bx + bw + pad and x + w > bx - pad
                    and y < by + bh + pad and y + h > by - pad)
        if overlaps and a >= 8:
            keep[lab2 == i] = 255
    ys, xs = np.where(keep > 0)
    if len(ys) < 30:
        return None
    core = keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return core if min(core.shape) >= 8 else None


def legend_templates(templates_dir):
    from make_synthetic import load_tpl   # samme rensing som i syntetisk trening
    for name, code in CODES.items():
        t = load_tpl(os.path.join(templates_dir, f"{code}.png"))
        if t is None:
            print(f"[!] fant ikke {code}")
            continue
        out = f"cand_{name}.png"
        cv2.imwrite(out, t)
        print(f"[✓] {name:12s} ({code}) -> {out}  {t.shape[1]}x{t.shape[0]} px")


def drawing_check_template(source, explicit_file, drawings_dir, dpi):
    """Foretrukket vei: klipp fra TEKSTMASKET rendring av PDF-en (taggene
    finnes da ikke i bildet), med posisjoner fra dataset/labels.csv.
    Fallback uten --drawings-dir: rå dataset-utsnitt (kan ha tekst)."""
    if drawings_dir:
        want = norm(source)
        rows = [r for r in csv.DictReader(open(os.path.join("dataset", "labels.csv"),
                                               encoding="utf-8"))
                if r["class"] == "CheckValve" and norm(r["source"]) == want]
        if not rows:
            print(f"[!] ingen CheckValve-rader for {source} i labels.csv")
            return
        pdfs = []
        for ext in ("pdf", "PDF"):
            pdfs += glob.glob(os.path.join(drawings_dir, "**", f"*.{ext}"),
                              recursive=True)
        match = [p for p in pdfs
                 if norm(os.path.splitext(os.path.basename(p))[0]).endswith(want)
                 or want.endswith(norm(os.path.splitext(os.path.basename(p))[0]))]
        if not match:
            print(f"[!] fant ingen PDF for {source} under {drawings_dir}")
            return
        from classify_drawing import load
        img = load(match[0], dpi, mask_text=True)
        for r in rows:
            cx, cy = float(r["cx_px"]), float(r["cy_px"])
            win = int(float(r["win_px"]))
            x0, y0 = max(int(cx - win / 2), 0), max(int(cy - win / 2), 0)
            crop = img[y0:y0 + win, x0:x0 + win]
            core = isolate_symbol(crop)
            if core is None:
                continue
            cv2.imwrite("cand_check2.png", core)
            print(f"[✓] check2 (tekstmasket, {os.path.basename(match[0])} "
                  f"@ {int(cx)},{int(cy)}) -> cand_check2.png  "
                  f"{core.shape[1]}x{core.shape[0]} px")
            print("    Åpne filen og sjekk at det er klaffsymbolet.")
            return
        print("[!] ingen brukbare posisjoner — prøv annen --check2-source")
        return

    # fallback: rå dataset-utsnitt (kan inneholde tag-tekst)
    files = sorted(glob.glob(os.path.join(CHECK_DIR, "*.png")))
    pick = ([explicit_file] if explicit_file else
            [f for f in files if norm(os.path.basename(f)).startswith(norm(source))])
    if not pick:
        print(f"[!] ingen CheckValve-utsnitt fra {source} — velg med --check2-file")
        return
    for fp in pick:
        crop = cv2.imread(fp, 0)
        core = isolate_symbol(crop) if crop is not None else None
        if core is None:
            continue
        cv2.imwrite("cand_check2.png", core)
        print(f"[✓] check2 (rått utsnitt, {os.path.basename(fp)}) -> cand_check2.png")
        print("    NB: rå utsnitt kan ha tag-tekst — bruk --drawings-dir for "
              "tekstmasket klipping.")
        return
    print("[!] ingen brukbare utsnitt — bruk --drawings-dir eller --check2-file")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", default=None,
                    help="legendemal-mappen; utelat for kun tegningsstil-maler")
    ap.add_argument("--check2-source", default="25WHO63PU00501",
                    help="tegning å hente check-klaffen fra (norm-stem)")
    ap.add_argument("--check2-file", default=None,
                    help="eksplisitt CheckValve-utsnitt")
    ap.add_argument("--no-check2", action="store_true",
                    help="hopp over tegningsstil-malen")
    ap.add_argument("--drawings-dir", default=None,
                    help="rå tegningsmappe -> klipp check2 fra TEKSTMASKET "
                         "rendring (anbefalt)")
    ap.add_argument("--dpi", type=int, default=200,
                    help="må matche make_dataset (labels.csv-koordinatene)")
    args = ap.parse_args()

    if args.templates:
        legend_templates(args.templates)
    if not args.no_check2:
        drawing_check_template(args.check2_source, args.check2_file,
                               args.drawings_dir, args.dpi)
    if not args.templates and args.no_check2:
        print("ingenting å gjøre — angi --templates og/eller la check2 stå på")


if __name__ == "__main__":
    main()