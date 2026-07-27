"""
Symbol ↔ text reconciliation: a local, offline second opinion on rule findings.

The rule screening runs on the DEXPI/text model, where a valve that exists on
the sheet as a symbol only — with no readable tag — is invisible. That is the
exact blind spot behind every "missing X" finding: absence in the model cannot
be told apart from an extraction miss. `ai/hazop_vision.vision_check_finding`
already asks a cloud model to look at the sheet; this module does the same job
with the LOCAL gatevalve-ai CNN detections, so it costs no API call, runs
offline and is deterministic.

The bridge is coordinates. CNN detections carry `bbox_orig` in full-page
pixels at the render DPI (see gatevalve-ai/classify_drawing.py); text-tag
boxes from extraction.tag_locator.locate_tags are full-page pixels at dpi/72.
At a shared DPI the two live in the same pixel space; `dpi_scale` rescales the
detections when they were produced at a different DPI.

ASYMMETRIC, like the vision check: a detected-but-untagged valve near a finding
can WEAKEN it (the "missing" thing may be drawn, just untagged — verify on the
sheet). A detection never STRENGTHENS a finding, because the CNN has its own
misses; absence of a detection proves nothing. Only R2 (missing action valve)
is a genuine match — the CNN detects valves, not PSVs (R1) or instrument
bubbles (R3), and R4–R7 are about the SCD sheet, not this one.
"""
from __future__ import annotations

import json
from pathlib import Path

# CNN classes that represent an actuated/manual line valve — the kind an
# XV/ESV action valve (R2) would be drawn as. Reducers and check valves are
# excluded: a check valve is not an "action" valve, a reducer is not a valve.
_ACTION_VALVE_CLASSES = {
    "gate_open", "gate_closed", "ball_valve", "ball_open", "ball_closed",
    "globe_valve", "butterfly_valve", "other_valve",
}
# All valve-ish classes, for the drawing-wide "untagged symbols" overlay.
_VALVE_CLASSES = _ACTION_VALVE_CLASSES | {"check_valve"}


def load_detections(stem: str, results_dir: str | Path) -> list[dict] | None:
    """The cached `{stem}_detections.json` from a Drawing-analysis run, or
    None if the CNN has not been run on this drawing yet."""
    p = Path(results_dir) / f"{stem}_detections.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None


def _det_center(d: dict, scale: float) -> tuple[float, float]:
    x0, y0, x1, y1 = d["bbox_orig"]
    return ((x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale)


def _tag_centers(boxes_by_tag: dict) -> list[tuple[float, float]]:
    out = []
    for boxes in boxes_by_tag.values():
        for (x, y, w, h) in boxes:
            out.append((x + w / 2, y + h / 2))
    return out


def _near(a, b, radius: float) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= radius * radius


def untagged_valves(detections: list[dict], valve_tag_boxes: dict,
                    dpi_scale: float = 1.0, match_px: float = 90.0,
                    min_conf: float = 0.0,
                    confident_only: bool = True) -> list[dict]:
    """CNN valve detections with NO text-tagged valve nearby. NOTE this is not
    the same as an extraction error: most hand valves on a P&ID are symbol-only
    BY DESIGN and carry no tag. The overlay shows WHERE the drawing holds valve
    symbols the text model can't see — the exact places a 'missing valve'
    finding could be symbol-only rather than a true gap. Each item carries a
    pixel centre (`cx`,`cy`) in the text-layer DPI, ready to overlay."""
    tag_centers = _tag_centers(valve_tag_boxes)
    out = []
    for d in detections:
        if d.get("cls") not in _VALVE_CLASSES or d.get("conf", 0) < min_conf:
            continue
        if confident_only and d.get("tier", "sikker") != "sikker":
            continue                                # skip the "mulig" tier
        c = _det_center(d, dpi_scale)
        if any(_near(c, tc, match_px) for tc in tag_centers):
            continue                                # explained by a text tag
        out.append({**d, "cx": c[0], "cy": c[1]})
    return out


def crosscheck_finding(finding: dict, detections: list[dict] | None,
                       anchor_boxes: dict, valve_tag_boxes: dict,
                       dpi_scale: float = 1.0, radius_px: float = 260.0,
                       match_px: float = 90.0) -> dict:
    """Local second opinion on ONE finding.

    Returns {"applies", "seen", "note", "boxes"} where `boxes` are (x,y,w,h)
    of untagged valve symbols near the finding's anchor — drawable markers.
    `applies` is False for rules the CNN cannot speak to (honest by design).
    """
    if finding.get("rule") != "R2" or not detections:
        return {"applies": False, "seen": False, "note": "", "boxes": []}

    anchors = _tag_centers({t: anchor_boxes.get(t, [])
                            for t in finding.get("tags", [])})
    if not anchors:
        return {"applies": True, "seen": False, "boxes": [],
                "note": "The trip tag could not be located in the text layer, "
                        "so the CNN neighbourhood cannot be checked."}

    known = _tag_centers(valve_tag_boxes)
    hits = []
    for d in detections:
        if d.get("cls") not in _ACTION_VALVE_CLASSES:
            continue
        c = _det_center(d, dpi_scale)
        if not any(_near(c, a, radius_px) for a in anchors):
            continue                                # not near this finding
        if any(_near(c, k, match_px) for k in known):
            continue                                # already a tagged valve
        hits.append({**d, "cx": c[0], "cy": c[1]})

    boxes = [(d["cx"] - 55, d["cy"] - 55, 110, 110) for d in hits]
    if hits:
        note = (f"⚠️ The symbol model detected {len(hits)} untagged "
                f"valve symbol(s) near this safety function — the missing "
                f"action valve MAY be drawn but symbol-only (text-extraction "
                f"miss). Verify on the drawing.")
    else:
        note = ("The symbol model saw no untagged valve near the anchor "
                "either — but the CNN has its own misses, so this does not "
                "confirm the finding; it stays a screening candidate.")
    return {"applies": True, "seen": bool(hits), "note": note, "boxes": boxes}


if __name__ == "__main__":                                  # smoke test
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from analysis.hazop_dexpi import load_dexpi_model
    from analysis.rule_screening import screen, dedupe
    from extraction.tag_locator import locate_tags

    ROOT = Path(__file__).resolve().parents[2]
    RESULTS = ROOT / "gatevalve-ai" / "results"
    for xml in sorted((ROOT / "data" / "raw").rglob("*.DGN.xml")):
        stem = xml.stem.replace(".DGN", "")
        dets = load_detections(stem, RESULTS)
        if not dets:
            continue
        m = load_dexpi_model(xml)
        fs = [f for f in dedupe(screen(m["tag_graph"], m["objects"],
                                       m["sections"])) if f["rule"] == "R2"]
        pdfs = list((ROOT / "data" / "raw").rglob(f"{stem}.[pP][dD][fF]"))
        if not (fs and pdfs):
            continue
        valve_tags = [o.tag for o in m["objects"]
                      if o.type_code in {"XV", "ESV", "PV", "LV", "FV", "HV"}]
        vboxes = locate_tags(pdfs[0], valve_tags, dpi=200)
        print(f"\n{stem}: {len(fs)} R2 findings, {len(dets)} detections")
        for f in fs:
            aboxes = locate_tags(pdfs[0], f["tags"], dpi=200)
            cc = crosscheck_finding(f, dets, aboxes, vboxes)
            print(f"  {f['tags']}: seen={cc['seen']} — {cc['note'][:70]}")
