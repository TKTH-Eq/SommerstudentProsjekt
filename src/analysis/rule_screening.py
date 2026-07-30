"""
Rule screening: findings the drawing does NOT show — anchored to standards.

The HAZOP worksheet describes deviations for what IS on the drawing. This
module finds what seems to be MISSING: a pressure-controlled section with
no relief path, a trip function with no actuation, a section with no
pressure monitoring. That capability provably requires structured data —
from a PDF, the absence of a line cannot be distinguished from an
extraction miss (the 45 % recall gap), which is why this module runs on the
DEXPI model only.

STANDARD REFERENCES ARE INDICATIVE. Each finding carries a pointer to the
governing standard family (NORSOK P-001 pressure protection / S-001
technical safety / I-001 instrumentation; API 521 for relief philosophy),
NOT a verified clause number. A discipline engineer must confirm both the
finding and the reference before any use beyond screening — the module
says so in every output row. Findings are screening candidates, not
non-conformities.

Rules are deliberately few and conservative (structural absence only, no
sizing, no process judgement):

  R1  MISSING RELIEF PATH    section contains pressure control/measurement
                             but no PSV/PSE among its members
  R2  TRIP WITHOUT ACTION    an SHH/SLL trip function with no XV/valve
                             reachable downstream in the graph
  R3  BLIND SECTION          section with ≥4 members but no pressure
                             measurement at all
  R8  VALVE WITHOUT FEEDBACK an actuated shutdown valve (XV/ESV) whose loop
                             has no position switch (ZS/ZL) — the safety
                             logic cannot confirm the valve reached position
  R9  TRIP WITHOUT VOTING     a trip sensor (SHH/SLL) that is the only leg in
                             its loop — no redundant sensor for voting

Each finding lists the REAL tags that triggered it, so the viewer can mark
the location on the drawing.
"""
from __future__ import annotations

import sys

import networkx as nx

if __name__ == "__main__" and __package__ is None:      # direct run support
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_VERIFY = ("Indicative reference — a discipline engineer must confirm both "
           "the finding and the clause.")

_PRESSURE_TYPES = {"PT", "PI", "PIC", "PIT", "PDI", "PDT", "PV", "PSH", "PSL"}
_RELIEF_TYPES = {"PSV", "PSE"}
_TRIP_TYPES = {"LSHH", "PSHH", "LSH", "PSH", "LSL", "FSH", "LSLL", "PSLL"}
_ACTION_TYPES = {"XV", "ESV", "XY"}
_ONOFF_VALVES = {"XV", "ESV"}               # actuated on/off (shutdown) valves
_POS_FEEDBACK = {"ZS", "ZL", "ZSH", "ZSL", "ZI", "ZT"}   # valve position switch/indication


