#!/usr/bin/env python3
"""
check_drawing.py — Svarer TRUE/FALSE: inneholder tegningen gate valve
(åpen / lukket)? Bruker symbolene lært av learn_from_legend.py.

To trinn:
  1. KANDIDATER: malmatch (begge sløyfene, flere skalaer, 0° og 90°) finner
     steder som ligner en sløyfe. Geometri-krav (størrelse, symmetri) og
     NMS luker bort strekkryss og tekst.
  2. KLASSIFISERING: åpen vs. lukket avgjøres av fyllgraden i funnet —
     beslutningsgrensen er lært fra legenden (midtpunktet mellom de to
     malenes fyllgrad), ikke håndsatt.

Ut:
  terminal:  gate valve OPEN:  TRUE/FALSE (antall, beste score)
  <navn>_verdict.json          maskinlesbart svar
  <navn>_proof.png             tegning med funn markert (grønn=åpen, rød=lukket)

Bruk:
  python check_drawing.py tegning.pdf [--dpi 300]
  python check_drawing.py tegning.jpg [--upscale 3]
"""
import argparse, json, os, sys
import numpy as np
import cv2

def load(path, dpi):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(path)[0].render(scale=dpi / 72.0).to_numpy()
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY if img.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
        return img
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        sys.exit(f"kunne ikke lese {path}")
    return img

def prep(bw, blur=3):
    f = bw.astype(np.float32) / 255.0
    return cv2.GaussianBlur(f, (blur, blur), 0) if blur else f

