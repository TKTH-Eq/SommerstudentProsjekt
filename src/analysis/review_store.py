"""
src/analysis/review_store.py
=====================================================================
Remember which compositions a human confirmed, and which they rejected.

Why this exists: filters cannot tell a false detection apart from a different
way of drawing the same symbol. Both look like an unfamiliar composition, and
tightening a threshold removes them together — which is exactly what happened
when the CheckValve survey went from twenty-seven compositions down to three,
only one of which was a check valve.

Only a person looking at the picture can make that call. This module stores the
call so it is made once. Decisions are keyed on class plus composition, not on
which drawing the instance came from, so re-running the survey with different
settings keeps them.

A useful by-product: once a class has been reviewed, the confirmed share IS a
precision measurement for the detector on that class, obtained without anyone
annotating a dataset.

Pure functions, no Streamlit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CONFIRMED = "confirmed"
REJECTED = "rejected"


def decision_key(dexpi_class: str, composition_key: str) -> str:
    """Stable across survey runs: what it is, and what it is built from."""
    return f"{dexpi_class}|{composition_key}"


def load_decisions(path: Path | str) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        return {}


def save_decisions(decisions: dict[str, dict], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decisions, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path


def set_decision(decisions: dict[str, dict], dexpi_class: str,
                 composition_key: str, verdict: str, *,
                 note: str = "", instances: int = 0,
                 drawings: list[str] | None = None) -> dict[str, dict]:
    """Record one call. Returns the same dict, mutated, for chaining.

    The context is stored alongside the verdict — how many instances and which
    drawings — so the file is readable on its own and can be cited without
    re-running anything.
    """
    decisions[decision_key(dexpi_class, composition_key)] = {
        "verdict": verdict,
        "class": dexpi_class,
        "composition": composition_key,
        "instances": instances,
        "drawings": drawings or [],
        "note": note,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return decisions


def clear_decision(decisions: dict[str, dict], dexpi_class: str,
                   composition_key: str) -> dict[str, dict]:
    decisions.pop(decision_key(dexpi_class, composition_key), None)
    return decisions


def verdict_of(decisions: dict[str, dict], dexpi_class: str,
               composition_key: str) -> str | None:
    d = decisions.get(decision_key(dexpi_class, composition_key))
    return d.get("verdict") if d else None


def stats(decisions: dict[str, dict], dexpi_class: str | None = None) -> dict:
    """Counts, plus the detector precision they imply.

    `precision` is the share of reviewed compositions judged genuine. It is a
    precision over COMPOSITIONS, not over detections — a class can score badly
    here while most individual detections are correct, if the wrong ones happen
    to be varied. Report it as what it is.
    """
    rows = [d for d in decisions.values()
            if dexpi_class is None or d.get("class") == dexpi_class]
    confirmed = sum(1 for d in rows if d["verdict"] == CONFIRMED)
    rejected = sum(1 for d in rows if d["verdict"] == REJECTED)
    reviewed = confirmed + rejected
    inst_ok = sum(d.get("instances", 0) for d in rows
                  if d["verdict"] == CONFIRMED)
    inst_no = sum(d.get("instances", 0) for d in rows
                  if d["verdict"] == REJECTED)
    return {
        "confirmed": confirmed, "rejected": rejected, "reviewed": reviewed,
        "instances_confirmed": inst_ok, "instances_rejected": inst_no,
        "precision": confirmed / reviewed if reviewed else None,
        "instance_precision": (inst_ok / (inst_ok + inst_no)
                               if (inst_ok + inst_no) else None),
    }