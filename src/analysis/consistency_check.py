"""P&ID <-> SCD consistency check."""
from __future__ import annotations
import csv
from pathlib import Path


def check_consistency(pid_objs, scd_objs) -> dict:
    pid = {o.tag for o in pid_objs}
    scd = {o.tag for o in scd_objs}
    return {
        "both": sorted(pid & scd),
        "pid_only": sorted(pid - scd),
        "scd_only": sorted(scd - pid),
    }


def write_flagged_issues(result: dict, path: Path):
    """SCD-only tags are the primary flags: logic references not on the P&ID."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "issue", "severity", "note"])
        for t in result["scd_only"]:
            w.writerow([t, "in SCD logic, not found on P&ID", "review",
                        "missing tag, extraction miss, or different system"])
        for t in result["pid_only"]:
            w.writerow([t, "on P&ID, no role in SCD logic", "info",
                        "often expected (local indicator, position switch, relief)"])
    return path