#!/usr/bin/env python3
"""
make_dataset.py — Lager VEILEDET treningsdata automatisk:
kobler fasit fra Model Broker DEXPI-XML (klasse + posisjon per komponent)
til tegningsbildet, og klipper ut merkede symbolutsnitt.

Ingen manuell merking: XML-en ER labelen.

Ut (per kjøring, akkumulerende):
  dataset/<Klasse>/<tegning>_<tag>.png     utsnitt sortert på klasse
  dataset/Background/<tegning>_bgNN.png    negative utsnitt (uten komponenter)
  dataset/labels.csv                       klasse, tag, kilde, px-boks
  dataset/yolo/<tegning>.txt (+ .png)      YOLO-annotasjoner for detektortrening

Bruk:
  python make_dataset.py tegning_DGN.xml tegning.pdf [--dpi 200]
  python make_dataset.py tegning_DGN.xml tegning.jpg
  (kjør flere ganger med flere tegninger — datasettet vokser)
"""
import argparse, csv, os, random, re, sys
import numpy as np
import cv2
import xml.etree.ElementTree as ET

# klasser vi klipper ut (utvid fritt)
CLASSES = ["GateValve", "BallValve", "GlobeValve", "CheckValve", "ButterflyValve",
           "NeedleValve", "PlugValve", "AngleValve", "PipeReducer", "FlangedConnection"]
WIN_MM = 14.0          # utsnittsvindu rundt komponentsenteret
N_BACKGROUND = 25      # negative utsnitt per tegning

def load_image(path, dpi):
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(path)[0].render(scale=dpi / 72.0).to_numpy()
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY if img.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
        return img
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: sys.exit(f"kunne ikke lese {path}")
    return img

def drawing_extent(root):
    d = root.find(".//Drawing/Extent")
    if d is not None:
        mn, mx = d.find("Min"), d.find("Max")
        return (float(mn.get("X")), float(mn.get("Y")),
                float(mx.get("X")), float(mx.get("Y")))
    return (0.0, 0.0, 840.0, 594.0)   # A1-fallback

def components(root):
    """(klasse, tag, x_mm, y_mm) for alle instanser utenfor ShapeCatalogue."""
    out = []
    def walk(el, in_catalogue):
        if el.tag == "ShapeCatalogue":
            in_catalogue = True
        cls = el.get("ComponentClass")
        if not in_catalogue and cls in CLASSES:
            loc = el.find("./Position/Location")
            if loc is not None:
                x, y = float(loc.get("X", 0)), float(loc.get("Y", 0))
                if x or y:
                    out.append((cls, el.get("TagName") or "", x, y))
        for ch in el:
            walk(ch, in_catalogue)
    walk(root, False)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml"); ap.add_argument("drawing")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--out", default="dataset")
    ap.add_argument("--win-mm", type=float, default=WIN_MM)
    args = ap.parse_args()

    root = ET.parse(args.xml).getroot()
    x0, y0, x1, y1 = drawing_extent(root)
    comps = components(root)
    if not comps:
        sys.exit("fant ingen komponenter av interesse i XML-en")

    img = load_image(args.drawing, args.dpi)
    H, W = img.shape
    sx, sy = W / (x1 - x0), H / (y1 - y0)
    win = int(args.win_mm * (sx + sy) / 2)
    stem = re.sub(r"[^A-Za-z0-9]+", "", os.path.splitext(os.path.basename(args.drawing))[0])[-14:]

    os.makedirs(args.out, exist_ok=True)
    yolo_dir = os.path.join(args.out, "yolo"); os.makedirs(yolo_dir, exist_ok=True)
    lab_path = os.path.join(args.out, "labels.csv")
    new_csv = not os.path.exists(lab_path)
    fcsv = open(lab_path, "a", newline="", encoding="utf-8")
    wcsv = csv.writer(fcsv)
    if new_csv: wcsv.writerow(["class", "tag", "source", "cx_px", "cy_px", "win_px"])

    cls_ids = {c: i for i, c in enumerate(CLASSES)}
    yolo_lines, count = [], {}
    boxes = []
    for cls, tag, xm, ym in comps:
        cx = int((xm - x0) * sx)
        cy = int(H - (ym - y0) * sy)          # DEXPI har y oppover, bilder nedover
        a0, b0 = max(cx - win//2, 0), max(cy - win//2, 0)
        a1, b1 = min(cx + win//2, W), min(cy + win//2, H)
        crop = img[b0:b1, a0:a1]
        if crop.size == 0: continue
        d = os.path.join(args.out, cls); os.makedirs(d, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9]+", "", tag) or f"x{cx}y{cy}"
        cv2.imwrite(os.path.join(d, f"{stem}_{safe}.png"), crop)
        wcsv.writerow([cls, tag, stem, cx, cy, win])
        yolo_lines.append(f"{cls_ids[cls]} {cx/W:.5f} {cy/H:.5f} {win/W:.5f} {win/H:.5f}")
        boxes.append((a0, b0, a1, b1))
        count[cls] = count.get(cls, 0) + 1

    # negative utsnitt: tilfeldige vinduer som ikke overlapper noen komponent
    bg_dir = os.path.join(args.out, "Background"); os.makedirs(bg_dir, exist_ok=True)
    rng = random.Random(42); made = 0; tries = 0
    while made < N_BACKGROUND and tries < 600:
        tries += 1
        a0 = rng.randint(0, max(W - win, 1)); b0 = rng.randint(0, max(H - win, 1))
        a1, b1 = a0 + win, b0 + win
        if any(not (a1 < c0 or a0 > c2 or b1 < c1 or b0 > c3) for c0, c1, c2, c3 in boxes):
            continue
        crop = img[b0:b1, a0:a1]
        if (crop < 128).mean() < 0.005:       # helt tomt papir er uinteressant
            continue
        cv2.imwrite(os.path.join(bg_dir, f"{stem}_bg{made:02d}.png"), crop)
        made += 1

    cv2.imwrite(os.path.join(yolo_dir, f"{stem}.png"), img)
    open(os.path.join(yolo_dir, f"{stem}.txt"), "w").write("\n".join(yolo_lines))
    open(os.path.join(yolo_dir, "classes.txt"), "w").write("\n".join(CLASSES))
    fcsv.close()

    print(f"[✓] {stem}: {sum(count.values())} merkede utsnitt + {made} bakgrunner "
          f"(vindu {win}px @ {args.dpi} dpi)")
    for c, n in sorted(count.items(), key=lambda kv: -kv[1]):
        print(f"    {n:3d}  {c}")
    print(f"    -> {args.out}/<Klasse>/, labels.csv, yolo/")

if __name__ == "__main__":
    main()