def screen(graph: nx.DiGraph, objects, sections: dict) -> list[dict]:
    """Findings over one drawing's DEXPI model.

    graph/objects/sections come straight from hazop_dexpi.load_dexpi_model.
    Returns [{rule, title, severity, tags, section, description,
              recommendation, standard}] — tags are real extracted tags,
    usable as anchors for on-drawing markers.
    """
    by_tag = {o.tag: o for o in objects}
    findings: list[dict] = []

    # ---- R1 + R3: per section ----------------------------------------------
    for name, members in (sections or {}).items():
        types = {o.type_code for o in members if o.type_code}
        p_tags = sorted(o.tag for o in members if o.type_code in _PRESSURE_TYPES)
        relief = sorted(o.tag for o in members if o.type_code in _RELIEF_TYPES)
        if p_tags and not relief:
            findings.append({
                "rule": "R1", "title": "Possible missing relief path",
                "severity": "high", "section": name, "tags": p_tags[:6],
                "description": f"The section has pressure measurement/control "
                               f"({', '.join(p_tags[:4])}) but no PSV/PSE "
                               f"among its members.",
                "recommendation": "Verify on the drawing or an adjacent sheet "
                                  "whether relief exists outside the section, "
                                  "or is genuinely missing.",
                "standard": f"NORSOK P-001 / API 521 (pressure protection). "
                            f"{_VERIFY}",
            })
        if len(members) >= 4 and not (types & (_PRESSURE_TYPES | _RELIEF_TYPES)):
            findings.append({
                "rule": "R3", "title": "Section without pressure monitoring",
                "severity": "low", "section": name,
                "tags": sorted(o.tag for o in members)[:6],
                "description": f"{len(members)} components with no pressure "
                               f"measurement anywhere in the section.",
                "recommendation": "May be correct (a drain, for example) — "
                                  "confirm that monitoring is not required.",
                "standard": f"NORSOK I-001 (instrumentation). {_VERIFY}",
            })

    # ---- R2: trip functions without an actuation path -----------------------
    for o in objects:
        if o.type_code not in _TRIP_TYPES or o.tag not in graph:
            continue
        down = nx.descendants(graph, o.tag)
        acts = sorted(t for t in down
                      if by_tag.get(t) and by_tag[t].type_code in _ACTION_TYPES)
        if not acts:
            findings.append({
                "rule": "R2", "title": "Safety function without action path",
                "severity": "high", "section": "",
                "tags": [o.tag],
                "description": f"{o.tag} ({o.type_code}) has no XV/ESV "
                               f"downstream in the model.",
                "recommendation": "The action may live in SCD logic or on "
                                  "another sheet — verify that the function "
                                  "actually triggers an action.",
                "standard": "NORSOK I-005:2013+AC:2016, B.2.3.2 — shutdown "
                            "functions shall be implemented on the SCD as "
                            "logical connections between the relevant outputs "
                            "and inputs (paraphrased). Clause verified "
                            "against the standard text.",
            })

    # ---- R8 + R9: per loop (redundancy legs A/B/C share a loop) -------------
    from collections import defaultdict
    loops: dict[str, list] = defaultdict(list)
    for o in objects:
        loops[o.loop].append(o)

    for o in objects:
        # R8: actuated shutdown valve with no position feedback in its loop.
        if o.type_code in _ONOFF_VALVES:
            sibling_types = {s.type_code for s in loops[o.loop]}
            if not (sibling_types & _POS_FEEDBACK):
                findings.append({
                    "rule": "R8",
                    "title": "Actuated valve without position feedback",
                    "severity": "medium", "section": o.loop,
                    "tags": [o.tag],
                    "description": f"{o.tag} ({o.type_code}) is an actuated "
                                   f"shutdown valve, but its loop has no "
                                   f"position switch (ZS/ZL) — the logic "
                                   f"cannot confirm the valve reached "
                                   f"position.",
                    "recommendation": "The position switch may be symbol-only "
                                      "(absent from the text layer) or on "
                                      "another sheet — verify on the drawing "
                                      "that ZS/ZL exists, or that feedback is "
                                      "not required.",
                    "standard": f"NORSOK I-001 / I-005 (position indication "
                                f"for SIS valves). {_VERIFY}",
                })
        # R9: trip sensor that is the only leg in its loop (no voting).
        if o.type_code in _TRIP_TYPES:
            legs = [s for s in loops[o.loop] if s.type_code == o.type_code]
            if len(legs) < 2:
                findings.append({
                    "rule": "R9",
                    "title": "Shutdown function without redundancy",
                    "severity": "low", "section": o.loop,
                    "tags": [o.tag],
                    "description": f"{o.tag} ({o.type_code}) is the only "
                                   f"{o.type_code} sensor in its loop — no "
                                   f"redundant sensor for voting (1oo1).",
                    "recommendation": "Whether voting is required depends on "
                                      "the SIL classification (IEC 61511) — "
                                      "confirm against the SRS/SIL analysis "
                                      "that 1oo1 is acceptable for this "
                                      "function.",
                    "standard": f"IEC 61511 / NORSOK I-002 (redundancy and "
                                f"voting per SIL). {_VERIFY}",
                })

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: (order[f["severity"]], f["rule"]))


if __name__ == "__main__":
    import os, sys
    from pathlib import Path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from analysis.hazop_dexpi import load_dexpi_model
    for xml in sorted(Path("data/raw").rglob("*.DGN.xml")):
        m = load_dexpi_model(xml)
        fs = screen(m["tag_graph"], m["objects"], m["sections"])
        if fs:
            print(f"\n{xml.stem.replace('.DGN', '')}: {len(fs)} findings")
            for f in fs[:4]:
                print(f"  [{f['rule']}/{f['severity']}] {f['title']} — "
                      f"{', '.join(f['tags'][:3])}")


