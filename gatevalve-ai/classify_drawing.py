#!/usr/bin/env python3
"""
classify_drawing.py — Som check_drawing.py, men klassifiseringen gjøres av
den TRENTE modellen (model.joblib) i stedet for håndlagde geometriregler.

Flyt: kandidater (malmatch-sweep) -> utsnitt i ORIGINAL oppløsning
      -> HOG + SVM -> TRUE/FALSE per klasse + proof-bilde.

Bruk:
  python classify_drawing.py tegning.pdf --dpi 200
  python classify_drawing.py tegning.jpg
"""
import argparse, json, os, sys
import numpy as np
import cv2
import joblib
from train_classifier import features   # samme representasjon som i trening

def load(path, dpi, mask_text=True):
    """Les tegning. For PDF: bruk tekstlaget til å VISKE UT all tekst før
    deteksjon — tekst kan da aldri bli feilklassifisert som ventil."""
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(path)[0].render(scale=dpi / 72.0).to_numpy()
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY if img.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
        if mask_text:
            try:
                import pdfplumber
                s = dpi / 72.0
                n = 0
                with pdfplumber.open(path) as pdf:
                    for w in pdf.pages[0].extract_words():
                        x0 = max(int((w["x0"] - 1) * s), 0)
                        x1 = min(int((w["x1"] + 1) * s), img.shape[1])
                        y0 = max(int((w["top"] - 1) * s), 0)
                        y1 = min(int((w["bottom"] + 1) * s), img.shape[0])
                        img[y0:y1, x0:x1] = 255; n += 1
                print(f"  [tekstmaske: {n} ord visket ut fra PDF-tekstlaget]")
            except Exception as e:
                print(f"  [tekstmaske hoppet over: {e}]")
        return img
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: sys.exit(f"kunne ikke lese {path}")
    return img

def detect_content_box(bw):
    """Finn tegningens innholdsområde automatisk: ytterramme = lange
    gjennomgående linjer; tittelfelt/revisjonstabell = øverste lange
    horisontale linje i nedre band. Alt utenfor maskeres."""
    H, W = bw.shape
    rows = (bw > 0).mean(axis=1)
    cols = (bw > 0).mean(axis=0)
    long_h = np.where(rows > 0.55)[0]
    long_v = np.where(cols > 0.55)[0]
    x0 = int(long_v[long_v < W * 0.10].max() + 2) if (long_v < W * 0.10).any() else int(W * 0.03)
    x1 = int(long_v[long_v > W * 0.90].min() - 2) if (long_v > W * 0.90).any() else int(W * 0.97)
    y0 = int(long_h[long_h < H * 0.08].max() + 2) if (long_h < H * 0.08).any() else int(H * 0.02)
    band = long_h[(long_h > H * 0.82) & (long_h < H * 0.995)]
    y1 = int(band.min() - 2) if len(band) >= 2 else int(H * 0.86)
    return x0, y0, x1, y1

def prep(bw):
    return cv2.GaussianBlur(bw.astype(np.float32) / 255.0, (3, 3), 0)

def strip_pipes(r):
    while r.shape[0] > 6 and (r[0] > 0).mean() > 0.85:  r = r[1:]
    while r.shape[0] > 6 and (r[-1] > 0).mean() > 0.85: r = r[:-1]
    while r.shape[1] > 8 and (r[:, 0] > 0).mean() > 0.85:  r = r[:, 1:]
    while r.shape[1] > 8 and (r[:, -1] > 0).mean() > 0.85: r = r[:, :-1]
    return r

