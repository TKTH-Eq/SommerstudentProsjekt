"""
Warm the vision second-opinion cache for every rule finding.

Evening-before demo routine, one command:

    python src/ai/warm_vision_checks.py            # all systems
    python src/ai/warm_vision_checks.py 27 24      # only these systems

Runs the same chain as the buttons in the Regelfunn tab (rule screening ->
vision_check_finding per finding, P&ID for R1-R3, SCD for R4-R7) and saves
each result with the same cache key the UI uses — so the presentation hits
disk, not the API. Requires GEMINI_API_KEY; skips findings already cached.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.discovery import find_systems
from extraction.tag_extractor import extract_tags, create_objects
from analysis.rule_screening import screen, screen_scd_coverage
from analysis.hazop_dexpi import load_dexpi_model
from ai.hazop_vision import vision_check_finding
from ai.ai_cache import load_vcheck, save_vcheck
from config import PID_DIR


def main() -> None:
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY mangler (.env)")
    want = set(sys.argv[1:])
    for sysno, (pid, scd) in find_systems().items():
        if want and sysno not in want:
            continue
        objs = (create_objects(extract_tags(str(pid)), "P&ID")
                + create_objects(extract_tags(str(scd)), "SCD"))
        findings = []
        xml = list(Path(PID_DIR).parent.rglob(f"{Path(pid).stem}.DGN.xml"))
        if xml:
            m = load_dexpi_model(xml[0])
            findings += screen(m["tag_graph"], m["objects"], m["sections"])
        findings += screen_scd_coverage(
            create_objects(extract_tags(str(pid)), "P&ID"),
            create_objects(extract_tags(str(scd)), "SCD"))
        if not findings:
            continue
        print(f"system {sysno}: {len(findings)} funn")
        for f in findings:
            target = scd if f["rule"] in ("R4", "R5", "R6", "R7") else pid
            vkey = (f"{Path(target).stem}|{f['rule']}|"
                    + ",".join(f["tags"][:4]))
            if load_vcheck(vkey):
                print(f"  [{f['rule']}] {f['tags'][0]}: 🗂️ allerede cachet")
                continue
            try:
                r = vision_check_finding(Path(target), f,
                                         [o.tag for o in objs])
                if r.get("ok"):
                    save_vcheck(vkey, r)
                mark = "⚠️ sett" if r.get("seen") else "ikke sett"
                print(f"  [{f['rule']}] {f['tags'][0]}: {mark}")
            except Exception as e:                          # noqa: BLE001
                print(f"  [{f['rule']}] {f['tags'][0]}: FEILET {e}")
    print("Ferdig — kontroller svarene i appen, og commit reports/ai_cache/.")


if __name__ == "__main__":
    main()