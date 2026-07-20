"""
Locate tags on the drawing: tag -> pixel boxes on the rendered PNG.

Mirrors how extraction.tag_extractor RECONSTRUCTS tags, because most tags
do not exist as single words on the sheet: an instrument bubble holds the
type letters ("PT") stacked over the number ("4805"), and the system
prefix ("27-") comes from the file name, not the drawing. Locating
"27-PT4805" therefore means: find a "PT" word with a "4805" word in the
same column (same proximity thresholds as the extractor), and box BOTH.
Single-word forms (hand valves like 27-4561PV, inline hyphenated tags)
are matched directly.

Coordinates come from pdfplumber word bboxes (PDF points) and are scaled
to raster pixels with dpi/72 — render and overlay share the source
document, so they always agree. Tags the text layer cannot see
(symbol-only) get no box, which is honest: "here" is only shown where
"here" is actually known.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

_X_TOL, _Y_TOL = 16, 50          # same column-window as tag_extractor


def _parse(tag: str):
    """'27-PT4805A' -> ('PT', '4805A') ; '27-4561PV' -> ('PV', '4561') ;
    None if the tag doesn't parse (equipment names etc. still get pass 1)."""
    t = re.sub(r"\s+", "", str(tag).upper())
    t = t.split("-", 1)[1] if re.match(r"^\d{2}-", t) else t
    m = re.match(r"^([A-Z]{1,4})-?(\d{2,4}[A-Z]?)$", t)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(\d{2,4})([A-Z]{1,4})$", t)
    if m:
        return m.group(2), m.group(1)
    return None


def _norm(t: str) -> str:
    return re.sub(r"[\s-]+", "", str(t).upper())


def locate_tags(pdf_path: str | Path, tags, dpi: int = 200) -> dict:
    """{tag: [(x, y, w, h), ...]} in PIXELS at the given dpi.
    Best effort — empty dict on failure, missing keys for unlocatable tags."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            words = pdf.pages[0].extract_words()
    except Exception:                                       # noqa: BLE001
        return {}
    sc = dpi / 72.0

    def box(*ws):
        x0 = min(w["x0"] for w in ws); x1 = max(w["x1"] for w in ws)
        t0 = min(w["top"] for w in ws); b1 = max(w["bottom"] for w in ws)
        return (x0 * sc, t0 * sc, (x1 - x0) * sc, (b1 - t0) * sc)

    by_text = defaultdict(list)
    for w in words:
        by_text[_norm(w["text"])].append(w)

    out: dict[str, list] = {}
    for tag in tags:
        # BUBBLE hits (type + number stacked or side-by-side) are the
        # component symbol; INLINE full-text hits may be mentions in the
        # NOTES column or line labels. Prefer bubbles when they exist —
        # a note mention must never shadow (or stand in for) the symbol.
        bubble, inline = [], []
        parsed = _parse(tag)
        if parsed:
            ty, num = parsed
            for tw in by_text.get(ty, []):
                for nw in by_text.get(num, []):
                    stacked = (abs(nw["x0"] - tw["x0"]) < _X_TOL
                               and abs(nw["top"] - tw["top"]) < _Y_TOL)
                    side = (abs(nw["top"] - tw["top"]) < 10
                            and -5 < nw["x0"] - tw["x1"] < 25)
                    if stacked or side:
                        bubble.append(box(tw, nw))
        t_full = _norm(tag)                      # hyphen already stripped
        t_nosys = t_full[2:] if re.match(r"^\d{2}-", str(tag).strip()) \
            else t_full
        for key in {t_full, t_nosys}:
            for w in by_text.get(key, []):
                inline.append(box(w))
        hits = bubble or inline
        if hits:
            out[tag] = hits
    return out


def dexpi_fallback_boxes(pdf_path, xml_path, missing_tags, located: dict,
                         dpi: int = 200) -> tuple[dict, dict]:
    """Positions for tags the TEXT LAYER cannot see, from DEXPI geometry.

    Calibration is MEASURED, not assumed: tags located in both worlds
    (text-layer box centre + DEXPI Position) give a least-squares affine
    fit per axis (handles scale, offset and a flipped y-axis). Applied
    only if >=4 anchor pairs and residual < 60 px. Returns ({tag: [box]},
    info) where info reports anchors/residual — honesty for the caption.
    """
    import xml.etree.ElementTree as ET
    import numpy as np
    from pathlib import Path as _P
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:                                       # noqa: BLE001
        return {}, {"ok": False}
    xy = {}
    for el in root.iter():
        t, loc = el.get("TagName"), el.find("Position/Location")
        if t and loc is not None:
            try:
                xy[_norm(t)] = (float(loc.get("X")), float(loc.get("Y")))
            except Exception:                               # noqa: BLE001
                pass
    A = [(xy[_norm(t)], (b[0][0] + b[0][2] / 2, b[0][1] + b[0][3] / 2))
         for t, b in located.items() if _norm(t) in xy]
    if len(A) < 4:
        return {}, {"ok": False, "anchors": len(A)}
    src = np.array([a for a, _ in A]); dst = np.array([b for _, b in A])
    fits, res = [], 0.0
    for ax in (0, 1):
        M = np.c_[src[:, ax], np.ones(len(A))]
        (k, m), r, *_ = np.linalg.lstsq(M, dst[:, ax], rcond=None)
        fits.append((k, m))
        res += float(np.sqrt(r[0] / len(A))) if len(r) else 0.0
    if res > 60:
        return {}, {"ok": False, "anchors": len(A), "residual": res}
    out = {}
    for t in missing_tags:
        p = xy.get(_norm(t))
        if p:
            cx = fits[0][0] * p[0] + fits[0][1]
            cy = fits[1][0] * p[1] + fits[1][1]
            out[t] = [(cx - 55, cy - 45, 110, 90)]
    return out, {"ok": True, "anchors": len(A), "residual": round(res, 1)}