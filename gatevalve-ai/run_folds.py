#!/usr/bin/env python3
"""
run_folds.py — Kryssvalidering light: trener og evaluerer med RULLERENDE
holdout, så hver tegning i foldene måles som usett — og butterfly endelig
får sine ekte eksemplarer i trening (i foldene der HO71 ikke er holdout).

Per fold: tren hovedmodell -> min harde negativer -> tren verifikatorer
-> evaluer holdout. Artefakter arkiveres i results/folds/, og til slutt
aggregeres alle foldene til én samlet P/R-tabell + results/evaluation_folds.csv.

MERK: full kjøring er tung (~3 x hele treningssyklusen, gjerne 2-3 timer
på CPU). --skip-mining og --skip-verifiers gir en raskere, grovere runde.

Bruk:
  py run_folds.py --drawings-dir "C:\\Appl\\SommerstudentProsjekt\\data\\raw"
  py run_folds.py --drawings-dir ... --folds "a,b,c;d,e,f;g,h,i"
"""
import argparse, csv, os, shutil, subprocess, sys, time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_FOLDS = [
    "25VHO64PU00101,25VHO71PW00101,25WHO71PW00101",
    "25VHA24PE00101,25WHO13PE00401,25WHO63PU00501",
    "25WHO11PE00101,25WHO20PE00101,25VHO27PE00101",
]


def run(cmd, label):
    t0 = time.time()
    print(f"\n[{label}] {' '.join(str(c) for c in cmd)}")
    r = subprocess.run([sys.executable] + [str(c) for c in cmd], cwd=HERE)
    print(f"[{label}] ferdig på {time.time()-t0:.0f}s (kode {r.returncode})")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings-dir", required=True)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--folds", default=";".join(DEFAULT_FOLDS),
                    help="semikolonseparerte foldlister (komma innen fold)")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--verifier-epochs", type=int, default=10)
    ap.add_argument("--target-precision", type=float, default=0.95)
    ap.add_argument("--max-per-side", type=int, default=4000)
    ap.add_argument("--skip-mining", action="store_true")
    ap.add_argument("--skip-verifiers", action="store_true")
    args = ap.parse_args()

    folds = [f.strip() for f in args.folds.split(";") if f.strip()]
    arch = HERE / "results" / "folds"
    arch.mkdir(parents=True, exist_ok=True)
    hn_dir = HERE / "dataset" / "HardNegativeByClass"

    for i, fold in enumerate(folds, 1):
        print(f"\n{'='*68}\nFOLD {i}/{len(folds)} — holdout: {fold}\n{'='*68}")

        if hn_dir.exists():
            shutil.rmtree(hn_dir)          # ingen kryss-fold-lekkasje

        if not run(["train_cnn.py", "--real", "dataset",
                    "--holdout-list", fold, "--epochs", args.epochs],
                   f"fold{i}:tren"):
            print("[!] trening feilet — hopper til neste fold"); continue
        shutil.copy(HERE / "model_cnn.pt", arch / f"model_fold{i}.pt")

        if not args.skip_mining:
            run(["mine_hard_negatives.py", "--drawings-dir", args.drawings_dir,
                 "--model", "model_cnn.pt", "--dpi", args.dpi,
                 "--exclude", fold], f"fold{i}:mine")

        if not args.skip_verifiers:
            if run(["train_verifiers.py", "--real", "dataset",
                    "--synth", "synth", "--holdout-list", fold,
                    "--epochs", args.verifier_epochs,
                    "--max-per-side", args.max_per_side,
                    "--target-precision", args.target_precision],
                   f"fold{i}:verifikatorer"):
                shutil.copy(HERE / "verifiers.pt",
                            arch / f"verifiers_fold{i}.pt")
        else:
            # uten verifikatorer må evt. gammel fil vekk så classify kjører rent
            vf = HERE / "verifiers.pt"
            if vf.exists():
                vf.rename(arch / f"verifiers_prefold{i}_backup.pt")

        run(["make_report.py", "--drawings-dir", args.drawings_dir,
             "--model", "model_cnn.pt", "--dpi", args.dpi,
             "--holdout-only", fold], f"fold{i}:evaluer")
        ev = HERE / "results" / "evaluation.csv"
        if ev.exists():
            shutil.copy(ev, arch / f"evaluation_fold{i}.csv")

    # ---------------- aggregat over alle folder ----------------
    agg = defaultdict(lambda: [0] * 6)     # cls -> TPs,FPs,FNs,TPa,FPa,FNa
    rows = []
    for i in range(1, len(folds) + 1):
        p = arch / f"evaluation_fold{i}.csv"
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8")):
            r["fold"] = i
            rows.append(r)
            a = agg[r["class"]]
            for j, k in enumerate(["tp_strong", "fp_strong", "fn_strong",
                                   "tp_all", "fp_all", "fn_all"]):
                a[j] += int(r[k])

    out = HERE / "results" / "evaluation_folds.csv"
    if rows:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    print(f"\n{'='*68}\nAGGREGERT (alle folder — hver tegning målt som usett)\n{'='*68}")
    print(f"{'klasse':<16} {'fasit':>5} {'sikre: P / R':>16} {'m/mulige: P / R':>18}")
    for cls, (tps, fps, fns, tpa, fpa, fna) in sorted(agg.items()):
        n = tps + fns
        ps = tps / max(tps + fps, 1); rs = tps / max(n, 1)
        pa = tpa / max(tpa + fpa, 1); ra = tpa / max(tpa + fna, 1)
        print(f"{cls:<16} {n:>5} {ps:>7.0%} /{rs:>6.0%} {pa:>9.0%} /{ra:>6.0%}")
    print(f"\n[✓] per-rad detaljer -> {out}")
    print(f"[✓] fold-artefakter   -> {arch}")


if __name__ == "__main__":
    main()