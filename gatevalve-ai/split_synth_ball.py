#!/usr/bin/env python3
"""
split_synth_ball.py — Sorterer den eksisterende blandede synth/ball_valve/
(VAL022 åpen + VAL027 lukket om hverandre) i synth/ball_open/ og
synth/ball_closed/, med samme erosjonstest som pseudo-merker de ekte
utsnittene: fylte flater overlever erosjon med strektykkelsen, omriss og
rørlinjer gjør det ikke. Trengs når malmappen (pid-symbol-ai/templates)
ikke lenger finnes og make_synthetic ikke kan kjøres på nytt.

Bruk (fra gatevalve-ai-mappen):
  py split_synth_ball.py
Etterpå:
  rmdir /s /q synth\\ball_valve
"""
import glob
import os
import shutil

import cv2
import numpy as np

SRC = os.path.join("synth", "ball_valve")
DST_OPEN = os.path.join("synth", "ball_open")
DST_CLOSED = os.path.join("synth", "ball_closed")
THRESHOLD = 0.18   # samme som ball_pseudo_state i train_cnn.py


def fill_after_erosion(img):
    """Som i train_cnn.ball_pseudo_state, men polaritets-robust:
    syntetiske utsnitt er hvitt-på-svart, ekte er svart-på-hvitt."""
    ink = (img > 128) if img.mean() < 127 else (img < 128)
    ink = ink.astype(np.uint8)
    n = int(ink.sum())
    if n < 30:
        return 0.0
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    stroke = 2.0 * float(np.median(dt[ink > 0]))
    k = max(int(round(stroke)), 2)
    survived = int(cv2.erode(ink, np.ones((k, k), np.uint8)).sum())
    return survived / n


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f"fant ikke {SRC} — kjør fra gatevalve-ai-mappen "
                         f"(er den allerede splittet og slettet?)")
    os.makedirs(DST_OPEN, exist_ok=True)
    os.makedirs(DST_CLOSED, exist_ok=True)

    n_open = n_closed = n_bad = 0
    fracs = []
    for fp in sorted(glob.glob(os.path.join(SRC, "*.png"))):
        img = cv2.imread(fp, 0)
        if img is None:
            n_bad += 1
            continue
        frac = fill_after_erosion(img)
        fracs.append(frac)
        if frac > THRESHOLD:
            shutil.copy(fp, os.path.join(DST_CLOSED,
                        "closed_" + os.path.basename(fp)))
            n_closed += 1
        else:
            shutil.copy(fp, os.path.join(DST_OPEN,
                        "open_" + os.path.basename(fp)))
            n_open += 1

    print(f"[✓] {n_open} -> {DST_OPEN}   {n_closed} -> {DST_CLOSED}"
          + (f"   ({n_bad} uleselige)" if n_bad else ""))
    if fracs:
        fr = np.array(fracs)
        print(f"    erosjonsfyll: median {np.median(fr):.2f}, "
              f"andel > {THRESHOLD}: {(fr > THRESHOLD).mean():.0%}")
    # VAL022/VAL027 ble valgt 50/50 i make_synthetic — fordelingen bør
    # ligge rundt halvparten i hver. Stor skjevhet = sjekk terskelen.
    tot = n_open + n_closed
    if tot and not (0.30 <= n_closed / tot <= 0.70):
        print("    [!] skjev fordeling — forventet ~50/50. Åpne noen filer i "
              "begge mappene og kontroller; juster THRESHOLD ved behov.")
    print(f"    neste:  rmdir /s /q {SRC}")


if __name__ == "__main__":
    main()