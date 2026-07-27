#!/usr/bin/env python3
"""
make_report.py — Sluttevaluering: kjører classify_drawing på alle tegninger
med fasit (labels.csv), matcher funn mot XML-posisjoner, og teller
TP/FP/FN per klasse per tegning — i begge lag (sikre / sikre+mulige).

Reducer og flenser er bakgrunn by design og skåres ikke.
Gate open/closed slås sammen mot GateValve-fasiten (XML skiller ikke
tilstand); tilstandsfordelingen rapporteres som tilleggsinfo.

Ut:
  results/evaluation.csv       én rad per tegning x klasse
  terminal                     totaltabell med presisjon/dekning

Bruk:
  py make_report.py --drawings-dir "C:\\Appl\\SommerstudentProsjekt\\data\\raw" ^
      --model model_cnn.pt --dpi 200
  (legg --holdout-only for kun holdout-tegningene, eller --exclude ... )
"""
import argparse, csv, glob, json, os, re, subprocess, sys
from collections import defaultdict

def norm(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()

# deteksjonsklasse -> DEXPI-fasitklasse(r)
DET2GT = {"gate": ["GateValve"], "ball": ["BallValve"],
          "globe_valve": ["GlobeValve"], "check_valve": ["CheckValve"],
          "butterfly_valve": ["ButterflyValve"], "reducer": ["PipeReducer"],
          "other_valve": ["NeedleValve", "PlugValve", "AngleValve"]}

def find_source_key(stem, gt):
    nk = norm(stem)
    exact = [k for k in gt if nk.endswith(k) or k.endswith(nk)]
    if exact:
        return max(exact, key=len)
    tail = nk[-14:]
    part = [k for k in gt if k in nk or tail in k]
    return max(part, key=len) if part else None

def match(dets, pts, radius_f):
    """Grådig matching: hvert fasitpunkt til nærmeste ledige funn innen radius."""
    used = set()
    tp = 0
    for gx, gy in pts:
        best, bi = None, None
        for i, d in enumerate(dets):
            if i in used:
                continue
            x0, y0, x1, y1 = d["bbox_orig"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            R = radius_f * max(x1 - x0, y1 - y0)
            dist2 = (gx - cx) ** 2 + (gy - cy) ** 2
            if dist2 <= R * R and (best is None or dist2 < best):
                best, bi = dist2, i
        if bi is not None:
            used.add(bi)
            tp += 1
    return tp, len(dets) - len(used), len(pts) - tp   # TP, FP, FN

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings-dir", required=True)
    ap.add_argument("--labels", default="dataset/labels.csv")
    ap.add_argument("--model", default="model_cnn.pt")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--radius", type=float, default=1.5)
    ap.add_argument("--exclude", default="", help="hopp over disse (komma)")
    ap.add_argument("--holdout-only", default="",
                    help="evaluer KUN disse tegningene (komma)")
    ap.add_argument("--results-dir", default="results")
    # videresendes til classify_drawing (forslagssteget)
    ap.add_argument("--cand-threshold", type=float, default=None)
    ap.add_argument("--cand-scales", default=None)
    ap.add_argument("--cand-mirror", action="store_true")
    ap.add_argument("--cand-components", action="store_true")
    args = ap.parse_args()

    exclude = {norm(s) for s in args.exclude.split(",") if s.strip()}
    only = {norm(s) for s in args.holdout_only.split(",") if s.strip()}

    gt = {}
    for r in csv.DictReader(open(args.labels, encoding="utf-8")):
        gt.setdefault(norm(r["source"]), {}).setdefault(r["class"], []).append(
            (float(r["cx_px"]), float(r["cy_px"])))
    print(f"[+] fasit for {len(gt)} tegninger fra {args.labels}")

    files = []
    for ext in ("pdf", "PDF", "jpg", "jpeg", "png"):
        files += glob.glob(os.path.join(args.drawings_dir, "**", f"*.{ext}"),
                           recursive=True)
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(args.results_dir, exist_ok=True)

    rows = []
    agg = defaultdict(lambda: [0, 0, 0, 0, 0, 0])  # cls -> TPs,FPs,FNs,TPa,FPa,FNa
    for fp in sorted(set(files)):
        stem = os.path.splitext(os.path.basename(fp))[0]
        key = find_source_key(stem, gt)
        if key is None or key in exclude or (only and key not in only):
            continue
        det_path = os.path.join(args.results_dir, f"{stem}_detections.json")
        cmd = [sys.executable, os.path.join(here, "classify_drawing.py"),
               fp, "--dpi", str(args.dpi), "--model", args.model,
               "--out-dir", args.results_dir, "--dump-detections"]
        if args.cand_threshold is not None:
            cmd += ["--cand-threshold", str(args.cand_threshold)]
        if args.cand_scales:
            cmd += ["--cand-scales", args.cand_scales]
        if args.cand_mirror:
            cmd += ["--cand-mirror"]
        if args.cand_components:
            cmd += ["--cand-components"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if not os.path.exists(det_path):
            print(f"    {stem}: FEIL — ingen detections ({r.returncode})")
            continue
        dets = json.load(open(det_path, encoding="utf-8"))

        # slå sammen gate og ball open/closed mot tilstandsløs XML-fasit;
        # noter tilstandsfordelingene som tilleggsinfo
        byc = defaultdict(list)
        for d in dets:
            c = d["cls"]
            if c in ("gate_open", "gate_closed"):
                bucket = "gate"
            elif c in ("ball_open", "ball_closed", "ball_valve"):
                bucket = "ball"
            else:
                bucket = c
            byc[bucket].append(d)
        states = f'{sum(1 for d in byc["gate"] if d["cls"]=="gate_open")}o/' \
                 f'{sum(1 for d in byc["gate"] if d["cls"]=="gate_closed")}c'
        ball_states = f'{sum(1 for d in byc["ball"] if d["cls"]=="ball_open")}o/' \
                      f'{sum(1 for d in byc["ball"] if d["cls"]=="ball_closed")}c'

        line = [f"    {stem}"]
        for cls, gcls in DET2GT.items():
            pts = [p for g in gcls for p in gt[key].get(g, [])]
            all_d = byc.get(cls, [])
            strong = [d for d in all_d if d.get("tier", "sikker") == "sikker"]
            tps, fps, fns = match(strong, pts, args.radius)
            tpa, fpa, fna = match(all_d, pts, args.radius)
            if pts or all_d:
                rows.append({"drawing": key, "class": cls, "gt": len(pts),
                             "tp_strong": tps, "fp_strong": fps, "fn_strong": fns,
                             "tp_all": tpa, "fp_all": fpa, "fn_all": fna,
                             "gate_states": states if cls == "gate" else "",
                             "ball_states": ball_states if cls == "ball" else ""})
                a = agg[cls]
                for i, v in enumerate((tps, fps, fns, tpa, fpa, fna)):
                    a[i] += v
                line.append(f"{cls.replace('_valve','')}:{tps}/{len(pts)}"
                            + (f"+{fps}fp" if fps else ""))
        print("  ".join(line))

    out = os.path.join(args.results_dir, "evaluation.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["drawing", "class", "gt",
                                          "tp_strong", "fp_strong", "fn_strong",
                                          "tp_all", "fp_all", "fn_all",
                                          "gate_states", "ball_states"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'klasse':<12} {'fasit':>5} {'sikre: P / R':>16} {'m/mulige: P / R':>18}")
    for cls, (tps, fps, fns, tpa, fpa, fna) in agg.items():
        n = tps + fns
        ps = tps / max(tps + fps, 1); rs = tps / max(n, 1)
        pa = tpa / max(tpa + fpa, 1); ra = tpa / max(tpa + fna, 1)
        print(f"{cls:<12} {n:>5} {ps:>7.0%} /{rs:>6.0%} {pa:>9.0%} /{ra:>6.0%}")
    print(f"\n[✓] -> {out}")

if __name__ == "__main__":
    main()