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

Extraction (unified with the validated pipeline):
  * Tags are extracted by extraction.tag_extractor.extract_tags -- the SAME
    code path that is validated against the DEXPI ground truth in
    validate_against_dexpi.py (precision/recall figures in Results.md apply
    to this register directly).
  * Multi-page drawings (a handful of SCDs) are handled by running the same
    passes on every page and unioning the results.
  * Image-only drawings are handled by the shared Gemini vision reserve
    (pass c in the extractor), enabled with --vision / HULDRA_VISION=1.
    Requires GEMINI_API_KEY in .env; no other credentials.

Usage:
    python build_tag_register.py --raw data/raw --out reports
    python build_tag_register.py --raw data/raw --out reports --system 27
    python build_tag_register.py --raw data/raw --out reports --vision
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from extraction.tag_extractor import extract_tags as _validated_extract_tags


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

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

SYSTEM_TOKEN = re.compile(r"^H[A-Z](\d{1,3})", re.IGNORECASE)


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
# Tag extraction -- delegates to the validated pipeline
# --------------------------------------------------------------------------

def extract_tags(path: Path, system: str, doc_type: str,
                 use_vision: bool = False) -> set[str]:
    """Extract tags from one drawing via the validated extractor.

    Runs the validated page-1 extraction, plus the same passes on any
    additional pages (a handful of SCDs are multi-page). system and doc_type
    are kept in the signature for register bookkeeping; the extractor derives
    the system itself from the filename. The vision reserve is controlled
    globally via HULDRA_VISION (set in main() from --vision) and runs on
    page 1 only. Unprefixed vision twins are filtered out — the register
    keeps the canonical NN-prefixed form only.
    """
    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
    tags: set[str] = set()
    for page in range(n_pages):
        tags |= _validated_extract_tags(path, page=page)
    # The vision reserve adds unprefixed twins ("PT4805" alongside
    # "27-PT4805") so validation matches either written form. The register
    # wants the canonical prefixed form only — the twins would land as
    # system "?" and double-count components.
    return {t for t in tags if re.match(r"^\d{2,3}-", t)}


def split_tag(tag: str):
    """'27-PT4805A' -> ('27', 'PT', '4805A');  '27-4510PV' -> ('27', 'PV', '4510')."""
    m = re.match(r"(\d{2})-([A-Z]{1,4})(\d.*)$", tag)          # type-first
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r"(\d{2})-(\d{2,5})([A-Z]{1,3})$", tag)        # number-first
    if m:
        return m.group(1), m.group(3), m.group(2)
    return ("?", "?", tag)


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
                    help="enable the Gemini vision reserve for image-only drawings")
    args = ap.parse_args()

    if args.vision:
        os.environ["HULDRA_VISION"] = "1"

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