# ---------------------------------------------------------------------------
# I-005 Annex B coverage rules: P&ID vs SCD (verified clause references)
# ---------------------------------------------------------------------------
# These clauses were read directly from NORSOK I-005:2013+AC:2016 and are
# PARAPHRASED here (the standard text is copyright protected). References
# below are therefore VERIFIED — unlike the indicative P-001/I-001 pointers
# above. Honest caveat baked into every finding: a tag "missing on the SCD"
# may be a real coverage gap OR a text-layer extraction miss on the SCD
# sheet; the finding is a screening candidate either way.

_MEASURING = None      # category == "input" is the proxy (transmitters etc.)
_ACTUATED_VALVES = {"XV", "ESV", "XY", "PV", "LV", "FV", "HV", "TV"}
_SHUTDOWN_FUNCS = {"LSHH", "PSHH", "LSH", "LSL", "PSH", "FSH"}


def screen_scd_coverage(pid_objects, scd_objects) -> list[dict]:
    """Findings for I-005 Annex B coverage: what the P&ID shows that the
    SCD (extraction) does not. Inputs are EngineeringObject lists from the
    two sources separately."""
    scd_tags = {o.tag for o in scd_objects}
    findings: list[dict] = []

    def _gap(objs, title, rule, clause, paraphrase):
        missing = sorted(o.tag for o in objs if o.tag not in scd_tags)
        if missing:
            findings.append({
                "rule": rule, "title": title, "severity": "medium",
                "section": "P&ID↔SCD", "tags": missing[:8],
                "description": f"{len(missing)} components on the P&ID are "
                               f"not found in the SCD extraction: "
                               f"{', '.join(missing[:5])}"
                               + (" …" if len(missing) > 5 else "") + ".",
                "recommendation": "Either a real coverage gap against the "
                                  "clause, or an extraction miss on the SCD "
                                  "sheet — verify against the SCD drawing.",
                "standard": f"NORSOK I-005:2013+AC:2016, {clause} — "
                            f"{paraphrase} (paraphrased). Clause verified "
                            f"against the standard text.",
            })

    # B.2.2 applies to instruments WITH an input to the control system — local
    # indicators (PI/FI/TI/LI/PDI without a transmitter) are excluded to avoid
    # false findings; a conservative choice, documented here.
    _LOCAL_ONLY = {"PI", "FI", "TI", "LI", "PDI"}
    _gap([o for o in pid_objects if o.category == "input"
          and o.type_code not in _LOCAL_ONLY],
         "Measuring instrument not found on the SCD", "R4", "B.2.2",
         "all measuring instruments with an input to the control system "
         "shall be shown on the SCD")
    _gap([o for o in pid_objects if o.type_code in _ACTUATED_VALVES],
         "Actuated valve not found on the SCD", "R5", "B.2.1.3",
         "remotely operated valves with an actuator, including on/off and "
         "control valves, shall be included on the SCD")
    _gap([o for o in pid_objects if o.type_code in _SHUTDOWN_FUNCS],
         "Shutdown function not found on the SCD", "R6", "B.2.3.2",
         "all shutdown functions within PCS and PSD shall be implemented on "
         "the SCDs")
    # control functions: type codes ending in IC (PIC, LIC, FIC, TIC …)
    import re as _re
    _gap([o for o in pid_objects
          if o.type_code and _re.match(r"^[A-Z]{1,3}IC$", o.type_code)],
         "Control function not found on the SCD", "R7", "B.2.3.1",
         "the SCD shall include all control functions and their mutual "
         "exchange of status, measured variables, interlocks and "
         "suppression")
    return findings


