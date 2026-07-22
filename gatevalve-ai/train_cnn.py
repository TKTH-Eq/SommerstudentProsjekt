#!/usr/bin/env python3
"""
train_cnn.py — Steg C: liten CNN i stedet for HOG+SVM.

Gjenbruker HELE den validerte datarørledningen fra train_classifier.py
(canonicalize-forbehandling, pseudo-merking av gate-tilstand, ekte-klasse-
mapping, holdout per tegning) — kun selve modellen byttes.

Krever PyTorch (kun for trening/inferens, CPU holder):
  pip install torch --index-url https://download.pytorch.org/whl/cpu

Bruk:
  py train_cnn.py --real dataset                (synth/ + ekte data)
  py train_cnn.py --real dataset --epochs 20
Ut:
  model_cnn.pt   (arkitektur + vekter + klasser + foreslåtte terskler)
Deretter:
  py classify_drawing.py tegning.pdf --dpi 200 --model model_cnn.pt --only-gates
"""
import argparse, glob, os
import numpy as np
import cv2

# Gjenbruk validert forbehandling og merkelogikk
from train_classifier import canonicalize, pseudo_state, REAL_MAP, CLASSES, SIZE


# ---------------------------------------------------------------- data
def load_folder_as_images(root, mapping=None):
    """Som train_classifier.load_dir, men returnerer BILDER (canonicalized),
    ikke HOG-vektorer."""
    X, y, srcs = [], [], []
    for cls in sorted(os.listdir(root)):
        label = (mapping or {}).get(cls, cls if cls in CLASSES else None)
        if label is None:
            continue
        for fp in glob.glob(os.path.join(root, cls, "*.png")):
            img = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            X.append(canonicalize(img))
            y.append(label)
            srcs.append(os.path.basename(fp).split("_")[0])
    return X, y, srcs


def load_real_as_images(root):
    X, y, srcs = [], [], []
    gate_log = []
    for cls in sorted(os.listdir(root)):
        d = os.path.join(root, cls)
        if not os.path.isdir(d) or cls == "yolo":
            continue
        for fp in glob.glob(os.path.join(d, "*.png")):
            img = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if cls == "GateValve":
                label = pseudo_state(img)
                gate_log.append((os.path.basename(fp), label))
            else:
                label = REAL_MAP.get(cls)
                if label is None:
                    continue
            X.append(canonicalize(img))
            y.append(label)
            srcs.append(os.path.basename(fp).split("_")[0])
    return X, y, srcs, gate_log


def load_all_data(synth_dir, real_dir, holdout_sources=3, seed=0, holdout_list=None):
    """Returnerer (Xtr, ytr, Xva, yva, Xte, yte, labels, info) som numpy.
    Testbar uten torch."""
    Xs, ys, _ = load_folder_as_images(synth_dir)
    labels = sorted(set(ys))
    li = {l: i for i, l in enumerate(labels)}

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(ys))
    n_va = max(int(len(ys) * 0.2), 1)
    va_i, tr_i = set(idx[:n_va].tolist()), idx[n_va:]
    Xtr = [Xs[i] for i in tr_i]; ytr = [li[ys[i]] for i in tr_i]
    Xva = [Xs[i] for i in sorted(va_i)]; yva = [li[ys[i]] for i in sorted(va_i)]

    Xte, yte, info = [], [], {}
    if real_dir and os.path.isdir(real_dir):
        Xr, yr, sr, gate_log = load_real_as_images(real_dir)
        from collections import Counter
        info["real_counts"] = dict(Counter(yr))
        info["pseudo"] = dict(Counter(l for _, l in gate_log))
        uniq = sorted(set(sr))
        if holdout_list:
            hold = {h.strip() for h in holdout_list.split(",") if h.strip()}
            missing = hold - set(uniq)
            if missing:
                print(f"    [!] holdout-navn ikke i data: {sorted(missing)}")
            hold &= set(uniq)
        else:
            # egen, stabil trekning — uavhengig av datamengde ellers
            hrng = np.random.default_rng(42)
            hold = set(hrng.choice(uniq, size=min(holdout_sources, max(len(uniq) - 1, 1)),
                                   replace=False).tolist())
        info["holdout"] = sorted(hold)
        # dynamisk oversampling: små ekte klasser dupliseres mot ~180 eksempler
        from collections import Counter as _C
        tr_counts = _C(l for l, s in zip(yr, sr) if s not in hold)
        dup = {l: min(max(int(round(180 / max(n, 1))), 1), 6)
               for l, n in tr_counts.items() if l not in ("background",)}
        for x, l, s in zip(Xr, yr, sr):
            if s in hold:
                Xte.append(x); yte.append(li[l])
            else:
                for _ in range(dup.get(l, 1)):
                    Xtr.append(x); ytr.append(li[l])
        if dup:
            print(f"    oversampling (ekte): { {k: v for k, v in dup.items() if v > 1} }")

    def to_arr(X):  # (N,1,64,64) float32 i [0,1]
        return (np.stack(X)[:, None, :, :].astype(np.float32) / 255.0) if X else np.zeros((0, 1, SIZE, SIZE), np.float32)

    return (to_arr(Xtr), np.array(ytr), to_arr(Xva), np.array(yva),
            to_arr(Xte), np.array(yte), labels, info)


