"""
Shared data discovery — importable WITHOUT side effects.

Why this module exists: hazop.py used to do `from system_analysis import
find_systems`. But system_analysis.py is a PAGE script — importing it
executes its whole top-level Streamlit body, so the FIRST click on the
HAZOP page rendered System-analyse instead (second click worked, because
the module was then cached). Rule of thumb this enforces: pages import
from shared modules; pages never import from pages.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import PID_DIR, SCD_DIR


def find_systems() -> dict:
    """Systems that have BOTH a P&ID and an SCD, keyed by system code."""
    def scan(d: Path) -> dict:
        out = {}
        for f in sorted(list(d.glob("*.PDF")) + list(d.glob("*.pdf"))):
            m = re.search(r"H[A-Z](\d{2})", f.stem)
            if m:
                out.setdefault(m.group(1), f)
        return out
    pid, scd = scan(PID_DIR), scan(SCD_DIR)
    return {s: (pid[s], scd[s]) for s in sorted(set(pid) & set(scd))}