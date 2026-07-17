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
        hits = []
        # pass 1: the whole tag (with or without system prefix) as one word
        t_full = _norm(tag)                      # hyphen already stripped
        t_nosys = t_full[2:] if re.match(r"^\d{2}-", str(tag).strip()) \
            else t_full
        for key in {t_full, t_nosys}:
            for w in by_text.get(key, []):
                hits.append(box(w))
        # pass 2: stacked bubble — type word + number word in same column
        parsed = _parse(tag)
        if parsed and not hits:
            ty, num = parsed
            for tw in by_text.get(ty, []):
                for nw in by_text.get(num, []):
                    stacked = (abs(nw["x0"] - tw["x0"]) < _X_TOL
                               and abs(nw["top"] - tw["top"]) < _Y_TOL)
                    # wellhead style: "PT 2438" side by side on one line
                    side = (abs(nw["top"] - tw["top"]) < 10
                            and -5 < nw["x0"] - tw["x1"] < 25)
                    if stacked or side:
                        hits.append(box(tw, nw))
        if hits:
            out[tag] = hits
    return out