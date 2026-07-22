"""PDF reading: diagnostics, text, positioned words, page render.

Uses pdfplumber (text + vector geometry) and pypdfium2 (render).
Chosen over PyMuPDF because it recovers positioned words, which we need to
reassemble the vertically-stacked tags inside instrument bubbles.

Image-only drawings (no usable text layer) return few or no words here.
That is by design: the vision reserve for such drawings lives in
extraction.tag_extractor (pass c, opt-in via HULDRA_VISION=1), which reads
tags directly off the rendered page with Gemini. This module does text and
geometry only, and makes no API calls.
"""
from __future__ import annotations
import tempfile
from pathlib import Path

import pdfplumber


def diagnose(pdf_path: str | Path) -> dict:
    """Is there a usable text layer, or is this a vision/OCR job?"""
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[0]
        text = p.extract_text() or ""
        info = {
            "file": pdf_path.name,
            "lines": len(p.lines), "curves": len(p.curves),
            "chars": len(p.chars), "images": len(p.images),
            "text_chars": len(text.strip()),
        }
    if info["text_chars"] > 200:
        info["verdict"] = "text-extractable"
    elif info["images"] and info["lines"] == 0:
        info["verdict"] = "raster - OCR/vision required"
    else:
        info["verdict"] = "vector but text is outlined - vision required"
    return info


def extract_text(pdf_path: str | Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return pdf.pages[0].extract_text() or ""


def extract_words(pdf_path: str | Path) -> list[tuple[str, float, float]]:
    """Return (text, x_center, y_center) for each word on page 1.

    Text layer only. Image-only drawings yield few or no words; the vision
    reserve in extraction.tag_extractor handles those.
    """
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[0]
        return [(w["text"].strip(),
                 (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)
                for w in p.extract_words()]


def render(pdf_path: str | Path, dpi: int = 200, out_dir: str | Path | None = None) -> Path:
    """Render page 1 to PNG (for a vision model or human inspection).

    Uses pypdfium2 — pure pip dependency, no poppler/system install needed.
    """
    import pypdfium2 as pdfium
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir is not None else Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pdf_path.stem}.png"
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        pdf[0].render(scale=dpi / 72).to_pil().save(out)
    finally:
        pdf.close()
    return out