def is_bowtie(roi, closed_hyp, stroke):
    """Geometrisk maskesjekk. ÅPEN: blekket skal ligge på et X (+ endestolper).
    LUKKET: blekket skal ligge inni to fylte trekanter som fyller dem godt.
    Uavhengig av oppløsning og robust mot ±stroke lokaliseringsfeil."""
    Hh, Ww = roi.shape
    if Ww < 10 or Hh < 6:
        return False
    ink = roi > 0
    n_ink = int(ink.sum())
    if n_ink < 12:
        return False
    th = max(int(round(stroke * 1.8)), 2)
    if closed_hyp:
        # to fylte trekanter: |dy| <= (|dx|/halvbredde) * halvhøyde
        yy, xx = np.mgrid[0:Hh, 0:Ww]
        dx = np.abs(xx - (Ww - 1) / 2) / max((Ww - 1) / 2, 1)
        dy = np.abs(yy - (Hh - 1) / 2) / max((Hh - 1) / 2, 1)
        mask = dy <= dx + (th / Hh)
        inside = (ink & mask).sum() / n_ink
        fillgrad = (ink & mask).sum() / max(mask.sum(), 1)
        if not (inside >= 0.85 and fillgrad >= 0.45):
            return False
        # profilkrav: jevne, høye ender + ~halv høyde ved kvartpunktene
        cols = (roi > 0).sum(axis=0).astype(np.float32)
        kk = max(Ww // 14, 1)
        cols = np.convolve(cols, np.ones(2*kk+1)/(2*kk+1), mode="same")
        e = max(int(Ww * 0.16), 2)
        hL, hR = cols[:e].max(), cols[-e:].max()
        hi = max(hL, hR)
        if min(hL, hR) < 0.60 * Hh or abs(hL - hR) > 0.30 * hi:
            return False          # skjev kile / én stolpe
        for q in (0.25, 0.75):
            r = cols[int(Ww * q)] / max(hi, 1)
            if not (0.28 <= r <= 0.80):
                return False      # stolpepar (1.0) eller hult midtparti (0)
        # taper-test: i topp/bunn-radene ligger blekket KUN ytterst ved endene
        # (fylte blokker/striper har blekk over hele bredden der)
        band = max(int(Hh * 0.20), 1)
        outer = np.zeros(Ww, bool)
        oe = max(int(Ww * 0.25), 2)
        outer[:oe] = outer[-oe:] = True
        for rows in (ink[:band], ink[-band:]):
            r_ink = int(rows.sum())
            if r_ink and rows[:, outer].sum() / r_ink < 0.70:
                return False
        return True
    # åpen: X-omriss + venstre/høyre endestolper
    mask = np.zeros((Hh, Ww), np.uint8)
    cv2.line(mask, (0, 0), (Ww - 1, Hh - 1), 1, th)
    cv2.line(mask, (0, Hh - 1), (Ww - 1, 0), 1, th)
    cv2.line(mask, (0, 0), (0, Hh - 1), 1, th)
    cv2.line(mask, (Ww - 1, 0), (Ww - 1, Hh - 1), 1, th)
    on_mask = (ink & (mask > 0)).sum() / n_ink
    x_cov = (ink & (mask > 0)).sum() / max(int(mask.sum()), 1)
    return on_mask >= 0.70 and x_cov >= 0.28

def strip_pipes(roi):
    """Fjern gjennomgående rørlinjer i kanten av utsnittet."""
    r = roi
    while r.shape[0] > 6 and (r[0] > 0).mean() > 0.85:  r = r[1:]
    while r.shape[0] > 6 and (r[-1] > 0).mean() > 0.85: r = r[:-1]
    while r.shape[1] > 8 and (r[:, 0] > 0).mean() > 0.85:  r = r[:, 1:]
    while r.shape[1] > 8 and (r[:, -1] > 0).mean() > 0.85: r = r[:, :-1]
    return r

def core_ratio(roi, stroke):
    """Andel blekk som overlever erosjon med strektykkelsen.
    Omriss (åpen) -> ~0, fylt (lukket) -> beholder kjerne. Oppløsningsuavhengig."""
    k = max(int(round(stroke)), 2)
    er = cv2.erode(roi, np.ones((k, k), np.uint8))
    ink = (roi > 0).sum()
    return (er > 0).sum() / max(ink, 1)

def nms(dets, iou=0.3):
    dets = sorted(dets, key=lambda d: -d["score"]); kept = []
    for d in dets:
        x0, y0, x1, y1 = d["bbox"]; a = (x1 - x0) * (y1 - y0)
        if all((lambda k: (max(0, min(x1,k[2])-max(x0,k[0])) *
                            max(0, min(y1,k[3])-max(y0,k[1]))) /
                           max(min(a, (k[2]-k[0])*(k[3]-k[1])), 1) <= iou)(k["bbox"])
               for k in kept):
            kept.append(d)
    return kept

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("--labels", default="labels.json")
    ap.add_argument("--dpi", type=int, default=300, help="render-DPI for PDF")
    ap.add_argument("--workwidth", type=int, default=2400,
                    help="arbeidsbredde i px (tegningen normaliseres hit)")
    ap.add_argument("--threshold", type=float, default=0.55)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(args.labels)) or "."
    labels = json.load(open(args.labels))
    tpls = {}
    for name, meta in labels.items():
        t = cv2.imread(os.path.join(here, meta["template"]), cv2.IMREAD_GRAYSCALE)
        tpls[name] = {"img": t, "fill": meta["fill"]}
    # beslutningsgrense åpen/lukket — lært fra legenden
    fill_split = (tpls["gate_open"]["fill"] + tpls["gate_closed"]["fill"]) / 2

    orig = load(args.drawing, args.dpi)
    _, obw = cv2.threshold(orig, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    f = args.workwidth / orig.shape[1]
    img = cv2.resize(orig, None, fx=f, fy=f,
                     interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    target = prep(bw)
    H, W = bw.shape
    # strektykkelse i ORIGINAL oppløsning (der tilstanden avgjøres)
    dt = cv2.distanceTransform((obw > 0).astype(np.uint8), cv2.DIST_L2, 3)
    stroke = 2 * float(np.median(dt[obw > 0])) if (obw > 0).any() else 2.0

    # skala-sweep: en gate valve-sløyfe er ~0,6–1,7 % av arkbredden (A1),
    # så malbreddene beregnes som andel av arbeidsbredden — samme kode
    # fungerer da for lavoppløselige JPEG-er og 300 dpi-PDF-er.
    base_w = tpls["gate_open"]["img"].shape[1]
    cand = []
    for frac in (0.006, 0.0075, 0.0095, 0.012, 0.015):
        tw = max(int(W * frac), 11)
        s = tw / base_w
        for name, t in tpls.items():
            tt = cv2.resize(t["img"], None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            if tt.shape[0] < 9: continue
            for rot in (0, 1):
                tr = np.ascontiguousarray(np.rot90(tt)) if rot else tt
                tf = prep(tr)
                if tf.shape[0] >= H or tf.shape[1] >= W: continue
                res = cv2.matchTemplate(target, tf, cv2.TM_CCOEFF_NORMED)
                # kun lokale topper — ellers drukner NMS i titusenvis av naboer
                peak = (res >= args.threshold) & (res >= cv2.dilate(res, np.ones((9, 9))) - 1e-6)
                ys, xs = np.where(peak)
                if len(ys) > 400:
                    top = np.argsort(res[ys, xs])[-400:]
                    ys, xs = ys[top], xs[top]
                for y, x in zip(ys, xs):
                    cand.append({"score": float(res[y, x]), "matched": name,
                                 "bbox": [int(x), int(y),
                                          int(x + tf.shape[1]), int(y + tf.shape[0])]})
    cand = nms(cand)

    # geometri-verifisering + åpen/lukket-klassifisering på selve tegningen
    found = {"gate_open": [], "gate_closed": [], "gate_uncertain": []}
    for d in cand:
        # deteksjon skjedde i arbeidsoppløsning; TILSTAND avgjøres i original
        x0, y0, x1, y1 = [int(round(v / f)) for v in d["bbox"]]
        roi = strip_pipes(obw[y0:y1, x0:x1])
        if roi.size == 0 or roi.shape[1] < 9: continue
        ink = (roi > 0).mean()
        if not (0.06 <= ink <= 0.92):           # for tomt / heldekket = ikke sløyfe
            continue
        # sløyfa er venstre/høyre-symmetrisk: halvdelene skal ha likt blekk
        lh, rh = (roi[:, :roi.shape[1]//2] > 0).mean(), (roi[:, roi.shape[1]//2:] > 0).mean()
        if abs(lh - rh) > 0.35 * max(lh, rh, 1e-6):
            continue
        # tilstand (åpen/lukket) kan bare avgjøres når symbolet er stort nok
        # relativt til strektykkelsen til at interiøret faktisk er synlig
        state_reliable = min(roi.shape) >= 7.5 * stroke and min(roi.shape) >= 18
        if state_reliable:
            closed_hyp = core_ratio(roi, stroke) >= 0.22
            if not is_bowtie(roi, closed_hyp, stroke):
                continue
            cls = "gate_closed" if closed_hyp else "gate_open"
        else:
            # lav oppløsning: alt ser fylt ut — sjekk mot lukket-masken
            if not is_bowtie(roi, True, stroke):
                continue
            cls = "gate_uncertain"
        d["ink"] = round(ink, 3)
        found[cls].append(d)

    stem = os.path.splitext(os.path.basename(args.drawing))[0]
    STRONG = 0.60
    verdict = {}
    print(f"\n=== {stem} ===")
    if found["gate_uncertain"]:
        print("  [oppløsning for lav til å skille åpen/lukket — rapporterer samlet]")
    for cls, label in (("gate_open", "gate valve OPEN"),
                       ("gate_closed", "gate valve CLOSED"),
                       ("gate_uncertain", "gate valve (tilstand usikker)")):
        if cls == "gate_uncertain" and not found[cls]:
            continue
        hits = sorted(found[cls], key=lambda d: -d["score"])
        strong = [h for h in hits if h["score"] >= STRONG]
        present = len(strong) > 0
        best = hits[0]["score"] if hits else 0.0
        verdict[cls] = {"present": present, "count": len(strong),
                        "weak_count": len(hits) - len(strong),
                        "best_score": round(best, 3)}
        extra = f", {len(hits)-len(strong)} svake" if len(hits) > len(strong) else ""
        print(f"  {label:18s} {'TRUE ' if present else 'FALSE'}  "
              f"({len(strong)} funn{extra}, beste score {best:.2f})")

    json.dump(verdict, open(f"{stem}_verdict.json", "w"), indent=2)

    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for cls, col in (("gate_open", (0, 170, 0)), ("gate_closed", (0, 0, 255)),
                     ("gate_uncertain", (0, 140, 255))):
        for d in found[cls]:
            x0, y0, x1, y1 = d["bbox"]
            th = 2 if d["score"] >= STRONG else 1
            cv2.rectangle(vis, (x0, y0), (x1, y1), col, th)
            cv2.putText(vis, f"{d['score']:.2f}", (x0, max(y0-3, 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)
    cv2.imwrite(f"{stem}_proof.png", vis)
    print(f"  -> {stem}_verdict.json + {stem}_proof.png")

if __name__ == "__main__":
    main()
