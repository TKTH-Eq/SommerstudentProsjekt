"""
build_tag_register.py
=====================================================================
Backbone for the Huldra summer-student project.

Walks data/raw, extracts equipment/instrument tags from every P&ID and
SCD drawing, normalises them to a canonical form, and produces:

    reports/tag_register.csv          one row per tag: where it appears,
                                      system, type, BOTH/PID_ONLY/SCD_ONLY
    reports/tag_register.json         same data, for index.html / the app
    reports/reconciliation.csv        per-system P&ID<->SCD comparison
    reports/reconciliation_summary.csv  counts per system

Extraction strategy (validated against the system-27 drawings):
  * PDFs are MicroStation CAD exports WITH a real text layer, so a plain
    text scraper (pdfplumber) is primary -- free, fast, exact.
  * Tags appear in two forms:
        joined  ->  "27-PT4805"          (labels, notes, line tags)
        split   ->  "PT" / "4805" / "27" (instrument bubbles on P&IDs)
    Joined tags are caught by regex on all documents. Split bubbles are
    recombined from word coordinates -- P&IDs only, because SCDs already
    write their tags joined.
  * Google Vision is only needed for scanned drawings that have NO text
    layer. That fallback is optional (see ocr_pages_with_vision) and is
    triggered automatically when a PDF yields no extractable text.

Usage:
    python build_tag_register.py --raw data/raw --out reports
    python build_tag_register.py --raw data/raw --out reports --system 27
    python build_tag_register.py --raw data/raw --out reports --vision
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# ISA / instrument function codes used on the Huldra drawings. Curated so
# that stray words and signal labels (e.g. PSD) are NOT read as instruments.
INSTRUMENT_TYPES = {
    "PT", "TT", "FT", "LT", "PDT",                       # transmitters
    "PI", "TI", "FI", "LI", "PDI",                       # indicators
    "PIC", "FIC", "TIC", "LIC",                          # controllers
    "PV", "FV", "XV", "LV", "TV",                        # valves
    "PY", "FY", "XY", "TY", "ZY",                        # relays / computing
    "ZS", "ZL",                                          # position switch / lamp
    "HS", "HV",                                          # hand switch / valve
    "PSV", "PSE",                                        # safety valve / element
    "FE", "FO",                                          # flow element / restriction orifice
    "SI",                                                # speed / vibration
    "FSH", "PSH", "PSL", "PAH", "PAL",                   # switches / alarms
    "KA",                                               # machine (compressor)
}

# Human-readable category, for the register (extend as needed).
TYPE_CATEGORY = {
    **{t: "transmitter" for t in ("PT", "TT", "FT", "LT", "PDT")},
    **{t: "indicator" for t in ("PI", "TI", "FI", "LI", "PDI")},
    **{t: "controller" for t in ("PIC", "FIC", "TIC", "LIC")},
    **{t: "control_valve" for t in ("PV", "FV", "LV", "TV")},
    "XV": "shutdown_valve",
    **{t: "relay" for t in ("PY", "FY", "XY", "TY", "ZY")},
    "ZS": "position_switch", "ZL": "position_indicator",
    "HS": "hand_switch", "HV": "hand_valve",
    "PSV": "safety_valve", "PSE": "safety_element",
    "FE": "flow_element", "FO": "restriction_orifice",
    "SI": "speed_vibration",
    "KA": "machine",
}

# Folders / files under data/raw that are NOT tag sources and must be
# skipped during extraction (reference material, semantic set, legal).
# Matching is case-insensitive on any part of the path.
SKIP_PARTS = {
    "scd legend", "symbols", "semantum", "processed", "legend",
}
SKIP_NAME_SUBSTRINGS = {
    "license", "licence",          # e.g. "Equinor open data sharing license"
}

JOINED_TAG = re.compile(r"\b(\d{2})-([A-Z]{1,4})(\d{2,4})([A-Z])?\b")
LOOP_NUMBER = re.compile(r"^\d{4}[A-Z]?$")      # instrument loop numbers are 4-digit
SYSTEM_TOKEN = re.compile(r"^HO(\d{1,3})", re.IGNORECASE)


# --------------------------------------------------------------------------
# File discovery + classification
# --------------------------------------------------------------------------

@dataclass
class Drawing:
    path: Path
    doc_type: str          # "PID" | "SCD"
    system: str            # e.g. "27"
    name: str


def parse_system(filename: str) -> str | None:
    """Pull the system number out of the HO<sys> token in the filename."""
    for token in filename.replace("-", " ").split():
        m = SYSTEM_TOKEN.match(token)
        if m:
            return m.group(1)
    return None


def parse_discipline(filename: str) -> str | None:
    """Discipline letter is the token right after the HO<sys> token."""
    tokens = filename.replace("-", " ").split()
    for i, tok in enumerate(tokens):
        if SYSTEM_TOKEN.match(tok) and i + 1 < len(tokens):
            return tokens[i + 1].upper()
    return None


def is_skipped(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    if any(any(skip in part for part in parts) for skip in SKIP_PARTS):
        return True
    lower = path.name.lower()
    return any(s in lower for s in SKIP_NAME_SUBSTRINGS)


def discover_drawings(raw_dir: Path) -> list[Drawing]:
    """Find every P&ID / SCD PDF under raw_dir, skipping reference material."""
    drawings: list[Drawing] = []
    for path in sorted(raw_dir.rglob("*.pdf")) + sorted(raw_dir.rglob("*.PDF")):
        if is_skipped(path):
            continue
        disc = parse_discipline(path.name)
        # Fall back to folder name if the filename doesn't carry the discipline.
        folder = " ".join(p.lower() for p in path.parts)
        if disc == "P" or ("p&id" in folder and disc not in ("J",)):
            doc_type = "PID"
        elif disc == "J" or "scd" in folder:
            doc_type = "SCD"
        else:
            continue  # not a P&ID or SCD -> ignore for reconciliation
        system = parse_system(path.name) or "?"
        drawings.append(Drawing(path=path, doc_type=doc_type,
                                system=system, name=path.name))
    # de-duplicate the .pdf/.PDF double glob on case-insensitive filesystems
    seen, unique = set(), []
    for d in drawings:
        key = str(d.path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


# --------------------------------------------------------------------------
# Text + tag extraction
# --------------------------------------------------------------------------

def read_words(path: Path):
    """Return (text, words) where words is [(text, cx, cy), ...]."""
    words = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for w in page.extract_words(use_text_flow=False):
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                words.append((w["text"], cx, cy))
    text = " ".join(w[0] for w in words)
    return text, words


def extract_tags(path: Path, system: str, doc_type: str,
                 use_vision: bool = False) -> set[str]:
    """Extract normalised tags from one drawing."""
    text, words = read_words(path)

    # Scanned drawing with no text layer -> optionally OCR with Vision.
    if len(text.strip()) < 20:
        if use_vision:
            text = ocr_pages_with_vision(path)
            words = []  # OCR gives no reliable coordinates for recombination
        else:
            return set()

    tags: set[str] = set()

    # 1) Joined tags (both P&ID and SCD, incl. cross-system tie-ins).
    for m in JOINED_TAG.finditer(text):
        s, d, n, suf = m.groups()
        tags.add(f"{s}-{d}{n}{suf or ''}")

    # 2) Split instrument bubbles -- P&IDs only, using the drawing's own
    #    system number and a tight coordinate pairing.
    if doc_type == "PID" and words:
        types = [(t, x, y) for t, x, y in words if t in INSTRUMENT_TYPES]
        nums = [(t, x, y) for t, x, y in words if LOOP_NUMBER.match(t)]
        for t, x, y in types:
            best, best_d = None, 45.0
            for nt, nx, ny in nums:
                if abs(nx - x) < 22 and (ny - y) > -5:      # centred, at/below
                    d = math.hypot(nx - x, ny - y)
                    if d < best_d:
                        best_d, best = d, nt
            if best:
                tags.add(f"{system}-{t}{best}")

    return tags


def split_tag(tag: str):
    """'27-PT4805A' -> ('27', 'PT', '4805A')."""
    m = re.match(r"(\d{2})-([A-Z]{1,4})(\d.*)$", tag)
    if not m:
        return ("?", "?", tag)
    return m.group(1), m.group(2), m.group(3)


# --------------------------------------------------------------------------
# Optional Google Vision OCR fallback (scanned drawings only)
# --------------------------------------------------------------------------

def ocr_pages_with_vision(path: Path, dpi: int = 200) -> str:
    """
    OCR a scanned PDF with Google Cloud Vision (document text detection).

    Only needed for drawings that have NO text layer. Requires:
        pip install google-cloud-vision pymupdf
        set GOOGLE_APPLICATION_CREDENTIALS=path\\to\\service-account.json

    Rasterises each page with PyMuPDF and sends it to Vision. Imported
    lazily so the main pipeline runs without these packages installed.
    """
    import fitz  # PyMuPDF, for rasterising pages
    from google.cloud import vision

    client = vision.ImageAnnotatorClient()
    out = []
    doc = fitz.open(path)
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        image = vision.Image(content=pix.tobytes("png"))
        resp = client.document_text_detection(image=image)
        if resp.error.message:
            raise RuntimeError(resp.error.message)
        out.append(resp.full_text_annotation.text)
    return "\n".join(out)


# --------------------------------------------------------------------------
# Register + reconciliation
# --------------------------------------------------------------------------

@dataclass
class TagInfo:
    system: str
    disc: str
    category: str
    pid_files: set[str] = field(default_factory=set)
    scd_files: set[str] = field(default_factory=set)


def build_register(drawings: list[Drawing], use_vision: bool):
    register: dict[str, TagInfo] = {}
    for d in drawings:
        try:
            tags = extract_tags(d.path, d.system, d.doc_type, use_vision)
        except Exception as e:                       # keep going on a bad file
            print(f"  ! failed on {d.name}: {e}")
            continue
        print(f"  {d.doc_type:3}  sys {d.system:>3}  {len(tags):3} tags  {d.name}")
        for tag in tags:
            sysn, disc, _ = split_tag(tag)
            info = register.setdefault(
                tag, TagInfo(system=sysn, disc=disc,
                             category=TYPE_CATEGORY.get(disc, "other")))
            (info.pid_files if d.doc_type == "PID" else info.scd_files).add(d.name)
    return register


def status_of(info: TagInfo) -> str:
    if info.pid_files and info.scd_files:
        return "BOTH"
    if info.pid_files:
        return "PID_ONLY"
    return "SCD_ONLY"


def write_outputs(register: dict[str, TagInfo], out_dir: Path,
                  only_system: str | None):
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for tag in sorted(register):
        info = register[tag]
        if only_system and info.system != only_system:
            continue
        rows.append({
            "tag": tag,
            "system": info.system,
            "type": info.disc,
            "category": info.category,
            "status": status_of(info),
            "n_pid": len(info.pid_files),
            "n_scd": len(info.scd_files),
            "pid_files": ";".join(sorted(info.pid_files)),
            "scd_files": ";".join(sorted(info.scd_files)),
        })

    # tag_register.csv + .json
    reg_csv = out_dir / "tag_register.csv"
    with reg_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["tag", "system", "type", "category", "status",
                            "n_pid", "n_scd", "pid_files", "scd_files"])
        w.writeheader()
        w.writerows(rows)
    (out_dir / "tag_register.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # reconciliation.csv (same rows, focused on the comparison view)
    rec_csv = out_dir / "reconciliation.csv"
    with rec_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["system", "tag", "type", "status"])
        for r in sorted(rows, key=lambda r: (r["system"], r["status"], r["tag"])):
            w.writerow([r["system"], r["tag"], r["type"], r["status"]])

    # per-system summary
    summary = defaultdict(lambda: {"BOTH": 0, "PID_ONLY": 0, "SCD_ONLY": 0})
    for r in rows:
        summary[r["system"]][r["status"]] += 1
    sum_csv = out_dir / "reconciliation_summary.csv"
    with sum_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["system", "common", "pid_only", "scd_only",
                    "pct_common"])
        for sysn in sorted(summary):
            s = summary[sysn]
            total = s["BOTH"] + s["PID_ONLY"] + s["SCD_ONLY"]
            pct = round(100 * s["BOTH"] / total, 1) if total else 0.0
            w.writerow([sysn, s["BOTH"], s["PID_ONLY"], s["SCD_ONLY"], pct])

    return reg_csv, rec_csv, sum_csv, summary


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build the Huldra tag register "
                                             "and P&ID/SCD reconciliation.")
    ap.add_argument("--raw", default="data/raw", type=Path,
                    help="root folder of raw drawings (default: data/raw)")
    ap.add_argument("--out", default="reports", type=Path,
                    help="output folder (default: reports)")
    ap.add_argument("--system", default=None,
                    help="limit outputs to one system, e.g. 27")
    ap.add_argument("--vision", action="store_true",
                    help="enable Google Vision OCR fallback for scanned PDFs")
    args = ap.parse_args()

    print(f"Scanning {args.raw} ...")
    drawings = discover_drawings(args.raw)
    n_pid = sum(d.doc_type == "PID" for d in drawings)
    n_scd = sum(d.doc_type == "SCD" for d in drawings)
    print(f"Found {len(drawings)} drawings  ({n_pid} P&ID, {n_scd} SCD)\n")

    register = build_register(drawings, use_vision=args.vision)
    reg_csv, rec_csv, sum_csv, summary = write_outputs(
        register, args.out, args.system)

    print(f"\nWrote:\n  {reg_csv}\n  {rec_csv}\n  {sum_csv}\n"
          f"  {args.out / 'tag_register.json'}")
    print("\nPer-system reconciliation:")
    print(f"  {'sys':>4}  {'common':>6}  {'P&ID only':>9}  {'SCD only':>8}")
    for sysn in sorted(summary):
        s = summary[sysn]
        print(f"  {sysn:>4}  {s['BOTH']:>6}  {s['PID_ONLY']:>9}  {s['SCD_ONLY']:>8}")


if __name__ == "__main__":
    main()