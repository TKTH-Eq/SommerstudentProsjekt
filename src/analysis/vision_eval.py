"""
Vision evaluation against the DEXPI ground truth.

The vision excerpt proposes tags; the open question has been how many of
its 'new candidates' are REAL. This script answers it without new API
calls: it reads the CACHED vision runs (reports/vision_cache/*.json),
re-verifies every model-mentioned tag against BOTH registers — the PDF
text layer and the DEXPI model — and classifies:

  CONFIRMED_BOTH   in text layer and DEXPI      (correct read, nothing new)
  RECOVERED        in DEXPI, NOT in text layer  (vision recovered a piece
                                                 of the 55 %-recall gap,
                                                 CONFIRMED by ground truth)
  TEXT_ONLY        in text layer, not DEXPI     (DEXPI omission or noise)
  UNCONFIRMED      well-formed, in neither      (hallucination OR beyond
                                                 both sources — manual)
  NOISE            not a parseable tag          (doc refs, abbreviations)

RECOVERED is the headline number: it measures, against an independent
ground truth, how much symbol-only content multimodal reading gives back.
Matching uses the (type, number) normalisation from ai.hazop_vision, so
convention differences do not distort the result.

Usage:  python src/analysis/vision_eval.py            # all cached runs
Output: table to stdout + reports/vision_eval.csv
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.hazop_vision import _type_number
from config import PID_DIR

RAW = Path(PID_DIR).parent
CACHE = Path("reports/vision_cache")


def _pairs(tags) -> set[tuple]:
    return {p for t in tags if (p := _type_number(str(t)))}


def _model_mentions(excerpt: dict) -> list[str]:
    out = []
    for obs in excerpt.get("observations", []):
        out += [t["tag"] if isinstance(t, dict) else t
                for t in obs.get("tags", [])]
    out += [so.get("tag", "") for so in excerpt.get("possible_symbol_only", [])]
    seen, uniq = set(), []
    for t in out:
        k = _type_number(str(t)) or str(t).upper()
        if k not in seen:
            seen.add(k)
            uniq.append(str(t))
    return uniq


def evaluate(stem: str, excerpt: dict) -> list[dict] | None:
    pdfs = list(RAW.rglob(f"{stem}.PDF")) + list(RAW.rglob(f"{stem}.pdf"))
    xmls = list(RAW.rglob(f"{stem}.DGN.xml"))
    if not pdfs or not xmls:
        return None                      # needs both sources to judge
    from extraction.tag_extractor import extract_tags
    from analysis.hazop_dexpi import load_dexpi_model
    text_pairs = _pairs(extract_tags(str(pdfs[0])))
    dexpi_pairs = _pairs(o.tag for o in load_dexpi_model(xmls[0])["objects"])

    rows = []
    for tag in _model_mentions(excerpt):
        pair = _type_number(tag)
        if pair is None:
            cls = "NOISE"
        elif pair in dexpi_pairs and pair in text_pairs:
            cls = "CONFIRMED_BOTH"
        elif pair in dexpi_pairs:
            cls = "RECOVERED"
        elif pair in text_pairs:
            cls = "TEXT_ONLY"
        else:
            cls = "UNCONFIRMED"
        rows.append({"drawing": stem, "tag": tag, "class": cls})
    return rows


def main() -> None:
    all_rows = []
    for f in sorted(CACHE.glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        rows = evaluate(f.stem, payload["excerpt"])
        if rows is None:
            print(f"{f.stem}: hopper over (mangler PDF eller DEXPI)")
            continue
        c = Counter(r["class"] for r in rows)
        n_parse = sum(v for k, v in c.items() if k != "NOISE")
        conf = c["CONFIRMED_BOTH"] + c["RECOVERED"]
        print(f"\n{f.stem}  ({payload.get('saved_at', '?')})")
        print(f"  modell-nevnte tags: {len(rows)}  (parsbare: {n_parse})")
        print(f"  bekreftet i fasit:  {conf}  "
              f"({c['CONFIRMED_BOTH']} også i tekstlag, "
              f"{c['RECOVERED']} GJENVUNNET fra recall-gapet)")
        print(f"  ubekreftet:         {c['UNCONFIRMED']}  · kun tekstlag: "
              f"{c['TEXT_ONLY']}  · støy: {c['NOISE']}")
        if n_parse:
            print(f"  presisjon mot fasit (parsbare): {conf / n_parse:.0%}")
        rec = [r["tag"] for r in rows if r["class"] == "RECOVERED"]
        if rec:
            print(f"  gjenvunnet: {', '.join(rec[:10])}")
        all_rows += rows

    if all_rows:
        out = Path("reports/vision_eval.csv")
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["drawing", "tag", "class"])
            w.writeheader()
            w.writerows(all_rows)
        tot = Counter(r["class"] for r in all_rows)
        n = sum(v for k, v in tot.items() if k != "NOISE")
        conf = tot["CONFIRMED_BOTH"] + tot["RECOVERED"]
        print(f"\nTOTALT over {len({r['drawing'] for r in all_rows})} "
              f"tegninger: {conf}/{n} parsbare modell-tags bekreftet av "
              f"fasiten ({conf / n:.0%}), hvorav {tot['RECOVERED']} "
              f"gjenvunnet fra tekstlagets recall-gap. -> {out}")


if __name__ == "__main__":
    main()