#!/usr/bin/env python3
"""
learn_from_legend.py — Lærer gate valve-symbolene fra legende-PDF-en ved å
LESE beskrivelsesteksten, ikke ved forhåndskoding:

  1. Finner tekstene "GATE VALVE, OPEN" og "GATE VALVE, CLOSE" i PDF-en.
  2. Klipper ut symbolfeltet som hører til hver tekst.
  3. Trimmer bort ALT som ikke er selve sløyfen (de to trekantene):
     tekst maskeres, og alle strøk som berører kanten av feltet
     (boksen, hjørnemerker, rørstubber) fjernes. Kun den største
     sammenhengende figuren nær midten beholdes.
  4. Lagrer gate_open.png og gate_closed.png + labels.json.

Bruk:
  python learn_from_legend.py U999-1-000--PT-111-01.PDF
"""
import json, re, sys
import numpy as np
import cv2
import pdfplumber
import pypdfium2 as pdfium

DPI = 300
TARGETS = {"GATE VALVE, OPEN": "gate_open", "GATE VALVE, CLOSE": "gate_closed"}

def render(pdf_path):
    doc = pdfium.PdfDocument(pdf_path)
    img = doc[0].render(scale=DPI / 72.0).to_numpy()
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY if img.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
    return img

def isolate_symbol(crop):
    """Behold kun symbolkjernen: fjern alt som berører kantene, ta største
    gjenværende komponent-klynge nær midten."""
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(bw, connectivity=8)
    H, W = bw.shape
    keep = np.zeros_like(bw)
    cy0, cx0 = H / 2, W / 2
    best = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        touches = x == 0 or y == 0 or x + w >= W or y + h >= H
        frame_like = w > 0.6 * W or h > 0.6 * H     # rammen rundt legendefeltet
        if touches or frame_like or area < 20:
            continue
        d = ((cent[i][0] - cx0) ** 2 + (cent[i][1] - cy0) ** 2) ** 0.5
        best.append((d, i))
    if not best:
        return None
    # sløyfen kan være 1 komponent (åpen: omriss) eller 2 (lukket: to fylte
    # trekanter) — ta komponentene nærmest midten som er omtrent like nære
    best.sort()
    d0 = best[0][0]
    for d, i in best:
        if d <= d0 + 0.4 * max(H, W) * 0.15 + 30:
            keep[lab == i] = 255
    ys, xs = np.where(keep > 0)
    pad = 3
    return keep[max(ys.min()-pad,0):ys.max()+pad, max(xs.min()-pad,0):xs.max()+pad]

def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "U999-1-000--PT-111-01.PDF"
    img = render(pdf_path)
    H, W = img.shape
    scale = DPI / 72.0

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        # sett sammen ord til linjer slik at "GATE VALVE, OPEN" kan gjenfinnes
        lines = {}
        for w in words:
            key = round(w["top"], 1)
            lines.setdefault(key, []).append(w)

    # masker all tekst i bildet
    img = img.copy()
    for w in words:
        x0, x1 = int((w["x0"]-1)*scale), int((w["x1"]+1)*scale)
        y0, y1 = int((w["top"]-1)*scale), int((w["bottom"]+1)*scale)
        img[max(y0,0):min(y1,H), max(x0,0):min(x1,W)] = 255

    labels = {}
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w["x0"])
        # grupper ord som står nær hverandre horisontalt til fraser
        phrase, group = [], []
        for w in ws:
            if group and w["x0"] - group[-1]["x1"] > 12:
                phrase.append(group); group = [w]
            else:
                group.append(w)
        if group: phrase.append(group)
        for g in phrase:
            text = " ".join(x["text"] for x in g).upper().strip()
            if text in TARGETS:
                name = TARGETS[text]
                gx0, gx1 = g[0]["x0"], g[-1]["x1"]
                cx = (gx0 + gx1) / 2 * scale
                ty = g[0]["top"] * scale
                # symbolfeltet ligger over teksten (over kodelinjene): fast vindu
                win_w, win_h = int(190 * scale), int(140 * scale)
                x0 = int(max(cx - win_w/2, 0)); x1 = int(min(cx + win_w/2, W))
                y1 = int(max(ty - 45 * scale * 72/DPI, 0))  # hopp over VALxxx/VALVES1-linjene
                y1 = int(ty - 3.2 * scale * 10)
                y0 = int(max(y1 - win_h, 0))
                crop = img[y0:y1, x0:x1]
                sym = isolate_symbol(crop)
                if sym is None:
                    print(f"[!] fant ikke symbol for {text!r}"); continue
                out = f"{name}.png"
                cv2.imwrite(out, sym)
                labels[name] = {"legend_text": text, "template": out,
                                "size_px": [int(sym.shape[1]), int(sym.shape[0])],
                                "dpi": DPI, "fill": round(float((sym > 0).mean()), 3)}
                print(f"[✓] {text!r}  ->  {out}  "
                      f"({sym.shape[1]}x{sym.shape[0]} px, fyllgrad {labels[name]['fill']})")

    json.dump(labels, open("labels.json", "w"), indent=2)
    if len(labels) == 2:
        print("[✓] lærte begge symbolene fra legendeteksten -> labels.json")
    else:
        print(f"[!] lærte bare {len(labels)}/2 — sjekk legendefilen")

if __name__ == "__main__":
    main()
