"""
validate_against_dexpi.py
=====================================================================
Measures the tag extractor against the Semantum DEXPI XML files, which
act as ground truth wherever they exist.

DEXPI (ISO 15926 / Dexpi 1.3) stores tags as:
    TagName="27-PT4805"                     on instrument/valve elements
    <GenericAttribute Name="tagName"   ...> repeated instrument tag
    <GenericAttribute Name="valveTag"  ...> hand-valve tags (27-4510PV)
    <GenericAttribute Name="TagNameAssignmentClass" ...> main equipment
    <GenericAttribute Name="PipelineTag" ...> pipe line tags (kept separate)

Only the drawings that have a matching *_DGN.xml are scored. Everything
else runs through the same pipeline but simply isn't measured — a partial
ground truth still gives a legitimate accuracy figure on its subset.

For each matched P&ID / XML pair it reports precision, recall and F1, and
writes the exact disagreements (MISSED = in XML but not extracted, EXTRA =
extracted but not in XML) so an engineer can see whether each gap is an
extractor miss or real documentation drift.

Outputs:
    reports/validation_report.csv   one row per scored drawing + a TOTAL row
    reports/validation_diffs.csv    one row per disagreeing tag

Usage:
    python validate_against_dexpi.py --raw data/raw --out reports
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# --- Use the PROJECT's own extractor when available, so we measure the real
#     pipeline. Falls back to a built-in extractor if run standalone. --------
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
try:
    from extraction.tag_extractor import extract_tags as _project_extract
    from extraction.tag_extractor import create_objects as _project_objects

    def extract_pdf_tags(pdf_path: str) -> set[str]:
        objs = _project_objects(_project_extract(pdf_path), "P&ID")
        return {o.tag for o in objs}

    EXTRACTOR = "project pipeline (extraction.tag_extractor)"
except Exception:
    import math
    import pdfplumber

    _TYPES = {"PT", "TT", "FT", "LT", "PDT", "PI", "TI", "FI", "LI", "PDI",
              "PIC", "FIC", "TIC", "LIC", "PV", "FV", "XV", "LV", "TV", "PY",
              "FY", "XY", "TY", "ZY", "ZS", "ZL", "HS", "HV", "PSV", "PSE",
              "FE", "FO", "SI", "FSH", "PSH", "PSL", "KA"}
    _JOINED = re.compile(r"\b(\d{2})-([A-Z]{1,4})(\d{2,4})([A-Z])?\b")
    _VALVE = re.compile(r"\b(\d{2})-(\d{3,4})([A-Z]{2})\b")

    def extract_pdf_tags(pdf_path: str) -> set[str]:
        ws = []
        with pdfplumber.open(pdf_path) as pdf:
            for p in pdf.pages:
                for w in p.extract_words(use_text_flow=False):
                    ws.append((w["text"], (w["x0"] + w["x1"]) / 2,
                               (w["top"] + w["bottom"]) / 2))
        full = " ".join(w[0] for w in ws)
        drawing_sys = "27"
        m = re.search(r"H[A-Z](\d{2})", Path(pdf_path).stem)
        if m:
            drawing_sys = m.group(1)
        tags = set()
        for mm in _JOINED.finditer(full):
            s, d, n, x = mm.groups()
            tags.add(f"{s}-{d}{n}{x or ''}")
        for mm in _VALVE.finditer(full):
            tags.add(f"{mm.group(1)}-{mm.group(2)}{mm.group(3)}")
        types = [(t, x, y) for t, x, y in ws if t in _TYPES]
        nums = [(t, x, y) for t, x, y in ws if re.fullmatch(r"\d{4}[A-Z]?", t)]
        for t, x, y in types:
            best, bd = None, 45.0
            for nt, nx, ny in nums:
                if abs(nx - x) < 22 and (ny - y) > -5:
                    d = math.hypot(nx - x, ny - y)
                    if d < bd:
                        bd, best = d, nt
            if best:
                tags.add(f"{drawing_sys}-{t}{best}")
        return tags

    EXTRACTOR = "built-in fallback extractor"


# --------------------------------------------------------------------------
# DEXPI ground truth
# --------------------------------------------------------------------------

_WANT_ATTR = {"tagName", "valveTag", "TagNameAssignmentClass",
              "SubTagNameAssignmentClass"}


def parse_dexpi(xml_path: Path) -> tuple[set[str], set[str]]:
    """Return (equipment/instrument/valve tags, pipeline tags)."""
    root = ET.parse(xml_path).getroot()
    tags, pipes = set(), set()

    def add(t: str | None):
        if not t:
            return
        t = t.strip()
        if '"' in t:                      # pipe line tag, e.g. 6"-PV-274508-...
            pipes.add(t)
        elif re.search(r"\d", t) and not t.lower().startswith("empty"):
            tags.add(t)

    for el in root.iter():
        add(el.get("TagName"))
        if el.tag.endswith("GenericAttribute") and el.get("Name") in _WANT_ATTR:
            add(el.get("Value"))
        if el.tag.endswith("GenericAttribute") and el.get("Name") == "PipelineTag":
            v = el.get("Value")
            if v:
                pipes.add(v.strip())
    return tags, pipes


def normalize(tag: str) -> str:
    """Canonical key: upper-case, separators stripped. Makes 27-PT4805 and
    27-4510PV comparable across sources that agree on the native string."""
    return re.sub(r"[^A-Z0-9]", "", tag.upper())


# --------------------------------------------------------------------------
# Matching + evaluation
# --------------------------------------------------------------------------

def _normstem(name: str) -> str:
    """Lower-case, strip every non-alphanumeric char (so _E vs *E, spaces,
    dots and dashes all collapse to the same key)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_pairs(raw_dir: Path):
    """Match each DEXPI .xml to its PDF by drawing-number stem, tolerant to
    naming variants (name_DGN.xml, name.DGN.xml, name.xml, any case).

    Returns (pairs, unmatched_xmls, n_xml, n_pdf).
    """
    files = [p for p in raw_dir.rglob("*") if p.is_file()]
    xmls = [p for p in files if p.suffix.lower() == ".xml"]
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]

    pdf_by_key = {}
    for p in pdfs:
        pdf_by_key.setdefault(_normstem(p.stem), p)

    pairs, unmatched = [], []
    for x in sorted(xmls):
        # pathlib strips only the last suffix, so "name.DGN.xml" -> stem
        # "name.DGN". Normalise, then drop a trailing "dgn" token if present.
        xkey = _normstem(x.stem)
        xbase = xkey[:-3] if xkey.endswith("dgn") else xkey
        pdf = pdf_by_key.get(xbase) or pdf_by_key.get(xkey)
        if pdf:
            pairs.append((pdf, x))
        else:
            unmatched.append(x)
    return pairs, unmatched, len(xmls), len(pdfs)