def augment_batch(xb, rng):
    """Lett augmentering: små forskyvninger (symbolene er alt kanonisert)."""
    out = xb.copy()
    for i in range(out.shape[0]):
        dx, dy = int(rng.integers(-2, 3)), int(rng.integers(-2, 3))
        out[i, 0] = np.roll(np.roll(out[i, 0], dy, axis=0), dx, axis=1)
    return out


# ---------------------------------------------------------------- modell
def build_net(n_classes):
    """Liten CNN for 1x64x64 kanoniserte symbolutsnitt. Delt mellom
    trening (train_cnn) og inferens (classify_drawing)."""
    import torch.nn as nn
    return nn.Sequential(
        nn.Conv2d(1, 16, 3, padding=1), nn.BatchNorm2d(16), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(16, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
        nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.3),
        nn.Linear(64, n_classes),
    )


# ---------------------------------------------------------------- trening
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", default="synth")
    ap.add_argument("--real", default=None)
    ap.add_argument("--holdout-sources", type=int, default=3)
    ap.add_argument("--holdout-list", default=None,
                    help="pin holdout eksplisitt, f.eks. 25VHO64PU00101,25VHO71PW00101,25WHO71PW00101")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--model", default="model_cnn.pt")
    args = ap.parse_args()

    print("[+] laster data (samme rørledning som HOG+SVM) ...")
    Xtr, ytr, Xva, yva, Xte, yte, labels, info = load_all_data(
        args.synth, args.real, args.holdout_sources, holdout_list=args.holdout_list)
    print(f"    trening: {len(ytr)}  validering: {len(yva)}  "
          f"ekte holdout: {len(yte)}  klasser: {labels}")
    if "pseudo" in info:
        print(f"    GateValve pseudo-merket: {info['pseudo']}")
        print(f"    holdout-tegninger: {info.get('holdout')}")

    import torch
    import torch.nn as nn
    torch.manual_seed(0)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[+] trener CNN på {dev} ...")
    net = build_net(len(labels)).to(dev)

    # klassevekter mot ubalanse
    cnt = np.bincount(ytr, minlength=len(labels)).astype(np.float32)
    w = torch.tensor(cnt.sum() / (len(labels) * np.maximum(cnt, 1)), device=dev)
    lossf = nn.CrossEntropyLoss(weight=w)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    tva = torch.tensor(Xva, device=dev)
    yva_t = torch.tensor(yva, device=dev)
    rng = np.random.default_rng(1)
    best_va, best_state = 0.0, None

    for ep in range(1, args.epochs + 1):
        net.train()
        idx = rng.permutation(len(ytr))
        tot = 0.0
        for b in range(0, len(idx), args.batch):
            bi = idx[b:b + args.batch]
            xb = augment_batch(Xtr[bi], rng)
            xb = torch.tensor(xb, device=dev)
            yb = torch.tensor(ytr[bi], device=dev)
            opt.zero_grad()
            out = net(xb)
            loss = lossf(out, yb)
            loss.backward(); opt.step()
            tot += float(loss.detach()) * len(bi)
        sched.step()
        net.eval()
        with torch.no_grad():
            acc = float((net(tva).argmax(1) == yva_t).float().mean())
        print(f"    epoke {ep:2d}: tap {tot/len(idx):.3f}  val-nøyaktighet {acc:.3f}")
        if acc > best_va:
            best_va = acc
            best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}

    net.load_state_dict(best_state)
    net.eval()

    def report(tag, X, y):
        if not len(y):
            return None
        with torch.no_grad():
            pr = net(torch.tensor(X, device=dev)).softmax(1).cpu().numpy()
        pred = pr.argmax(1)
        acc = float((pred == y).mean())
        print(f"\n=== {tag} (n={len(y)}) ===\n  nøyaktighet: {acc:.3f}")
        w0 = max(len(l) for l in labels)
        print("  forveksling (rader=fasit):")
        print("  " + " " * w0 + "  " + "  ".join(f"{l[:6]:>6}" for l in labels))
        for i, l in enumerate(labels):
            row = [int(((y == i) & (pred == j)).sum()) for j in range(len(labels))]
            print(f"  {l:<{w0}}  " + "  ".join(f"{v:6d}" for v in row))
        return pr, pred

    pr_va, pred_va = report("VALIDERING syntetisk holdt-ut", Xva, yva)
    report("EKTE holdout-tegninger", Xte, yte)

    # foreslåtte terskler: 25-persentil av softmax på korrekte val-treff
    mx = pr_va.max(1)
    suggested = {}
    for i, l in enumerate(labels):
        ok = (pred_va == i) & (yva == i)
        q = float(np.percentile(mx[ok], 25)) if ok.sum() >= 5 else 0.5
        suggested[l] = round(min(max(q, 0.40), 0.90), 3)
    print(f"\n  foreslåtte terskler: {suggested}")

    torch.save({"state_dict": net.state_dict(), "classes": labels,
                "suggested_conf": suggested, "size": SIZE}, args.model)
    print(f"[✓] modell lagret -> {args.model}")


if __name__ == "__main__":
    main()