# Fluid annotation (slice of "media-aware relevance"): ANNOTATE, never
# filter — the codes are assumptions (see the fluid-code table in the
# report), so they inform the team without hiding rows.
FLUID_MEANINGS = {  # subset of Table 1; basis/confidence per report
    "PV": "Process Vapour (assumed, moderate)", "PL": "Process Liquid (assumed, moderate)",
    "VF": "Vent/Flare gas (assumed, moderate)", "DC": "Drain Closed (assumed, moderate)",
    "WS": "Water Service (assumed, low-moderate)", "WF": "Water Fresh (assumed, low-moderate)",
    "GF": "Gas Fuel (assumed, low-moderate)", "AI": "Air Instrument (assumed, moderate)",
    "GI": "Gas Injection (assumed, low-moderate)", "OL": "Oil Line (assumed, low-moderate)",
}


# ---------------------------------------------------------------------------
# Triage: rank + de-duplicate findings so a reviewer sees the worst first.
# ---------------------------------------------------------------------------
# Fluid hazard weight (relative, for ranking ONLY — not an ISO 17776 rating).
# Hydrocarbon/flare service dominates the consequence of a missing safeguard;
# utilities (water, air) sit lowest. Unknown codes get a neutral-ish weight so
# an unclassified line never silently sinks a finding.
FLUID_HAZARD = {
    "PV": 1.0, "PL": 1.0, "VF": 1.0, "GF": 1.0, "GI": 1.0, "OL": 1.0,
    "OF": 1.0, "GL": 1.0,                       # hydrocarbon / flare / fuel
    "AI": 0.5, "AP": 0.5,                        # instrument / plant air
    "WS": 0.3, "WF": 0.3, "WI": 0.3, "WC": 0.3, "WD": 0.3,   # water services
    "DC": 0.6,                                   # closed drain (may carry HC)
}
_SEV_BASE = {"high": 3.0, "medium": 2.0, "low": 1.0}


def hazard_score(finding: dict, fluid_codes: list[str] | None = None) -> float:
    """Screening priority 1.0–5.0: severity, lifted by the hazard of the
    fluid on the finding's connected lines. Ranking aid only — never a
    substitute for the discipline engineer's consequence assessment."""
    base = _SEV_BASE.get(finding.get("severity", "low"), 1.0)
    worst = max((FLUID_HAZARD.get(c, 0.6) for c in (fluid_codes or [])),
                default=0.5)
    return round(min(base * (1.0 + worst), 5.0), 2)


def dedupe(findings: list[dict]) -> list[dict]:
    """Drop exact duplicates — same rule, section and tag set. Different
    rules on the same tags are kept: they say different things."""
    seen, out = set(), []
    for f in findings:
        key = (f["rule"], f.get("section", ""), tuple(sorted(f["tags"])))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def screen_all(raw_dir) -> list[dict]:
    """Run the DEXPI structural rules (R1–R3, R8–R9) over EVERY drawing that
    has a DEXPI model, tagging each finding with its drawing and system — the
    plant-wide roll-up behind the compliance dashboard. Coverage rules (R4–R7)
    need a P&ID↔SCD pair and are left to the per-drawing view."""
    import re as _re
    from pathlib import Path as _P
    from analysis.hazop_dexpi import load_dexpi_model
    rows: list[dict] = []
    for xml in sorted(_P(raw_dir).rglob("*.DGN.xml")):
        try:
            m = load_dexpi_model(xml)
            fs = dedupe(screen(m["tag_graph"], m["objects"], m["sections"]))
        except Exception:                                   # noqa: BLE001
            continue
        stem = xml.stem.replace(".DGN", "")
        for f in fs:
            sysn = "?"
            for t in f.get("tags", []):
                mm = _re.match(r"^(\d{2})", str(t))
                if mm:
                    sysn = mm.group(1)
                    break
            rows.append({**f, "drawing": stem, "system": sysn})
    return rows


def fluids_for_tags(xml_path, tags: list[str]) -> list[str]:
    """Fluid codes on lines anchored by these tags, via the plant-model
    line-anchor helper. Codes come from the line tags themselves
    (4\"-PV-274599 -> PV)."""
    from pathlib import Path as _Path
    from analysis.plant_model import _line_anchor_tags
    import re as _re
    anchors = _line_anchor_tags(_Path(xml_path), set(tags))
    codes = []
    for line, ts in anchors.items():
        if any(t in tags for t in ts):
            m = _re.match(r'^[^-]*-([A-Z]{2})-', line)
            if m and m.group(1) not in codes:
                codes.append(m.group(1))
    return codes