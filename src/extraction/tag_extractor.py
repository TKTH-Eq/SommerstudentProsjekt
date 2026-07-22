"""Tag extraction from a P&ID or SCD PDF.

Two complementary passes, because tags appear in two forms on these drawings:
  (a) inline hyphenated, e.g. "27-PT4805" (and cross-system "63-XV4800")
  (b) stacked inside instrument bubbles: type over number in one column
      -> reassembled by clustering positioned words.

Redundant instruments are often written with a combined suffix, e.g.
"27-PT4250A/B" (two physical devices in one label). These are expanded so BOTH
legs (…A and …B, or …A/B/C) are captured, not just the first.

If the text passes yield almost nothing (image-only drawing) and
HULDRA_VISION=1 is set, a Gemini vision pass on the rendered page is used as a
reserve (pass c). The reserve never raises: any failure logs and falls back to
whatever the text passes found. It runs on page 1 only.

extract_tags defaults to page 1 (index 0) — the validated behaviour. The
register build passes higher page indices for the handful of multi-page SCDs.

Extraction is approximate. It is a first pass for engineer review, not truth.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from config import ALL_TYPES
from extraction.pdf_parser import extract_words
from models.engineering_object import EngineeringObject

INLINE = re.compile(r"\b(\d{2}-[A-Z]{2,4}\d{2,4}[A-Z]?)\b")
# combined redundancy forms:  27-PT4250A/B  ->  base "27-PT4250", suffix "A/B"
COMBINED = re.compile(r"(\d{2}-[A-Z]{2,4}\d{2,4})([A-Z](?:/[A-Z])+)")
NUM = re.compile(r"^\d{2,4}[A-Z]?$")
NUM_COMBINED = re.compile(r"^(\d{2,4})([A-Z](?:/[A-Z])+)$")
# (a3) number-first valve/line tags, e.g. "27-4510PV", "27-4454PL", "43-4505VF"
INLINE_NUMFIRST = re.compile(r"\b(\d{2}-\d{3,4}[A-Z]{2,3})\b")

# (c) vision reserve: below this many text-pass tags, the drawing is considered
# tag-poor (image-only) and the reserve may run. HO11 yields 0 and triggers;
# every other scored drawing yields 15+ and never touches the reserve.
VISION_MIN_TAGS = 3
# vision output without a system prefix, e.g. "PT4805" -> prefixed with the
# drawing's system code as well, so validation matches either written form
_UNPREFIXED = re.compile(r"^[A-Z]{1,4}\d{2,5}[A-Z]?$")


def _system_of(pdf_path: Path) -> str:
    """Guess the drawing's system code from the filename (…-HO27-… -> 27)."""
    m = re.search(r"H[A-Z](\d{2})", pdf_path.stem)
    return m.group(1) if m else "00"


def _legs(base: str, suffix: str) -> set[str]:
    """'A/B' -> {base+'A', base+'B'};  'A/B/C' -> three legs."""
    return {base + leg for leg in suffix.split("/")}


def _vision_reserve(pdf_path: Path, system: str, text_tags: set[str]) -> set[str]:
    """Pass (c): Gemini reads the rendered page. Opt-in, never raises."""
    try:
        from extraction.vision_extract import extract_tags_vision
        vtags = extract_tags_vision(pdf_path)
    except Exception as e:                     # never let the reserve sink the run
        print(f"[vision] {pdf_path.name}: reserve failed ({e})")
        return set()
    out: set[str] = set()
    for vt in vtags:
        out.add(vt)
        if _UNPREFIXED.match(vt):              # "PT4805" -> also "27-PT4805"
            out.add(f"{system}-{vt}")
    print(f"[vision] {pdf_path.name}: text layer gave {len(text_tags)} tag(s), "
          f"vision added {len(out)}")
    return out


def extract_tags(pdf_path: str | Path, page: int = 0) -> set[str]:
    pdf_path = Path(pdf_path)
    system = _system_of(pdf_path)
    words = extract_words(pdf_path, page=page)
    text = " ".join(t for (t, _, _) in words)
    tags: set[str] = set()

    # (a) inline hyphenated tags (single)
    for (t, x, y) in words:
        tags.update(INLINE.findall(t))
    tags.update(INLINE.findall(text))
    # (a2) inline combined redundancy forms: 27-PT4250A/B -> both legs
    for base, suffix in COMBINED.findall(text):
        tags |= _legs(base, suffix)
    # (a3) number-first valve tags: 27-4510PV, 27-4454PL, 43-4505VF
    tags.update(INLINE_NUMFIRST.findall(text))
    for (t, _, _) in words:
        tags.update(INLINE_NUMFIRST.findall(t))
    # (b) stacked bubbles: a type word + the nearest number in its column
    types = [(t, x, y) for (t, x, y) in words if t in ALL_TYPES]
    nums = [(t, x, y) for (t, x, y) in words if NUM.match(t) or NUM_COMBINED.match(t)]
    for (ty, tx, tyy) in types:
        cand = [(abs(ny - tyy), nt) for (nt, nx, ny) in nums
                if abs(nx - tx) < 16 and abs(ny - tyy) < 50]
        if cand:
            num = min(cand)[1]
            m = NUM_COMBINED.match(num)
            if m:                              # bubble holds a combined A/B number
                tags |= _legs(f"{system}-{ty}{m.group(1)}", m.group(2))
            else:
                tags.add(f"{system}-{ty}{num}")

    # (c) vision reserve for image-only drawings, opt-in via HULDRA_VISION=1.
    # Page 1 only: the reserve renders page 1, and must not fire on a sparse
    # later page of a multi-page SCD.
    if page == 0 and len(tags) < VISION_MIN_TAGS and os.getenv("HULDRA_VISION") == "1":
        tags |= _vision_reserve(pdf_path, system, tags)

    return tags


def create_objects(tags, source: str) -> list[EngineeringObject]:
    """Turn raw tag strings into typed EngineeringObjects."""
    objs = {EngineeringObject.from_tag(t, source=source) for t in tags}
    return sorted(objs, key=lambda o: o.tag)