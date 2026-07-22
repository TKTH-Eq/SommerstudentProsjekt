"""Persistence for HAZOP worksheets.

Streamlit session state dies with the browser tab; real HAZOP work spans
several meetings. This module stores each worksheet as one human-readable
JSON file under reports/hazop_store/, so edits and review status survive
restarts — and a worksheet diff between meetings is a plain git diff.

Design:
  * One file per worksheet, keyed by a caller-chosen id (e.g. the system
    number "27" or a drawing stem). Key is sanitised to a safe filename.
  * The worksheet payload is whatever the app keeps in session state today
    (list of row dicts / dict of sections) — this module does not interpret
    it, it just round-trips it. Excel export keeps working unchanged.
  * Atomic writes (tmp file + os.replace), so a crash mid-save never leaves
    a half-written worksheet.
  * Every save updates metadata (saved_at, n_saves) without touching rows.

Usage from a Streamlit page:

    from analysis.hazop_store import load_worksheet, save_worksheet

    if "hazop_rows" not in st.session_state:
        stored = load_worksheet(system)
        st.session_state.hazop_rows = (
            stored["data"] if stored else build_default_worksheet(system))

    ... user edits st.session_state.hazop_rows ...

    if st.button("Lagre arbeidsark"):
        path = save_worksheet(system, st.session_state.hazop_rows)
        st.success(f"Lagret ({path.name})")
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STORE_DIR = Path("reports") / "hazop_store"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_FORMAT_VERSION = 1


def _path_for(key: str) -> Path:
    safe = _SAFE.sub("_", str(key).strip()) or "worksheet"
    return STORE_DIR / f"{safe}.json"


def save_worksheet(key: str, data, meta: dict | None = None) -> Path:
    """Persist a worksheet. `data` must be JSON-serialisable (the same rows
    the app keeps in session state). Returns the file path written."""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(key)

    n_saves = 1
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            n_saves = int(old.get("meta", {}).get("n_saves", 0)) + 1
            created_at = old.get("meta", {}).get("created_at", created_at)
        except Exception:
            pass                                   # corrupt old file: overwrite

    payload = {
        "format_version": _FORMAT_VERSION,
        "key": str(key),
        "meta": {
            "created_at": created_at,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_saves": n_saves,
            **(meta or {}),
        },
        "data": data,
    }

    # atomic write: never leave a half-written worksheet behind
    fd, tmp = tempfile.mkstemp(dir=STORE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_worksheet(key: str) -> dict | None:
    """Return {'data': ..., 'meta': {...}} for a stored worksheet, or None
    if nothing has been saved for this key (or the file is unreadable)."""
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"data": payload.get("data"), "meta": payload.get("meta", {})}
    except Exception as e:                         # noqa: BLE001
        print(f"[hazop_store] could not read {path.name}: {e}")
        return None


def list_worksheets() -> list[dict]:
    """All stored worksheets, newest first: [{'key', 'saved_at', 'n_saves'}]."""
    if not STORE_DIR.exists():
        return []
    out = []
    for p in STORE_DIR.glob("*.json"):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            meta = payload.get("meta", {})
            out.append({"key": payload.get("key", p.stem),
                        "saved_at": meta.get("saved_at", ""),
                        "n_saves": meta.get("n_saves", 0)})
        except Exception:
            out.append({"key": p.stem, "saved_at": "(uleselig)", "n_saves": 0})
    return sorted(out, key=lambda w: w["saved_at"], reverse=True)


def delete_worksheet(key: str) -> bool:
    """Remove a stored worksheet. Returns True if a file was deleted."""
    path = _path_for(key)
    if path.exists():
        path.unlink()
        return True
    return False