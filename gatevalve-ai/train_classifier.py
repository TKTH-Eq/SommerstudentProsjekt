#!/usr/bin/env python3
"""
train_classifier.py — Veiledet trening: HOG-trekk + lineær SVM på de
syntetiske utsnittene. Rapporterer nøyaktighet og forvekslingsmatrise
på et holdt-ut valideringssett, og lagrer modellen (model.joblib).

Bruk:
  python make_synthetic.py --n 800          (først: lag treningsdata)
  python train_classifier.py                (så: tren)
  python train_classifier.py --eval-real dataset   (test på ekte, XML-merkede utsnitt)
"""
import argparse, glob, os
import numpy as np
import cv2
import joblib
from skimage.feature import hog
from sklearn.svm import LinearSVC, SVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

SIZE = 64
CLASSES = ["gate_open", "gate_closed", "ball_valve", "globe_valve",
           "check_valve", "butterfly_valve", "reducer", "other_valve", "background"]

def canonicalize(img):
    """Normaliser: hvitt-på-svart, klipp til blekk-boks, roter til liggende,
    sentrer i fast ramme. Fjerner posisjon-, skala- og rotasjonsvariasjon."""
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if bw.mean() > 127:
        bw = 255 - bw
    # 1) fjern gjennomgående rør/linjer (lange horisontale/vertikale strukturer)
    L = max(bw.shape[1] // 2, 15)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vert  = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    sym = cv2.subtract(bw, cv2.max(horiz, vert))
    sym = cv2.morphologyEx(sym, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # 2) behold komponentene nær midten
    ncc, lab, stats, cent = cv2.connectedComponentsWithStats(sym)
    H0, W0 = sym.shape
    keep = np.zeros_like(sym)
    for i in range(1, ncc):
        if stats[i][4] < 12:
            continue
        cx, cy = cent[i]
        if 0.15 * W0 < cx < 0.85 * W0 and 0.15 * H0 < cy < 0.85 * H0:
            keep[lab == i] = 255
    bw = keep if keep.any() else bw
    ys, xs = np.where(bw > 0)
    if len(ys) > 5:
        bw = bw[ys.min():ys.max()+1, xs.min():xs.max()+1]
    if bw.shape[0] > bw.shape[1]:           # stående -> liggende
        bw = np.ascontiguousarray(np.rot90(bw))
    h, w = bw.shape
    s = (SIZE - 8) / max(h, w)
    bw = cv2.resize(bw, (max(int(w*s), 1), max(int(h*s), 1)),
                    interpolation=cv2.INTER_AREA)
    out = np.zeros((SIZE, SIZE), np.uint8)
    oy, ox = (SIZE - bw.shape[0]) // 2, (SIZE - bw.shape[1]) // 2
    out[oy:oy+bw.shape[0], ox:ox+bw.shape[1]] = bw
    _, out = cv2.threshold(out, 60, 255, cv2.THRESH_BINARY)
    return out

def features(img):
    bw = canonicalize(img)
    return hog(bw, orientations=9, pixels_per_cell=(8, 8),
               cells_per_block=(2, 2), feature_vector=True)

def load_dir(root, mapping=None):
    X, y, srcs = [], [], []
    for cls in sorted(os.listdir(root)):
        label = (mapping or {}).get(cls, cls if cls in CLASSES else None)
        if label is None:
            continue
        for fp in glob.glob(os.path.join(root, cls, "*.png")):
            img = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            if img is None: continue
            X.append(features(img)); y.append(label)
            srcs.append(os.path.basename(fp).split("_")[0])
    return np.array(X), np.array(y), np.array(srcs)

def isolate_native(img):
    """Isoler symbolet i NATIV oppløsning: fjern gjennomgående linjer,
    behold komponentene nær midten. (Ingen resize -> ærlig strektykkelse.)"""
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if bw.mean() > 127: bw = 255 - bw
    L = max(bw.shape[1] // 2, 15)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vert  = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    sym = cv2.subtract(bw, cv2.max(horiz, vert))
    sym = cv2.morphologyEx(sym, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    ncc, lab, stats, cent = cv2.connectedComponentsWithStats(sym)
    H0, W0 = sym.shape
    keep = np.zeros_like(sym)
    for i in range(1, ncc):
        if stats[i][4] < 12: continue
        cx, cy = cent[i]
        if 0.15 * W0 < cx < 0.85 * W0 and 0.15 * H0 < cy < 0.85 * H0:
            keep[lab == i] = 255
    return keep if keep.any() else bw

def pseudo_state(img):
    """Auto-merk ekte GateValve-utsnitt som open/closed via trekantmaske-
    fyllgrad (samme diskriminator som validert feilfri på legendene):
    fylt sløyfe fyller trekantene tett, omriss gjør det ikke."""
    sym = isolate_native(img)
    ys, xs = np.where(sym > 0)
    if len(ys) < 12: return "gate_open"
    roi = sym[ys.min():ys.max()+1, xs.min():xs.max()+1]
    if roi.shape[0] > roi.shape[1]:
        roi = np.ascontiguousarray(np.rot90(roi))
    Hh, Ww = roi.shape
    yy, xx = np.mgrid[0:Hh, 0:Ww]
    dx = np.abs(xx - (Ww - 1) / 2) / max((Ww - 1) / 2, 1)
    dy = np.abs(yy - (Hh - 1) / 2) / max((Hh - 1) / 2, 1)
    mask = dy <= dx + 0.10
    fillgrad = ((roi > 0) & mask).sum() / max(mask.sum(), 1)
    return "gate_closed" if fillgrad >= 0.40 else "gate_open"

# Ekte klasser -> treningsklasser. Flenser/reduserere = harde negativer.
REAL_MAP = {"BallValve": "ball_valve", "GlobeValve": "globe_valve",
            "CheckValve": "check_valve", "ButterflyValve": "butterfly_valve",
            "NeedleValve": "other_valve", "PlugValve": "other_valve",
            "AngleValve": "other_valve", "Background": "background",
            "HardNegative": "background",
            "FlangedConnection": "background", "PipeReducer": "reducer"}

def load_real(root):
    X, y, srcs, gate_log = [], [], [], []
    for cls in sorted(os.listdir(root)):
        d = os.path.join(root, cls)
        if not os.path.isdir(d) or cls == "yolo":
            continue
        for fp in glob.glob(os.path.join(d, "*.png")):
            img = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            if img is None: continue
            if cls == "GateValve":
                label = pseudo_state(img)
                gate_log.append((os.path.basename(fp), label))
            else:
                label = REAL_MAP.get(cls)
                if label is None: continue
            X.append(features(img)); y.append(label)
            srcs.append(os.path.basename(fp).split("_")[0])
    if gate_log:
        with open(os.path.join(root, "gate_state_pseudolabels.csv"), "w", encoding="utf-8") as f:
            f.write("fil,pseudo_state\n")
            for n, l in gate_log: f.write(f"{n},{l}\n")
    return np.array(X), np.array(y), np.array(srcs), gate_log

def report(tag, ytrue, ypred, labels):
    print(f"\n=== {tag} (n={len(ytrue)}) ===")
    print(f"  nøyaktighet: {accuracy_score(ytrue, ypred):.3f}")
    cm = confusion_matrix(ytrue, ypred, labels=labels)
    w = max(len(l) for l in labels)
    print("  forveksling (rader=fasit):")
    print("  " + " " * w + "  " + "  ".join(f"{l[:6]:>6}" for l in labels))
    for l, row in zip(labels, cm):
        print(f"  {l:<{w}}  " + "  ".join(f"{v:6d}" for v in row))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", default="synth")
    ap.add_argument("--real", default=None,
                    help="dataset-mappe fra make_dataset_batch.py — blandes inn i TRENINGEN")
    ap.add_argument("--holdout-sources", type=int, default=3,
                    help="antall tegninger som holdes helt utenfor trening (ekte test)")
    ap.add_argument("--eval-real", default=None, help="(bakoverkompatibel) kun evaluering")
    ap.add_argument("--model", default="model.joblib")
    args = ap.parse_args()

    print("[+] leser syntetiske treningsdata ...")
    Xs, ys, _ = load_dir(args.synth)
    print(f"    {len(ys)} syntetiske eksempler")
    Xtr, Xva, ytr, yva = train_test_split(Xs, ys, test_size=0.2, random_state=0, stratify=ys)
    Xtr, ytr = list(Xtr), list(ytr)

    Xte_r, yte_r = None, None
    if args.real and os.path.isdir(args.real):
        print("[+] leser EKTE data (XML-merket) ...")
        Xr, yr, sr, gate_log = load_real(args.real)
        from collections import Counter
        print(f"    {len(yr)} ekte eksempler fra {len(set(sr))} tegninger: {dict(Counter(yr))}")
        if gate_log:
            gl = Counter(l for _, l in gate_log)
            print(f"    GateValve pseudo-merket: {dict(gl)}  "
                  f"(-> {args.real}/gate_state_pseudolabels.csv — kontroller gjerne)")
        # holdout per TEGNING: modellen testes aldri på ark den har trent på
        uniq = sorted(set(sr))
        rng = np.random.default_rng(0)
        hold = set(rng.choice(uniq, size=min(args.holdout_sources, max(len(uniq)-1, 1)),
                              replace=False))
        mask = np.array([s in hold for s in sr])
        Xtr += list(Xr[~mask]); ytr += list(yr[~mask])
        Xte_r, yte_r = Xr[mask], yr[mask]
        print(f"    holdout-tegninger (ekte test): {sorted(hold)}  ({mask.sum()} utsnitt)")

    print(f"[+] trener HOG + RBF-SVM på {len(ytr)} eksempler ...")
    base = SVC(kernel="rbf", C=8, gamma="scale")
    clf = CalibratedClassifierCV(base, cv=3, ensemble=False)
    clf.fit(np.array(Xtr), np.array(ytr))

    labels = sorted(set(ys))
    report("VALIDERING syntetisk holdt-ut", yva, clf.predict(Xva), labels)

    # foreslåtte konfidens-terskler: 25-persentil av maks-p på KORREKTE val-treff
    proba = clf.predict_proba(Xva)
    pred = np.array(labels)[np.argmax(proba, axis=1)]
    mx = proba.max(axis=1)
    suggested = {}
    for l in labels:
        ok = (pred == l) & (np.array(yva) == l)
        q = float(np.percentile(mx[ok], 25)) if ok.sum() >= 5 else 0.5
        suggested[l] = round(min(max(q, 0.40), 0.75), 3)
    print(f"  foreslåtte terskler: {suggested}")
    if Xte_r is not None and len(yte_r):
        report("EKTE holdout-tegninger", yte_r, clf.predict(Xte_r), labels)

    joblib.dump({"clf": clf, "classes": labels, "suggested_conf": suggested}, args.model)
    print(f"\n[✓] modell lagret -> {args.model}")

    if args.eval_real and os.path.isdir(args.eval_real) and not args.real:
        Xr, yr, _, _ = load_real(args.eval_real)
        if len(yr):
            report("EKTE DATA (kun evaluering)", yr, clf.predict(Xr), labels)

if __name__ == "__main__":
    main()