def gate_mask_ok(roi, closed, stroke):
    """Streng geometrisk verifisering for gate-klassene (fra check_drawing,
    validert feilfri på legendene)."""
    Hh, Ww = roi.shape
    if Ww < 10 or Hh < 6: return False
    ink = roi > 0
    n_ink = int(ink.sum())
    if n_ink < 12: return False
    lh, rh = ink[:, :Ww//2].mean(), ink[:, Ww//2:].mean()
    if abs(lh - rh) > 0.35 * max(lh, rh, 1e-6): return False
    ncc, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8))
    span = max((stats[i][2] for i in range(1, ncc)), default=0)
    if span < 0.82 * Ww: return False
    th = max(int(round(stroke * 1.8)), 2)
    if closed:
        yy, xx = np.mgrid[0:Hh, 0:Ww]
        dx = np.abs(xx - (Ww-1)/2) / max((Ww-1)/2, 1)
        dy = np.abs(yy - (Hh-1)/2) / max((Hh-1)/2, 1)
        mask = dy <= dx + (th / Hh)
        if (ink & mask).sum() / n_ink < 0.85: return False
        if (ink & mask).sum() / max(mask.sum(), 1) < 0.45: return False
        cols = ink.sum(axis=0).astype(np.float32)
        kk = max(Ww // 14, 1)
        cols = np.convolve(cols, np.ones(2*kk+1)/(2*kk+1), mode="same")
        e = max(int(Ww * 0.16), 2)
        hL, hR = cols[:e].max(), cols[-e:].max(); hi = max(hL, hR)
        if min(hL, hR) < 0.60 * Hh or abs(hL - hR) > 0.30 * hi: return False
        for q in (0.25, 0.75):
            r = cols[int(Ww*q)] / max(hi, 1)
            if not (0.28 <= r <= 0.80): return False
        return True
    m = np.zeros((Hh, Ww), np.uint8)
    cv2.line(m, (0, 0), (Ww-1, Hh-1), 1, th); cv2.line(m, (0, Hh-1), (Ww-1, 0), 1, th)
    cv2.line(m, (0, 0), (0, Hh-1), 1, th);    cv2.line(m, (Ww-1, 0), (Ww-1, Hh-1), 1, th)
    on = (ink & (m > 0)).sum()
    return on / n_ink >= 0.70 and on / max(int(m.sum()), 1) >= 0.28

def nms(dets, iou=0.35):
    dets = sorted(dets, key=lambda d: -d["score"]); kept = []
    for d in dets:
        x0, y0, x1, y1 = d["bbox"]; a = (x1-x0)*(y1-y0)
        ok = True
        for k in kept:
            kx0, ky0, kx1, ky1 = k["bbox"]
            iw = max(0, min(x1, kx1) - max(x0, kx0))
            ih = max(0, min(y1, ky1) - max(y0, ky0))
            if iw * ih / max(min(a, (kx1-kx0)*(ky1-ky0)), 1) > iou:
                ok = False; break
        if ok: kept.append(d)
    return kept

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drawing")
    ap.add_argument("--model", default="model.joblib")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--workwidth", type=int, default=2400)
    ap.add_argument("--cand-threshold", type=float, default=0.50)
    ap.add_argument("--out-dir", default="results",
                    help="mappe for verdict/proof/detections (lages automatisk)")
    ap.add_argument("--dump-detections", action="store_true",
                    help="skriv alle funn (alle klasser, orig-koordinater) til <navn>_detections.json")
    ap.add_argument("--only-gates", action="store_true",
                    help="rapporter kun gate valve open/closed")
    ap.add_argument("--keep-text", action="store_true",
                    help="ikke visk ut tekst fra PDF-tekstlaget")
    ap.add_argument("--full-sheet", action="store_true",
                    help="ikke masker marger/tittelfelt (søk hele arket)")
    ap.add_argument("--mode", choices=["recall", "precision"], default="recall",
                    help="recall: finn mest mulig (standard). precision: geometrisk portvakt, få men sikre")
    ap.add_argument("--min-conf", type=float, default=None,
                    help="overstyr terskel; standard = modellens egne kalibrerte terskler")
    ap.add_argument("--verifiers", default="non_gate_verifiers.pt",
                    help="binære andretrinnsmodeller for ball/globe/check/butterfly; tom streng slår av")
    ap.add_argument("--no-non-gate-verifier", action="store_true",
                    help="slå av andretrinnsverifisering (nyttig under hard-negative mining)")
    args = ap.parse_args()

    if args.model.endswith(".pt"):
        import torch
        from train_cnn import build_net
        from train_classifier import canonicalize
        ck = torch.load(args.model, map_location="cpu")
        classes = ck["classes"]
        net = build_net(len(classes)); net.load_state_dict(ck["state_dict"]); net.eval()
        suggested = ck.get("suggested_conf", {})
        def canonical_tensor(crop):
            x = canonicalize(crop)[None, None].astype(np.float32) / 255.0
            return torch.tensor(x)
        def predict_proba_one(crop):
            with torch.no_grad():
                return net(canonical_tensor(crop)).softmax(1).numpy()[0]
        print(f"  [modell: CNN ({args.model})]")
    else:
        m = joblib.load(args.model)
        clf, classes = m["clf"], m["classes"]
        suggested = m.get("suggested_conf", {})
        def predict_proba_one(crop):
            return clf.predict_proba([features(crop)])[0]
    def thr_for(cls):
        base = args.min_conf if args.min_conf is not None else suggested.get(cls, 0.5)
        return base + (0.10 if cls == "other_valve" else 0.0)   # SVM alene -> strengere

    # Andretrinnet er helt separat fra gate-modellen. Gate open/closed går
    # aldri gjennom disse verifikatorene, så gate-resultatene endres ikke.
    here = os.path.dirname(os.path.abspath(__file__))
    verifier_nets, verifier_thresholds = {}, {}
    if args.model.endswith(".pt") and args.verifiers and not args.no_non_gate_verifier:
        vp = args.verifiers
        if not os.path.isabs(vp):
            local = os.path.join(here, vp)
            vp = local if os.path.exists(local) else vp
        if os.path.exists(vp):
            vck = torch.load(vp, map_location="cpu")
            verifier_thresholds = vck.get("thresholds", {})
            for cls, state in vck.get("state_dicts", {}).items():
                vn = build_net(2); vn.load_state_dict(state); vn.eval()
                verifier_nets[cls] = vn
            print(f"  [andretrinn: {len(verifier_nets)} ikke-gate-verifikatorer ({os.path.basename(vp)})]")
        else:
            print(f"  [andretrinn: ingen fil {vp!r}; kjører bare hovedmodellen]")

    def verify_non_gate(cls, crop):
        """Returner (godkjent, sannsynlighet, terskel). Kun ikke-gate."""
        vn = verifier_nets.get(cls)
        if vn is None:
            return True, None, None
        with torch.no_grad():
            p = float(vn(canonical_tensor(crop)).softmax(1).numpy()[0, 1])
        t = float(verifier_thresholds.get(cls, 0.80))
        return p >= t, p, t
    cand_files = ["gate_open.png", "gate_closed.png",
                  "cand_ball.png", "cand_globe.png", "cand_check.png", "cand_butterfly.png", "cand_reducer.png"]
    tpls = []
    for fn in cand_files:
        t = cv2.imread(os.path.join(here, fn), 0)
        if t is not None:
            tpls.append(t)
    print(f"  [kandidat-prototyper: {len(tpls)} ({', '.join(f for f in cand_files if cv2.imread(os.path.join(here, f), 0) is not None)})]")

    orig = load(args.drawing, args.dpi, mask_text=not args.keep_text)
    _, obw_full = cv2.threshold(orig, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if not args.full_sheet:
        cx0, cy0, cx1, cy1 = detect_content_box(obw_full)
        orig = orig.copy()
        orig[:cy0, :] = 255; orig[cy1:, :] = 255
        orig[:, :cx0] = 255; orig[:, cx1:] = 255
        _, obw_full = cv2.threshold(orig, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        H0, W0 = orig.shape
        print(f"  [innholdsboks: x {cx0/W0:.0%}–{cx1/W0:.0%}, y {cy0/H0:.0%}–{cy1/H0:.0%} — marg og tittelfelt maskert]")
    dtt = cv2.distanceTransform((obw_full > 0).astype(np.uint8), cv2.DIST_L2, 3)
    stroke = 2 * float(np.median(dtt[obw_full > 0])) if (obw_full > 0).any() else 2.0
    f = args.workwidth / orig.shape[1]
    work = cv2.resize(orig, None, fx=f, fy=f,
                      interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    _, wbw = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    target = prep(wbw); H, W = wbw.shape

    cand = []
    for frac in (0.006, 0.0075, 0.0095, 0.012, 0.015):
        tw = max(int(W * frac), 11)
        for t in tpls:
            tt = cv2.resize(t, None, fx=tw / t.shape[1], fy=tw / t.shape[1],
                            interpolation=cv2.INTER_AREA)
            for rot in (0, 1):
                tr = np.ascontiguousarray(np.rot90(tt)) if rot else tt
                tf = prep(tr)
                if tf.shape[0] >= H or tf.shape[1] >= W: continue
                res = cv2.matchTemplate(target, tf, cv2.TM_CCOEFF_NORMED)
                pk = (res >= args.cand_threshold) & (res >= cv2.dilate(res, np.ones((9, 9))) - 1e-6)
                ys, xs = np.where(pk)
                if len(ys) > 400:
                    top = np.argsort(res[ys, xs])[-400:]; ys, xs = ys[top], xs[top]
                for y, x in zip(ys, xs):
                    cand.append({"score": float(res[y, x]),
                                 "bbox": [int(x), int(y), int(x+tf.shape[1]), int(y+tf.shape[0])]})
    cand = nms(cand)

    counts = {c: [] for c in classes}
    pad = 0.35
    for d in cand:
        x0, y0, x1, y1 = [v / f for v in d["bbox"]]
        w, h = x1 - x0, y1 - y0
        a0, b0 = int(max(x0 - pad*w, 0)), int(max(y0 - pad*h, 0))
        a1, b1 = int(min(x1 + pad*w, orig.shape[1])), int(min(y1 + pad*h, orig.shape[0]))
        crop = orig[b0:b1, a0:a1]
        if crop.size == 0: continue
        proba = predict_proba_one(crop)
        i = int(np.argmax(proba))
        d["cls"], d["conf"] = classes[i], float(proba[i])
        if d["cls"] == "background":
            continue

        # Binær class-vs-rest-verifikasjon for de nye ventilklassene.
        # Dette stopper f.eks. en reducer som hoved-CNN-en kaller ball valve
        # med høy softmax. Gate-klassene hoppes eksplisitt over.
        if d["cls"] not in ("gate_open", "gate_closed", "other_valve"):
            accepted, vconf, vthr = verify_non_gate(d["cls"], crop)
            if vconf is not None:
                d["verifier_conf"], d["verifier_threshold"] = vconf, vthr
            if not accepted:
                continue

        if args.mode == "recall":
            if args.min_conf is not None:
                if d["conf"] < args.min_conf:
                    continue
                d["tier"] = "sikker"
            else:
                strong = suggested.get(d["cls"], 0.50)
                if d["conf"] >= strong:
                    d["tier"] = "sikker"
                elif d["conf"] >= 0.55:
                    d["tier"] = "mulig"
                else:
                    continue
            # lett sanity (uten streng geometri): sløyfer er alltid
            # venstre/høyre-symmetriske og verken tomme eller heldekkede
            gx0, gy0, gx1, gy1 = [int(v / f) for v in d["bbox"]]
            roi = strip_pipes(obw_full[gy0:gy1, gx0:gx1])
            if roi.size == 0 or roi.shape[1] < 8:
                continue
            ink = (roi > 0).mean()
            if not (0.06 <= ink <= 0.92):
                continue
            lh = (roi[:, :roi.shape[1]//2] > 0).mean()
            rh = (roi[:, roi.shape[1]//2:] > 0).mean()
            if abs(lh - rh) > 0.35 * max(lh, rh, 1e-6):
                continue
        else:
            if d["conf"] < thr_for(d["cls"]):
                continue
            # PORTVAKT: gate-klassene må også bestå streng geometri
            if d["cls"] in ("gate_open", "gate_closed"):
                gx0, gy0, gx1, gy1 = [int(v / f) for v in d["bbox"]]
                roi = strip_pipes(obw_full[gy0:gy1, gx0:gx1])
                if roi.size == 0 or not gate_mask_ok(roi, d["cls"] == "gate_closed", stroke):
                    continue

        counts[d["cls"]].append(d)

    # DEDUP per klasse: maler i ulik skala/rotasjon kan gi 2-3 bokser på
    # samme symbol — behold beste konfidens, fjern senter-nære naboer
    for cls, lst in counts.items():
        lst.sort(key=lambda d: -d["conf"])
        kept = []
        for d in lst:
            x0, y0, x1, y1 = d["bbox"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            s = max(x1 - x0, y1 - y0)
            dup = False
            for k in kept:
                kx0, ky0, kx1, ky1 = k["bbox"]
                ks = max(kx1 - kx0, ky1 - ky0)
                if (abs(cx - (kx0 + kx1) / 2) < 0.6 * max(s, ks) and
                        abs(cy - (ky0 + ky1) / 2) < 0.6 * max(s, ks)):
                    dup = True
                    break
            if not dup:
                kept.append(d)
        counts[cls] = kept

    stem = os.path.splitext(os.path.basename(args.drawing))[0]
    os.makedirs(args.out_dir, exist_ok=True)
    def outp(name):
        return os.path.join(args.out_dir, name)
    verdict = {}
    print(f"\n=== {stem} (lært modell, modus: {args.mode}) ===")
    all_classes = tuple(c for c in classes if c != "background")
    report_classes = ("gate_open", "gate_closed") if args.only_gates else all_classes
    for cls in report_classes:
        hits = counts.get(cls, [])
        strong = [h for h in hits if h.get("tier", "sikker") == "sikker"]
        weak = [h for h in hits if h.get("tier") == "mulig"]
        present = len(hits) > 0
        best = max((h["conf"] for h in hits), default=0.0)
        verdict[cls] = {"present": present, "confident": len(strong),
                        "possible": len(weak), "best_conf": round(best, 3)}
        label = {"gate_open": "gate valve OPEN", "gate_closed": "gate valve CLOSED",
                 "ball_valve": "ball valve", "globe_valve": "globe valve",
                 "check_valve": "check valve", "butterfly_valve": "butterfly valve",
                 "reducer": "reducer", "other_valve": "andre ventiler"}.get(cls, cls)
        extra = f" + {len(weak)} mulige" if weak else ""
        print(f"  {label:18s} {'TRUE ' if present else 'FALSE'}  "
              f"({len(strong)} sikre{extra}, beste konfidens {best:.2f})")
    json.dump(verdict, open(outp(f"{stem}_verdict.json"), "w"), indent=2)
    if args.dump_detections:
        dump = []
        for cls, lst in counts.items():
            for d in lst:
                x0, y0, x1, y1 = [int(round(v / f)) for v in d["bbox"]]
                item = {"cls": cls, "conf": round(d["conf"], 3),
                        "tier": d.get("tier", "sikker"),
                        "bbox_orig": [x0, y0, x1, y1]}
                if d.get("verifier_conf") is not None:
                    item["verifier_conf"] = round(d["verifier_conf"], 3)
                    item["verifier_threshold"] = round(d["verifier_threshold"], 3)
                dump.append(item)
        json.dump(dump, open(outp(f"{stem}_detections.json"), "w"), indent=2)
        print(f"  -> {args.out_dir}/{stem}_detections.json ({len(dump)} funn)")

    vis = cv2.cvtColor(work, cv2.COLOR_GRAY2BGR)
    cols = {"gate_open": (0, 170, 0), "gate_closed": (0, 0, 255),
            "ball_valve": (0, 140, 255), "globe_valve": (200, 0, 200),
            "check_valve": (180, 180, 0), "butterfly_valve": (255, 0, 120),
            "reducer": (19, 69, 139), "other_valve": (200, 120, 0)}
    for cls, col in cols.items():
        if cls not in report_classes:
            continue
        for d in counts.get(cls, []):
            x0, y0, x1, y1 = d["bbox"]
            th = 2 if d.get("tier", "sikker") == "sikker" else 1
            cv2.rectangle(vis, (x0, y0), (x1, y1), col, th)
            score_txt = f"{d['conf']:.2f}"
            if d.get("verifier_conf") is not None:
                score_txt += f"/{d['verifier_conf']:.2f}"
            cv2.putText(vis, score_txt, (x0, max(y0-3, 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)
    cv2.imwrite(outp(f"{stem}_proof.png"), vis)
    print(f"  -> {args.out_dir}/{stem}_verdict.json + {stem}_proof.png")

if __name__ == "__main__":
    main()