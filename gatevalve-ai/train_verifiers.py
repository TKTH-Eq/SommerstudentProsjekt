#!/usr/bin/env python3
"""
train_verifiers.py — trener binære andretrinnsmodeller, én per
ventilklasse ("er dette virkelig en ball/globe/check/butterfly/reducer/
gate valve?"). Hovedmodellen model_cnn.pt endres IKKE; andretrinnet brukes
bare når hovedmodellen allerede har foreslått en klasse.

(Historikk: het train_non_gate_verifiers.py da gate-løpet var fredet;
fold-målingen viste at fredningen kostet ~56 presisjonspoeng, så gate har
nå også verifikator.)

PipeReducer og FlangedConnection vektes ekstra tungt som negativer, særlig
for ball valve. Klasse-spesifikke hard negatives fra
  dataset/HardNegativeByClass/<klasse>/
brukes kun mot den aktuelle verifikatoren og blir aldri globalt feilmerket
som background.

Bruk:
  py train_verifiers.py --real dataset --synth synth ^
      --holdout-list "25VHO64PU00101,25VHO71PW00101,25WHO71PW00101"

Ut:
  verifiers.pt
"""
import argparse
import glob
import os
import re
from collections import Counter
from functools import lru_cache

import cv2
import numpy as np

from train_classifier import canonicalize, REAL_MAP
from train_cnn import build_net

TARGETS = ("ball_valve", "globe_valve", "check_valve", "butterfly_valve",
           "reducer", "gate_valve")
DIR_TO_LABEL = dict(REAL_MAP)
DIR_TO_LABEL["GateValve"] = "gate_valve"  # positivt for gate-verifikatoren,
                                          # negativt for alle andre


def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def source_from_filename(path):
    return norm(os.path.basename(path).split("_")[0])


@lru_cache(maxsize=50000)
def load_canonical(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"kunne ikke lese {path}")
    return canonicalize(img)


# ball open/closed (og evt. gammel blandet ball_valve-mappe) er samme
# fysiske klasse for verifikatoren
SYNTH_ALIAS = {"ball_open": "ball_valve", "ball_closed": "ball_valve",
               "gate_open": "gate_valve", "gate_closed": "gate_valve"}


def collect_synthetic(root):
    items = []
    if not root or not os.path.isdir(root):
        return items
    for label in sorted(os.listdir(root)):
        d = os.path.join(root, label)
        if not os.path.isdir(d):
            continue
        for fp in glob.glob(os.path.join(d, "*.png")):
            items.append((fp, SYNTH_ALIAS.get(label, label), "synthetic"))
    return items


def collect_real(root, holdout):
    items = []
    if not root or not os.path.isdir(root):
        return items
    for dirname in sorted(os.listdir(root)):
        d = os.path.join(root, dirname)
        if not os.path.isdir(d) or dirname in ("yolo", "HardNegativeByClass"):
            continue
        label = DIR_TO_LABEL.get(dirname)
        if label is None:
            continue
        for fp in glob.glob(os.path.join(d, "*.png")):
            if source_from_filename(fp) in holdout:
                continue
            items.append((fp, label, dirname))
    return items


def collect_target_hard_negatives(root, target):
    if not root:
        return []
    d = os.path.join(root, target)
    return sorted(glob.glob(os.path.join(d, "**", "*.png"), recursive=True)) if os.path.isdir(d) else []


def negative_repeat(subtype, target):
    """Fokuser spesielt på kjente forvekslere uten å endre hovedmodellen."""
    if subtype == "PipeReducer":
        return 14 if target == "ball_valve" else 5
    if subtype == "FlangedConnection":
        return 7 if target == "ball_valve" else 4
    if subtype == "HardNegative":
        return 6
    if subtype == "Background":
        return 2
    if subtype == "GateValve":
        return 2
    if subtype == "synthetic":
        return 1
    return 3  # andre ekte ventiltyper er viktige class-vs-rest-negativer


