"""Tag extraction from a P&ID or SCD PDF.

Two complementary passes, because tags appear in two forms on these drawings:
  (a) inline hyphenated, e.g. "27-PT4805" (and cross-system "63-XV4800")
  (b) stacked inside instrument bubbles: type over number in one column
      -> reassembled by clustering positioned words.

Extraction is approximate. It is a first pass for engineer review, not truth.
"""
from __future__ import annotations
import re
from pathlib import Path
from config import ALL_TYPES
from extraction.pdf_parser import extract_words
from models.engineering_object import EngineeringObject

INLINE = re.compile(r"\b(\d{2}-[A-Z]{2,4}\d{3,4}[A-Z]?)\b")
NUM = re.compile(r"^\d{3,4}[A-Z]?$")


def _system_of(pdf_path: Path) -> str:
    """Guess the drawing's system code from the filename (…-HO27-… -> 27)."""
    m = re.search(r"H[A-Z](\d{2})", pdf_path.stem)
    return m.group(1) if m else "00"


def extract_tags(pdf_path: str | Path) -> set[str]:
    pdf_path = Path(pdf_path)
    system = _system_of(pdf_path)
    words = extract_words(pdf_path)
    tags: set[str] = set()

    # (a) inline hyphenated tags
    for (t, x, y) in words:
        tags.update(INLINE.findall(t))
    tags.update(INLINE.findall(" ".join(t for (t, _, _) in words)))

    # (b) stacked bubbles: a type word + the nearest number in its column
    types = [(t, x, y) for (t, x, y) in words if t in ALL_TYPES]
    nums = [(t, x, y) for (t, x, y) in words if NUM.match(t)]
    for (ty, tx, tyy) in types:
        cand = [(abs(ny - tyy), nt) for (nt, nx, ny) in nums
                if abs(nx - tx) < 16 and abs(ny - tyy) < 50]
        if cand:
            tags.add(f"{system}-{ty}{min(cand)[1]}")
    return tags


def create_objects(tags, source: str) -> list[EngineeringObject]:
    """Turn raw tag strings into typed EngineeringObjects."""
    objs = {EngineeringObject.from_tag(t, source=source) for t in tags}
    return sorted(objs, key=lambda o: o.tag)