def evaluate(extracted: set[str], truth: set[str]):
    T = {normalize(t): t for t in truth}
    E = {normalize(t): t for t in extracted}
    tp = set(T) & set(E)
    fn = set(T) - set(E)      # missed
    fp = set(E) - set(T)      # extra
    prec = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 0.0
    rec = len(tp) / (len(tp) + len(fn)) if (tp or fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "tp": len(tp), "fn": len(fn), "fp": len(fp),
        "precision": prec, "recall": rec, "f1": f1,
        "missed": sorted(T[k] for k in fn),
        "extra": sorted(E[k] for k in fp),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Validate tag extraction against DEXPI XML ground truth.")
    ap.add_argument("--raw", default="data/raw", type=Path)
    ap.add_argument("--out", default="reports", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pairs, unmatched, n_xml, n_pdf = find_pairs(args.raw)
    print(f"Extractor under test: {EXTRACTOR}")
    print(f"Under {args.raw}: found {n_xml} .xml and {n_pdf} .pdf files.")
    if not pairs:
        print("\nNo XML/PDF pairs matched. Diagnostics:")
        if n_xml == 0:
            print("  * No .xml files at all under this folder. Check that the "
                  "Semantum XML export actually lives under --raw (e.g. "
                  "data\\raw\\Semantum Huldra P&IDS\\), and that you passed the "
                  "right --raw path.")
        else:
            print(f"  * {n_xml} XML(s) found but none matched a PDF by name.")
            print("    Example XML stems : "
                  + ", ".join(sorted({x.stem for x in unmatched})[:3]))
            print("    Example PDF stems : "
                  + ", ".join(sorted({p.stem for p in
                              (list(args.raw.rglob('*.pdf')) +
                               list(args.raw.rglob('*.PDF')))})[:3]))
            print("    The XML stem should reduce to the PDF stem after "
                  "dropping a trailing _DGN/.DGN. If your names differ more "
                  "than that, tell me the pattern and I'll adjust the matcher.")
        return
    if unmatched:
        print(f"({len(unmatched)} XML(s) had no matching PDF and were skipped.)")
    print(f"Scoring {len(pairs)} drawing(s) that have a DEXPI XML.\n")

    report_rows, diff_rows = [], []
    agg = {"tp": 0, "fn": 0, "fp": 0}

    for pdf_path, xml_path in pairs:
        truth, pipes = parse_dexpi(xml_path)
        try:
            extracted = extract_pdf_tags(str(pdf_path))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {pdf_path.name}: extraction failed ({e})")
            continue
        r = evaluate(extracted, truth)
        for k in ("tp", "fn", "fp"):
            agg[k] += r[k]
        report_rows.append({
            "drawing": pdf_path.name, "truth_tags": len(truth),
            "extracted": len(extracted), "tp": r["tp"], "missed": r["fn"],
            "extra": r["fp"], "precision": round(r["precision"], 3),
            "recall": round(r["recall"], 3), "f1": round(r["f1"], 3),
        })
        for t in r["missed"]:
            diff_rows.append({"drawing": pdf_path.name, "tag": t,
                              "issue": "MISSED (in XML, not extracted)"})
        for t in r["extra"]:
            diff_rows.append({"drawing": pdf_path.name, "tag": t,
                              "issue": "EXTRA (extracted, not in XML)"})
        print(f"  {pdf_path.name}: P {r['precision']:.0%}  R {r['recall']:.0%}"
              f"  F1 {r['f1']:.0%}   ({r['tp']} hit, {r['fn']} missed, "
              f"{r['fp']} extra)")

    # aggregate (micro-average over all scored tags)
    tp, fn, fp = agg["tp"], agg["fn"], agg["fp"]
    P = tp / (tp + fp) if (tp + fp) else 0.0
    R = tp / (tp + fn) if (tp + fn) else 0.0
    F = 2 * P * R / (P + R) if (P + R) else 0.0
    report_rows.append({
        "drawing": "TOTAL", "truth_tags": tp + fn, "extracted": tp + fp,
        "tp": tp, "missed": fn, "extra": fp,
        "precision": round(P, 3), "recall": round(R, 3), "f1": round(F, 3)})

    with (args.out / "validation_report.csv").open("w", newline="",
                                                   encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
        w.writeheader()
        w.writerows(report_rows)
    with (args.out / "validation_diffs.csv").open("w", newline="",
                                                  encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["drawing", "tag", "issue"])
        w.writeheader()
        w.writerows(diff_rows)

    print(f"\nTOTAL over {len(pairs)} scored drawing(s): "
          f"PRECISION {P:.0%}  RECALL {R:.0%}  F1 {F:.0%}")
    print(f"Wrote {args.out/'validation_report.csv'} and "
          f"{args.out/'validation_diffs.csv'}")
    print("\nNote: drawings without a DEXPI XML are not scored; this figure "
          "is measured on the XML-covered subset and estimates the rest.")


if __name__ == "__main__":
    main()