def split_and_balance(pos, neg, rng, val_fraction, max_per_side):
    """pos/neg er (fil, vekt). Splitten skjer på UNIKE filer før
    oversampling, slik at samme utsnitt aldri havner i både trening og val."""
    pos, neg = list(pos), list(neg)
    rng.shuffle(pos); rng.shuffle(neg)
    if len(pos) < 2 or len(neg) < 2:
        raise ValueError(f"for lite data: {len(pos)} positive, {len(neg)} negative")

    npv = max(1, int(round(len(pos) * val_fraction)))
    nnv = max(1, int(round(len(neg) * val_fraction)))
    pos_va, pos_tr = pos[:npv], pos[npv:]
    neg_va, neg_tr = neg[:nnv], neg[nnv:]
    if not pos_tr: pos_tr = pos_va[:]
    if not neg_tr: neg_tr = neg_va[:]

    def sample_side(items, n):
        paths = [p for p, _ in items]
        weights = np.asarray([w for _, w in items], dtype=np.float64)
        weights /= weights.sum()
        idx = rng.choice(len(items), size=n, replace=True, p=weights)
        return [paths[int(i)] for i in idx]

    ntr = min(max(len(pos_tr), len(neg_tr)) * 3, max_per_side)
    nva = min(max(len(pos_va), len(neg_va)) * 2, max(400, max_per_side // 5))
    train = [(p, 1) for p in sample_side(pos_tr, ntr)] + [(p, 0) for p in sample_side(neg_tr, ntr)]
    valid = [(p, 1) for p in sample_side(pos_va, nva)] + [(p, 0) for p in sample_side(neg_va, nva)]
    rng.shuffle(train); rng.shuffle(valid)
    return train, valid


def as_arrays(items):
    X, y = [], []
    bad = 0
    for fp, label in items:
        try:
            X.append(load_canonical(fp))
            y.append(label)
        except ValueError:
            bad += 1
    if bad:
        print(f"      [!] hoppet over {bad} uleselige bilder")
    X = np.stack(X)[:, None].astype(np.float32) / 255.0
    return X, np.asarray(y, dtype=np.int64)


def augment(xb, rng):
    out = xb.copy()
    for i in range(len(out)):
        dx, dy = int(rng.integers(-2, 3)), int(rng.integers(-2, 3))
        out[i, 0] = np.roll(np.roll(out[i, 0], dy, axis=0), dx, axis=1)
        # Svært lett morfologisk variasjon, bare på en liten andel.
        if rng.random() < 0.12:
            k = np.ones((2, 2), np.uint8)
            z = (out[i, 0] * 255).astype(np.uint8)
            z = cv2.dilate(z, k) if rng.random() < 0.5 else cv2.erode(z, k)
            out[i, 0] = z.astype(np.float32) / 255.0
    return out


def choose_threshold(scores, y, target_precision):
    candidates = np.unique(np.concatenate([
        np.linspace(0.50, 0.995, 200), scores
    ]))
    feasible = []
    fallback = []
    for t in candidates:
        pred = scores >= t
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f05 = 1.25 * precision * recall / max(0.25 * precision + recall, 1e-9)
        fallback.append((f05, precision, recall, float(t), fp))
        if precision >= target_precision and tp > 0:
            feasible.append((recall, precision, -float(t), float(t), fp))
    if feasible:
        _, precision, _, threshold, fp = max(feasible)
        pred = scores >= threshold
        recall = ((pred == 1) & (y == 1)).sum() / max((y == 1).sum(), 1)
        return threshold, float(precision), float(recall), int(fp)
    _, precision, recall, threshold, fp = max(fallback)
    return threshold, float(precision), float(recall), int(fp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default="dataset")
    ap.add_argument("--synth", default="synth")
    ap.add_argument("--hard-negatives", default="dataset/HardNegativeByClass")
    ap.add_argument("--holdout-list", default="")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-fraction", type=float, default=0.20)
    ap.add_argument("--target-precision", type=float, default=0.98)
    ap.add_argument("--max-per-side", type=int, default=8000)
    ap.add_argument("--model", default="verifiers.pt")
    args = ap.parse_args()

    import torch
    import torch.nn as nn

    holdout = {norm(s) for s in args.holdout_list.split(",") if s.strip()}
    synth = collect_synthetic(args.synth)
    real = collect_real(args.real, holdout)
    print(f"[+] syntetisk: {len(synth)}  ekte (uten holdout): {len(real)}")
    print(f"    ekte undertyper: {dict(Counter(sub for _, _, sub in real))}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[+] trener binære verifikatorer på {dev}")
    state_dicts, thresholds, metrics = {}, {}, {}

    for target_index, target in enumerate(TARGETS):
        rng = np.random.default_rng(100 + target_index)
        pos = []  # (fil, samplingvekt)
        neg = []

        for fp, label, subtype in synth:
            (pos if label == target else neg).append((fp, 1.0))

        for fp, label, subtype in real:
            if label == target:
                pos.append((fp, 5.0))  # ekte positiver må dominere stilforskjellen
            else:
                neg.append((fp, float(negative_repeat(subtype, target))))

        hard = collect_target_hard_negatives(args.hard_negatives, target)
        for fp in hard:
            neg.append((fp, 10.0))

        print(f"\n=== {target} ===")
        print(f"    unike: {len(pos)} positive, {len(neg)} negative; "
              f"klasse-spesifikke hard negatives: {len(hard)}")
        train_items, valid_items = split_and_balance(
            pos, neg, rng, args.val_fraction, args.max_per_side)
        Xtr, ytr = as_arrays(train_items)
        Xva, yva = as_arrays(valid_items)
        print(f"    balansert: trening {len(ytr)}, validering {len(yva)}")

        torch.manual_seed(200 + target_index)
        net = build_net(2).to(dev)
        lossf = nn.CrossEntropyLoss()
        opt = torch.optim.Adam(net.parameters(), lr=args.lr)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
        tva = torch.tensor(Xva, device=dev)
        yva_t = torch.tensor(yva, device=dev)

        best_loss, best_state = float("inf"), None
        for ep in range(1, args.epochs + 1):
            net.train()
            order = rng.permutation(len(ytr))
            total = 0.0
            for b in range(0, len(order), args.batch):
                bi = order[b:b + args.batch]
                xb = torch.tensor(augment(Xtr[bi], rng), device=dev)
                yb = torch.tensor(ytr[bi], device=dev)
                opt.zero_grad()
                logits = net(xb)
                loss = lossf(logits, yb)
                loss.backward()
                opt.step()
                total += float(loss.detach()) * len(bi)
            sched.step()

            net.eval()
            with torch.no_grad():
                vloss = float(lossf(net(tva), yva_t).detach())
                vacc = float((net(tva).argmax(1) == yva_t).float().mean())
            print(f"    epoke {ep:2d}: train loss {total/len(ytr):.3f}  "
                  f"val loss {vloss:.3f}  val acc {vacc:.3f}")
            if vloss < best_loss:
                best_loss = vloss
                best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}

        net.load_state_dict(best_state)
        net.eval()
        with torch.no_grad():
            scores = net(tva).softmax(1)[:, 1].cpu().numpy()
        threshold, precision, recall, fp = choose_threshold(
            scores, yva, args.target_precision)
        print(f"    terskel {threshold:.3f}: precision {precision:.3f}, "
              f"recall {recall:.3f}, FP {fp}/{int((yva==0).sum())}")

        state_dicts[target] = best_state
        thresholds[target] = round(float(threshold), 4)
        metrics[target] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "false_positives": fp,
            "validation_negatives": int((yva == 0).sum()),
            "hard_negatives": len(hard),
        }

    torch.save({
        "version": 1,
        "state_dicts": state_dicts,
        "thresholds": thresholds,
        "metrics": metrics,
        "classes": list(TARGETS),
        "size": 64,
    }, args.model)
    print(f"\n[✓] verifikatorer lagret -> {args.model}")
    print(f"    terskler: {thresholds}")
    print("    model_cnn.pt er ikke endret; andretrinnet er separat.")


if __name__ == "__main__":
    main()