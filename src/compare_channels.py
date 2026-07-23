"""Compare extraction CHANNELS against the same DEXPI ground truth.

Three channels, scored with the exact same parsing/normalisation/matching as
validate_against_dexpi.py (imported from it, not copied):

    text    extraction.tag_extractor.extract_tags, vision reserve OFF
            (the validated 87/55/68 pipeline, page 1)
    vision  extraction.vision_extract.extract_tags_vision on the rendered
            page, with the same unprefixed-twin rule as the production
            reserve (tag_extractor._UNPREFIXED / _system_of)
    union   text | vision

The question this answers: text extraction has a measured ceiling (~74 %
recall ex-nozzle) because many tags exist only as graphics. Vision reads
pixels, not the text layer — can it break through that ceiling, and at what
precision cost? Either answer is a headline result.

Vision calls go through the disk cache (reports/vision_cache/tags/), so
re-runs are free. Text-rich drawings are not yet cached and will each cost
one API call on the first run (16 drawings max — well within one day's
quota on gemini-3.1-flash-lite).

Usage:
    python src/compare_channels.py --raw data/raw --out reports_channels
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# reuse the validator's ground truth + matching verbatim — the whole point
# is that all three channels are scored by IDENTICAL rules
from validate_against_dexpi import parse_dexpi, evaluate, find_pairs

from extraction.tag_extractor import (extract_tags as _text_extract,
                                      _UNPREFIXED, _system_of)
from extraction.vision_extract import extract_tags_vision

# same nozzle definition as analyze_recall_ceiling.py, for the ex-nozzle view
NOZZLE = re.compile(r"^(?:\d{1,3}[- ]?)?N\d{1,5}$", re.I)

CHANNELS = ("text", "vision", "union")


def text_tags(pdf_path: Path) -> set[str]:
    """The validated text pipeline, vision reserve guaranteed off."""
    os.environ.pop("HULDRA_VISION", None)
    return _text_extract(pdf_path)


def vision_tags(pdf_path: Path) -> set[str]:
    """Vision channel with the production reserve's twin rule applied."""
    system = _system_of(pdf_path)
    out: set[str] = set()
    for vt in extract_tags_vision(pdf_path):
        out.add(vt)
        if _UNPREFIXED.match(vt):           # "PT4805" -> also "27-PT4805"
            out.add(f"{system}-{vt}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score text / vision / union channels against DEXPI.")
    ap.add_argument("--raw", default="data/raw", type=Path)
    ap.add_argument("--out", default="reports_channels", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pairs, _, _, _ = find_pairs(args.raw)
    if not pairs:
        sys.exit("No XML/PDF pairs found — check --raw.")
    print(f"Scoring {len(pairs)} drawing(s), 3 channels, identical matching.\n")

    agg = {ch: {"tp": 0, "fn": 0, "fp": 0} for ch in CHANNELS}
    agg_ex = {ch: {"tp": 0, "fn": 0} for ch in CHANNELS}   # ex-nozzle recall
    rows = []
    skipped = []

    for pdf_path, xml_path in pairs:
        truth, _pipes = parse_dexpi(xml_path)
        truth_ex = {t for t in truth if not NOZZLE.match(t.strip())}
        try:
            ext = {"text": text_tags(pdf_path)}
            ext["vision"] = vision_tags(pdf_path)
        except Exception as e:  # noqa: BLE001  (API quota etc.)
            print(f"  ! {pdf_path.name}: vision failed ({e}) — drawing "
                  f"excluded from ALL channels to keep totals comparable")
            skipped.append(pdf_path.name)
            continue
        ext["union"] = ext["text"] | ext["vision"]

        line = f"  {pdf_path.name}:"
        for ch in CHANNELS:
            r = evaluate(ext[ch], truth)
            rex = evaluate(ext[ch], truth_ex)
            for k in ("tp", "fn", "fp"):
                agg[ch][k] += r[k]
            agg_ex[ch]["tp"] += rex["tp"]
            agg_ex[ch]["fn"] += rex["fn"]
            rows.append({
                "drawing": pdf_path.name, "channel": ch,
                "truth": len(truth), "extracted": len(ext[ch]),
                "tp": r["tp"], "missed": r["fn"], "extra": r["fp"],
                "precision": round(r["precision"], 3),
                "recall": round(r["recall"], 3),
                "f1": round(r["f1"], 3),
                "recall_ex_nozzle": round(rex["recall"], 3),
            })
            line += (f"  {ch} P{r['precision']:.0%}/R{r['recall']:.0%}"
                     f"(ex-noz {rex['recall']:.0%})")
        print(line)

    print("\n" + "=" * 72)
    print(f"{'channel':8s} {'P':>6} {'R':>6} {'F1':>6} {'R ex-nozzle':>12}"
          f"   (micro over {len(pairs) - len(skipped)} drawings)")
    print("-" * 72)
    for ch in CHANNELS:
        a, ax = agg[ch], agg_ex[ch]
        P = a["tp"] / (a["tp"] + a["fp"]) if (a["tp"] + a["fp"]) else 0.0
        R = a["tp"] / (a["tp"] + a["fn"]) if (a["tp"] + a["fn"]) else 0.0
        F = 2 * P * R / (P + R) if (P + R) else 0.0
        Rx = ax["tp"] / (ax["tp"] + ax["fn"]) if (ax["tp"] + ax["fn"]) else 0.0
        print(f"{ch:8s} {P:>6.0%} {R:>6.0%} {F:>6.0%} {Rx:>12.0%}")
        rows.append({"drawing": "TOTAL", "channel": ch,
                     "truth": a["tp"] + a["fn"],
                     "extracted": a["tp"] + a["fp"],
                     "tp": a["tp"], "missed": a["fn"], "extra": a["fp"],
                     "precision": round(P, 3), "recall": round(R, 3),
                     "f1": round(F, 3), "recall_ex_nozzle": round(Rx, 3)})
    if skipped:
        print(f"\n({len(skipped)} drawing(s) excluded after vision failure: "
              f"{', '.join(skipped)} — re-run to retry, cache keeps successes)")

    out_csv = args.out / "channel_comparison.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()