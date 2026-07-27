"""
Persist a reviewer's disposition of a rule finding, so screening becomes a
reviewable record instead of a throwaway list that resets on every rerun.

A finding is a screening CANDIDATE — the whole module says so. What turns a
candidate into a closed loop is an engineer's judgement: accepted (a real gap
to follow up), rejected (a false positive, with the reason), or verified (the
safeguard exists on the drawing/SCD, just not in the extraction). We store
that judgement keyed by a STABLE finding id (rule + tags), so it survives a
rerun and can be exported alongside the findings.

Deliberately file-based (one JSON per drawing under reports/): no database,
no service — matches the rest of this project and keeps the record in the repo
next to the drawings it describes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from config import REPORTS
except Exception:                                           # noqa: BLE001
    REPORTS = Path(__file__).resolve().parents[2] / "reports"

_DIR = Path(REPORTS) / "finding_dispositions"

STATUSES = ("open", "accepted", "rejected", "verified")
STATUS_LABEL = {
    "open":     "⬜ Open (not reviewed)",
    "accepted": "🔴 Accepted — real gap to follow up",
    "rejected": "⚪ Rejected — false positive",
    "verified": "🟢 Verified — safeguard exists, extraction miss",
}


def finding_id(finding: dict) -> str:
    """Stable id for a finding: rule + its (sorted) anchor tags. Independent
    of ordering and of transient fields, so it matches across reruns."""
    tags = ",".join(sorted(finding.get("tags", []))[:4])
    return f"{finding.get('rule', '?')}:{finding.get('section', '')}:{tags}"


def _path(stem: str) -> Path:
    return _DIR / f"{stem}.json"


def load_dispositions(stem: str) -> dict:
    """{finding_id: {status, note, at}} for one drawing (empty if none)."""
    p = _path(stem)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def set_disposition(stem: str, fid: str, status: str,
                    note: str = "") -> dict:
    """Record (or clear) a disposition and persist. status 'open' with no
    note removes the entry so the store only holds real decisions."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    data = load_dispositions(stem)
    if status == "open" and not note:
        data.pop(fid, None)
    else:
        data[fid] = {"status": status, "note": note.strip(),
                     "at": datetime.now(timezone.utc).strftime(
                         "%Y-%m-%d %H:%M UTC")}
    _DIR.mkdir(parents=True, exist_ok=True)
    _path(stem).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data


def summarise(dispositions: dict) -> dict:
    """Count by status — for a one-line review-progress caption."""
    out = {s: 0 for s in STATUSES}
    for d in dispositions.values():
        out[d.get("status", "open")] = out.get(d.get("status", "open"), 0) + 1
    return out
