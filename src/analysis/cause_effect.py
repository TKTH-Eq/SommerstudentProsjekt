"""
Cause & effect from the SCD — manually extracted, machine-checked.

The dependency graph says what CAN be connected; the SCD's cause-and-effect
logic says what is DESIGNED to happen: "LAHH trips -> close XV". That logic
is printed on the SCD sheets (PDF), so this module ingests a small CSV that
an engineer fills in by reading the sheet — the honest bridge until the
extraction is automated. Format (data/cause_effect/*.csv):

    drawing,cause_tag,effect_tag,function,source,verified,note

    cause_tag  : the initiating function (e.g. 27-PSH 4811)
    effect_tag : the actuated element   (e.g. 27-XV 4813)
    function   : short action text      (e.g. "PSD: steng innløp")
    source     : where on the sheet     (e.g. "SCD E-101, C&E-felt B4")
    verified   : ja/nei — nei renders with an explicit warning in the app

Every tag is validated against the extracted register; tags are normalised
(spaces stripped, upper-cased) so "27-PT 4804" and "27-PT4804" match. Rows
whose tags are unknown are kept but flagged — never silently dropped, never
silently trusted.

Pure functions, no Streamlit — unit-testable headless.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

CE_DIR = Path("data/cause_effect")

_COLS = ["drawing", "cause_tag", "effect_tag", "function", "source",
         "verified", "note"]


def _norm(tag: str) -> str:
    return (tag or "").replace(" ", "").upper()


def load_ce(path: Path | str = CE_DIR) -> list[dict]:
    """Read every *.csv under `path` (or a single file). Returns raw rows
    with whitespace-trimmed fields; missing optional fields become ''."""
    p = Path(path)
    files = sorted(p.glob("*.csv")) if p.is_dir() else ([p] if p.exists() else [])
    rows: list[dict] = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if not (r.get("cause_tag") or "").strip():
                    continue                       # blank/comment-ish line
                rows.append({c: (r.get(c) or "").strip() for c in _COLS}
                            | {"file": f.name})
    return rows


def validate_ce(rows: list[dict], by_tag: dict) -> dict:
    """Resolve tags against the register (normalised match). Returns
    {rows, index, stats}:

      rows   : each row + cause/effect (canonical register tag or None)
               + ok (both resolved) + verified (bool)
      index  : {"effects_of": {cause: [row..]}, "causes_of": {effect: [row..]}}
               canonical-tag keyed, resolved rows only
      stats  : counts for honest display
    """
    canon = {_norm(t): t for t in by_tag}
    out = []
    effects_of = defaultdict(list)
    causes_of = defaultdict(list)
    for r in rows:
        cause = canon.get(_norm(r["cause_tag"]))
        effect = canon.get(_norm(r["effect_tag"]))
        row = dict(r, cause=cause, effect=effect,
                   ok=bool(cause and effect),
                   verified=r["verified"].lower() in ("ja", "yes", "y", "1"))
        out.append(row)
        if row["ok"]:
            effects_of[cause].append(row)
            causes_of[effect].append(row)
    stats = {"rows": len(out),
             "resolved": sum(1 for r in out if r["ok"]),
             "unknown_tags": sorted({r["cause_tag"] for r in out if not r["cause"]}
                                    | {r["effect_tag"] for r in out if not r["effect"]}),
             "verified": sum(1 for r in out if r["ok"] and r["verified"]),
             "files": sorted({r["file"] for r in out})}
    return {"rows": out, "index": {"effects_of": dict(effects_of),
                                   "causes_of": dict(causes_of)},
            "stats": stats}


def ce_lines_for(tag: str, index: dict, max_lines: int = 6) -> list[str]:
    """Human-readable designed-logic lines for one tag, for briefs/FACTS.
    Unverified rows are explicitly marked."""
    lines = []
    for r in index["effects_of"].get(tag, [])[:max_lines]:
        mark = "" if r["verified"] else " [UVERIFISERT]"
        lines.append(f"{tag} → {r['effect']}: {r['function'] or 'aksjon'}"
                     f" ({r['source'] or r['file']}){mark}")
    for r in index["causes_of"].get(tag, [])[:max_lines - len(lines)]:
        mark = "" if r["verified"] else " [UVERIFISERT]"
        lines.append(f"{tag} aktueres av {r['cause']}: "
                     f"{r['function'] or 'aksjon'}"
                     f" ({r['source'] or r['file']}){mark}")
    return lines


def designed_response_check(fault: str, index: dict,
                            active: list[str]) -> list[dict]:
    """Debrief helper: for the true fault, which designed effects exist and
    did they actually ring? [{effect, function, verified, observed}]"""
    act = {_norm(a) for a in active}
    return [{"effect": r["effect"], "function": r["function"],
             "verified": r["verified"],
             "observed": _norm(r["effect"]) in act}
            for r in index["effects_of"].get(fault, [])]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    rows = load_ce(sys.argv[1] if len(sys.argv) > 1 else CE_DIR)
    print(f"{len(rows)} rader lest")
    for r in rows[:10]:
        print(f"  {r['cause_tag']:14} -> {r['effect_tag']:14} "
              f"{r['function']}  [{r['verified'] or 'nei'}]")