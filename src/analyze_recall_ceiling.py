"""Recall-ceiling analysis on top of an existing validation run.

Answers two questions from Results.md's 'further work' list, without
touching the validator or the extractor:

  1. Nozzle exclusion - what is recall if nozzle tags (N1100 etc.), which
     are rarely printed as text, are removed from the ground truth?
  2. Valve-line split - of the MISSED valve/line tags, how many exist as
     readable text in the PDF at all? Splits the recall gap into
     'extraction miss (fixable)' vs 'symbol-only (method ceiling)'.

Reads:  <reports>/validation_report.csv and <reports>/validation_diffs.csv
Needs:  the PDFs under data/raw (for the text-presence check).

Usage:  python src/analyze_recall_ceiling.py --reports reports_vision --raw data/raw
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from extraction.pdf_parser import extract_words

# nozzle: N + digits (also single-digit: N1, N2, N3)
NOZZLE = re.compile(r"^(?:\d{1,3}[- ]?)?N\d{1,5}$", re.I)
# valve/line-ish tags, number-first form: 27-4510PV, 27-4454PL ...
VALVELINE = re.compile(r"^(?:\d{1,3}[- ]?)?\d{3,5}[A-Z]{1,3}$", re.I)


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def pick(df: pd.DataFrame, *cands: str) -> str:
    """Find a column by candidate names (case-insensitive, substring ok)."""
    low = {c.lower(): c for c in df.columns}
    for c in cands:
        if c in low:
            return low[c]
    for c in cands:
        for k, orig in low.items():
            if c in k:
                return orig
    sys.exit(f"Could not find any of {cands} among columns {list(df.columns)}")


def find_pdf(raw: Path, drawing: str) -> Path | None:
    stem = Path(drawing).stem
    hits = [p for p in raw.rglob("*.pdf") if p.stem.upper() == stem.upper()]
    hits += [p for p in raw.rglob("*.PDF") if p.stem.upper() == stem.upper()]
    return hits[0] if hits else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", default="reports_vision")
    ap.add_argument("--raw", default="data/raw")
    args = ap.parse_args()
    rep_dir, raw = Path(args.reports), Path(args.raw)

    report = pd.read_csv(rep_dir / "validation_report.csv")
    diffs = pd.read_csv(rep_dir / "validation_diffs.csv")

    d_col = pick(diffs, "drawing", "pdf", "file")
    t_col = pick(diffs, "tag")
    k_col = pick(diffs, "kind", "type", "status", "diff", "issue")
    rd_col = pick(report, "drawing", "pdf", "file")
    hit_col = pick(report, "hit", "hits", "tp")
    miss_col = pick(report, "missed", "miss", "fn")

    missed = diffs[diffs[k_col].astype(str).str.upper().str.contains("MISS")].copy()
    missed["is_nozzle"] = missed[t_col].map(lambda t: bool(NOZZLE.match(str(t).strip())))
    missed["is_valveline"] = missed[t_col].map(lambda t: bool(VALVELINE.match(str(t).strip())))

    # ---- 1) nozzle exclusion --------------------------------------------
    body = report[~report[rd_col].astype(str).str.upper().str.startswith("TOTAL")]
    noz = missed[missed["is_nozzle"]].groupby(d_col).size()

    rows, H, M, Mn = [], 0, 0, 0
    for _, r in body.iterrows():
        h, m = int(r[hit_col]), int(r[miss_col])
        n = int(noz.get(r[rd_col], 0))
        # nozzles are essentially never extracted as text, so hits are assumed
        # nozzle-free; excluding them therefore only shrinks the denominator
        rec0 = h / (h + m) if h + m else 0
        rec1 = h / (h + m - n) if h + m - n else 0
        rows.append((r[rd_col], h, m, n, f"{rec0:.0%}", f"{rec1:.0%}"))
        H, M, Mn = H + h, M + m, Mn + n
    print("== 1) Recall with nozzles excluded from ground truth ==")
    print(f"{'drawing':44s} {'hit':>4} {'miss':>5} {'noz':>4} {'R':>5} {'R_ex':>5}")
    for row in rows:
        print(f"{row[0]:44s} {row[1]:>4} {row[2]:>5} {row[3]:>4} {row[4]:>5} {row[5]:>5}")
    print(f"{'TOTAL':44s} {H:>4} {M:>5} {Mn:>4} "
          f"{H/(H+M):>5.0%} {H/(H+M-Mn):>5.0%}\n")

    # ---- 2) valve-line split: text-present vs symbol-only ---------------
    print("== 2) MISSED valve/line tags: present in PDF text layer? ==")
    vl = missed[missed["is_valveline"] & ~missed["is_nozzle"]]
    print(f"  analysing {len(vl)} valve/line misses across "
          f"{vl[d_col].nunique()} drawing(s) — reading PDFs, takes a moment...",
          flush=True)
    words_cache: dict[str, set[str]] = {}
    n_text = n_sym = n_nopdf = 0
    per_draw: dict[str, list[int]] = {}
    for _, r in vl.iterrows():
        draw, tag = str(r[d_col]), str(r[t_col]).strip()
        if draw not in words_cache:
            pdf = find_pdf(raw, draw)
            words_cache[draw] = ({norm(w) for (w, _, _) in extract_words(pdf)}
                                 if pdf else set())
            if not pdf:
                print(f"  [warn] no PDF found for {draw}")
        wset = words_cache[draw]
        ntag = norm(tag)
        unpref = re.sub(r"^\d{1,3}", "", ntag)
        number = re.sub(r"[A-Z]", "", unpref)
        present = (not wset and None) if False else any(
            ntag in w or unpref in w or (number and number in w) for w in wset)
        if not wset:
            n_nopdf += 1
            continue
        per_draw.setdefault(draw, [0, 0])
        if present:
            n_text += 1; per_draw[draw][0] += 1
        else:
            n_sym += 1;  per_draw[draw][1] += 1
    for draw, (t, s) in sorted(per_draw.items()):
        print(f"  {draw:44s} text-present {t:>3}   symbol-only {s:>3}")
    tot = n_text + n_sym
    if tot:
        print(f"  TOTAL valve/line misses analysed: {tot}  "
              f"-> text-present {n_text} ({n_text/tot:.0%}, fixable)  "
              f"symbol-only {n_sym} ({n_sym/tot:.0%}, method ceiling)")
        # recall uplift if every text-present miss were fixed
        print(f"  Max recall uplift from fixing text-present valve misses: "
              f"+{n_text/(H+M):.1%}-poeng (of baseline denominator)")
    if n_nopdf:
        print(f"  ({n_nopdf} misses skipped: PDF not found)")


if __name__ == "__main__":
    main()