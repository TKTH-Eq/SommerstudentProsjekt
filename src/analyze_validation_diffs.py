"""
analyze_validation_diffs.py
=====================================================================
Reads the output of validate_against_dexpi.py and explains WHERE recall
is lost, so you know which single fix buys the most.

It classifies every MISSED / EXTRA tag by shape:
    instrument   type-first,   e.g. 27-PT4805   (\\d{2}-[A-Z]+\\d)
    valve_line   number-first, e.g. 27-4510PV   (\\d{2}-\\d+[A-Z])
    other        anything else (nozzles like N1100, etc.)

and reports:
  * the overall MISSED breakdown by class (the big lever),
  * an estimate of recall if the valve/line class were fully captured,
  * a per-drawing table with recall and the dominant miss class,
  * near-zero-yield drawings (likely no text layer / parse failure),
    which need a different fix (OCR) than the systematic ones.

Usage:
    python analyze_validation_diffs.py --out reports
    (expects reports/validation_report.csv and reports/validation_diffs.csv)
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


def classify(tag: str) -> str:
    if re.match(r"\d{2}-[A-Z]{1,4}\d", tag):
        return "instrument"
    if re.match(r"\d{2}-\d{2,4}[A-Z]", tag):
        return "valve_line"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports", type=Path)
    args = ap.parse_args()

    rep_path = args.out / "validation_report.csv"
    diff_path = args.out / "validation_diffs.csv"
    if not rep_path.exists() or not diff_path.exists():
        print(f"Missing {rep_path} or {diff_path}. Run validate_against_dexpi.py first.")
        return

    # --- load report (per drawing) ---
    report = {}
    with rep_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["drawing"] == "TOTAL":
                continue
            report[row["drawing"]] = {
                "truth": int(row["truth_tags"]),
                "extracted": int(row["extracted"]),
                "tp": int(row["tp"]),
                "missed": int(row["missed"]),
                "extra": int(row["extra"]),
                "recall": float(row["recall"]),
            }

    # --- load diffs and classify ---
    missed_by_class = defaultdict(int)
    extra_by_class = defaultdict(int)
    missed_by_draw = defaultdict(lambda: defaultdict(int))
    with diff_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cls = classify(row["tag"])
            if row["issue"].startswith("MISSED"):
                missed_by_class[cls] += 1
                missed_by_draw[row["drawing"]][cls] += 1
            else:
                extra_by_class[cls] += 1

    total_missed = sum(missed_by_class.values())
    total_tp = sum(d["tp"] for d in report.values())
    total_truth = sum(d["truth"] for d in report.values())

    print("=" * 64)
    print("WHERE RECALL IS LOST  (missed tags by class)")
    print("=" * 64)
    for cls in ("valve_line", "instrument", "other"):
        n = missed_by_class.get(cls, 0)
        pct = 100 * n / total_missed if total_missed else 0
        print(f"  {cls:11}: {n:4}  ({pct:4.0f}% of all misses)")
    print(f"  {'TOTAL':11}: {total_missed:4}")

    # what-if: recall if the valve_line class were fully captured
    recovered = missed_by_class.get("valve_line", 0)
    base_recall = total_tp / total_truth if total_truth else 0
    fixed_recall = (total_tp + recovered) / total_truth if total_truth else 0
    print(f"\n  Current recall (micro)          : {base_recall:.0%}")
    print(f"  Recall if valve_line fully fixed: {fixed_recall:.0%}"
          f"   (+{fixed_recall - base_recall:.0%})")

    # --- near-zero-yield drawings (different problem: no text / parse fail) ---
    zero_yield = [d for d, r in report.items()
                  if r["truth"] >= 5 and r["extracted"] <= max(1, 0.05 * r["truth"])]
    print("\n" + "=" * 64)
    print("NEAR-ZERO-YIELD DRAWINGS  (likely no text layer -> need OCR)")
    print("=" * 64)
    if zero_yield:
        for d in sorted(zero_yield):
            r = report[d]
            print(f"  {d}: extracted {r['extracted']} of {r['truth']} truth tags")
    else:
        print("  none")

    # --- per-drawing summary, worst recall first ---
    print("\n" + "=" * 64)
    print("PER-DRAWING  (worst recall first)")
    print("=" * 64)
    print(f"  {'recall':>6}  {'miss':>4}  {'val':>4}  {'inst':>4}  drawing")
    rows_out = []
    for d in sorted(report, key=lambda d: report[d]["recall"]):
        r = report[d]
        mv = missed_by_draw[d].get("valve_line", 0)
        mi = missed_by_draw[d].get("instrument", 0)
        print(f"  {r['recall']:6.0%}  {r['missed']:4}  {mv:4}  {mi:4}  {d}")
        rows_out.append({"drawing": d, "recall": r["recall"],
                         "missed": r["missed"], "missed_valve_line": mv,
                         "missed_instrument": mi,
                         "extracted": r["extracted"], "truth": r["truth"]})

    out_csv = args.out / "validation_diff_summary.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()