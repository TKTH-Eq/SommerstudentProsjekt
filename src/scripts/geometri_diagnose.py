"""
geometri_diagnose.py
=====================================================================
Why did extract_region_geometry() find nothing?

Standalone, no Streamlit, no imports from the project. Point it at a drawing
and its detections file and it dumps what pdfplumber actually sees — first for
the page as a whole, then inside one detection region, then across six
variations of the lookup so you can see which one (if any) finds the symbol.

    python geometri_diagnose.py drawing.pdf detections.json --dpi 200 --index 0

The six variants exist because there are six plausible reasons for an empty
region, and prose cannot tell them apart:

    y-flip on/off        the raster grows downwards, PDF user space upwards.
                         Get this backwards and you read the mirror image of
                         the right place.
    contain vs intersect containment rejects any primitive with a single point
                         outside the box. A circle drawn as four bezier
                         segments has control points OUTSIDE the circle, so a
                         tight box throws the circle away and keeps the
                         straight pipe running through it — which is exactly
                         what "1 primitive" looks like.
    padding              a box fitted to the ink often clips the symbol.

It also reports fills separately from strokes. A symbol drawn as a solid
filled shape (the black triangles on some Huldra sheets) has no stroked
outline at all, and a configuration whose patterns are built from stroked
control points will never match it. If the fills column is where all the
geometry lives, that is the answer, and no amount of tuning the reader helps.

Nothing is written. Read-only diagnosis.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _page_summary(page) -> dict:
    return {
        "size_pt": (round(page.width, 1), round(page.height, 1)),
        "rotation": getattr(page, "rotation", 0),
        "lines": len(page.lines),
        "curves": len(page.curves),
        "rects": len(page.rects),
        "chars": len(page.chars),
        "images": len(page.images),
        "filled_curves": sum(1 for c in page.curves if c.get("fill")),
        "stroked_curves": sum(1 for c in page.curves if c.get("stroke")),
    }


def _points(prim, page_height: float, flip: bool) -> list[tuple[float, float]]:
    """Every point of a primitive, in top-down coordinates."""
    pts = prim.get("pts")
    if pts:
        out = [(float(px), float(py)) for px, py in pts]
        return [(px, page_height - py) for px, py in out] if flip else out
    if "x0" in prim and "top" in prim:
        return [(float(prim["x0"]), float(prim["top"])),
                (float(prim["x1"]), float(prim["bottom"]))]
    return []


def _collect(page, region, flip: bool, mode: str) -> list[dict]:
    """Primitives in the region under one combination of settings."""
    x0, y0, x1, y1 = region
    found = []
    for kind in ("lines", "curves", "rects"):
        for prim in getattr(page, kind):
            pts = _points(prim, page.height, flip)
            if not pts:
                continue
            inside = [x0 <= px <= x1 and y0 <= py <= y1 for px, py in pts]
            hit = all(inside) if mode == "contain" else any(inside)
            if hit:
                found.append({"kind": kind, "n_points": len(pts),
                              "fill": bool(prim.get("fill")),
                              "stroke": bool(prim.get("stroke")),
                              "pts": pts})
    return found


def diagnose(pdf_path: str, det_path: str, dpi: int, index: int,
             page_no: int = 0, pads=(0.0, 4.0, 12.0)) -> None:
    import pdfplumber

    dets = json.loads(Path(det_path).read_text(encoding="utf-8"))
    if not dets:
        print("Deteksjonsfilen er tom.")
        return
    dets = sorted(dets, key=lambda d: -float(d.get("conf", 0)))
    if index >= len(dets):
        print(f"Bare {len(dets)} deteksjoner i filen.")
        return
    det = dets[index]

    with pdfplumber.open(pdf_path) as pdf:
        print(f"PDF: {Path(pdf_path).name} · {len(pdf.pages)} side(r)")
        page = pdf.pages[page_no]
        s = _page_summary(page)
        print("\n--- SIDEN SOM HELHET ---")
        for k, v in s.items():
            print(f"  {k:16s} {v}")

        if s["lines"] + s["curves"] + s["rects"] == 0:
            print("\n  INGEN VEKTORPRIMITIVER PÅ SIDEN.")
            print("  Enten er arket et skann, eller så ligger tegningen i et")
            print("  Form XObject som pdfplumber ikke pakker ut. Test det med:")
            print("      page.objects.keys()   og se etter 'image' alene")
            print("  Er det XObjects, må de flates ut først — pikkeluttrekk")
            print("  hjelper ikke, og generering er utelukket for dette arket.")
            return
        if s["filled_curves"] and not s["stroked_curves"]:
            print("\n  MERK: all kurvegeometri er FYLT, ingen er STREKET.")
            print("  Model Broker-mønstre matcher kontrollpunkter på streker.")
            print("  Fylte symboler vil aldri treffe dem, uansett toleranse.")

        scale = dpi / 72.0
        box = det.get("bbox_orig")
        print(f"\n--- DETEKSJON {index} ---")
        print(f"  klasse    {det.get('cls')} (konfidens {det.get('conf')})")
        print(f"  bbox px   {box}   @ {dpi} DPI")
        if not box:
            print("  Deteksjonen mangler bbox_orig.")
            return
        bx0, by0, bx1, by1 = (v / scale for v in box)
        print(f"  bbox pt   ({bx0:.1f}, {by0:.1f}) - ({bx1:.1f}, {by1:.1f})")
        print(f"  sidehøyde {page.height:.1f} pt — hvis boksen ligger utenfor "
              f"[0, {page.height:.0f}] er DPI eller side feil")

        print("\n--- SEKS VARIANTER ---")
        print(f"  {'flip':>5} {'modus':>10} {'pad':>5} {'treff':>6} "
              f"{'streket':>8} {'fylt':>5}")
        best = None
        for flip in (False, True):
            for mode in ("contain", "intersect"):
                for pad_px in pads:
                    pad = pad_px / scale
                    region = (bx0 - pad, by0 - pad, bx1 + pad, by1 + pad)
                    found = _collect(page, region, flip, mode)
                    stroked = sum(1 for f in found if f["stroke"])
                    filled = sum(1 for f in found if f["fill"])
                    print(f"  {str(flip):>5} {mode:>10} {pad_px:5.0f} "
                          f"{len(found):6d} {stroked:8d} {filled:5d}")
                    if best is None or len(found) > len(best[0]):
                        best = (found, flip, mode, pad_px)

        found, flip, mode, pad_px = best
        print(f"\n--- BESTE VARIANT: flip={flip}, {mode}, pad={pad_px:.0f} px "
              f"-> {len(found)} primitiver ---")
        if not found:
            print("  Ingen variant fant noe. Regionen er tom i alle seks.")
            print("  Sjekk i denne rekkefølgen:")
            print("   1. Er bbox_orig i piksler ved samme DPI som oppgitt?")
            print("   2. Har PDF-en flere sider — er symbolet på side 0?")
            print("   3. Har siden /Rotate satt? Da stemmer ikke aksene.")
            return
        for f in found[:12]:
            tag = ("fylt" if f["fill"] else "") + \
                  ("+streket" if f["stroke"] else "")
            pts = ", ".join(f"({x:.1f},{y:.1f})" for x, y in f["pts"][:4])
            more = " …" if len(f["pts"]) > 4 else ""
            print(f"  {f['kind']:6s} {f['n_points']:3d} pkt  {tag:12s} {pts}{more}")
        if len(found) > 12:
            print(f"  … og {len(found) - 12} til")

        print("\n--- TOLKNING ---")
        if len(found) < 3:
            print("  Under tre primitiver. Et symbol er aldri så enkelt —")
            print("  dette er nesten sikkert rørlinjen som går gjennom, ikke")
            print("  ventilen. Prøv større pad, eller se om 'contain' kaster")
            print("  bort bezier-segmenter med kontrollpunkter utenfor boksen.")
        elif mode == "intersect" and pad_px > 0:
            print("  Fant geometri, men bare med romsligere innstillinger enn")
            print("  extract_region_geometry() bruker i dag. Endre modus til")
            print("  intersect og øk pad_px, så bør generering fungere.")
        else:
            print("  Geometrien er der og leses med standardinnstillinger.")
            print("  Feiler generering likevel, ligger problemet et annet sted")
            print("  enn i denne funksjonen.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("detections")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--index", type=int, default=0,
                    help="Which detection, sorted by confidence. Default 0.")
    ap.add_argument("--page", type=int, default=0)
    args = ap.parse_args()
    diagnose(args.pdf, args.detections, args.dpi, args.index, args.page)


if __name__ == "__main__":
    main()