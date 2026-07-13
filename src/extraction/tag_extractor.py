"""Tag extraction from a P&ID or SCD PDF.

Two complementary passes, because tags appear in two forms on these drawings:
  (a) inline hyphenated, e.g. "27-PT4805" (and cross-system "63-XV4800")
  (b) stacked inside instrument bubbles: type over number in one column
      -> reassembled by clustering positioned words.

Redundant instruments are often written with a combined suffix, e.g.
"27-PT4250A/B" (two physical devices in one label). These are expanded so BOTH
legs (…A and …B, or …A/B/C) are captured, not just the first.

Extraction is approximate. It is a first pass for engineer review, not truth.
"""
from __future__ import annotations
import re
from pathlib import Path
from config import ALL_TYPES
from extraction.pdf_parser import extract_words
from models.engineering_object import EngineeringObject

INLINE = re.compile(r"\b(\d{2}-[A-Z]{2,4}\d{2,4}[A-Z]?)\b")
# combined redundancy forms:  27-PT4250A/B  ->  base "27-PT4250", suffix "A/B"
COMBINED = re.compile(r"(\d{2}-[A-Z]{2,4}\d{3,4})([A-Z](?:/[A-Z])+)")
NUM = re.compile(r"^\d{3,4}[A-Z]?$")
NUM_COMBINED = re.compile(r"^(\d{3,4})([A-Z](?:/[A-Z])+)$")
# (a3) number-first valve/line tags, e.g. "27-4510PV", "27-4454PL", "43-4505VF"
INLINE_NUMFIRST = re.compile(r"\b(\d{2}-\d{3,4}[A-Z]{2,3})\b")


def _system_of(pdf_path: Path) -> str:
    """Guess the drawing's system code from the filename (…-HO27-… -> 27)."""
    m = re.search(r"H[A-Z](\d{2})", pdf_path.stem)
    return m.group(1) if m else "00"


def _legs(base: str, suffix: str) -> set[str]:
    """'A/B' -> {base+'A', base+'B'};  'A/B/C' -> three legs."""
    return {base + leg for leg in suffix.split("/")}


def extract_tags(pdf_path: str | Path) -> set[str]:
    pdf_path = Path(pdf_path)
    system = _system_of(pdf_path)
    words = extract_words(pdf_path)
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
            if m:                                    # bubble holds a combined A/B number
                tags |= _legs(f"{system}-{ty}{m.group(1)}", m.group(2))
            else:
                tags.add(f"{system}-{ty}{num}")
    return tags


def create_objects(tags, source: str) -> list[EngineeringObject]:
    """Turn raw tag strings into typed EngineeringObjects."""
    objs = {EngineeringObject.from_tag(t, source=source) for t in tags}
    return sorted(objs, key=lambda o: o.tag)