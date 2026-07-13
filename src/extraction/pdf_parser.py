"""PDF reading: diagnostics, text, positioned words, page render.

Uses pdfplumber (text + vector geometry) and poppler `pdftoppm` (render).
Chosen over PyMuPDF because it recovers positioned words, which we need to
reassemble the vertically-stacked tags inside instrument bubbles.

OCR fallback (Google Vision)
----------------------------
Some drawings carry a real text layer for the title block and grid frame,
but the actual components/tags are drawn as graphics (or a raster image).
Plain text extraction returns the frame and nothing useful. extract_words()
therefore optionally rasterises such pages and runs Google Vision OCR,
merging the recovered words back in the same (text, x, y) format.

The fallback is OFF by default (it costs API calls). Enable it by setting
the environment variable HULDRA_VISION=1, e.g. before a validation run:

    set HULDRA_VISION=1                 (Windows)
    export HULDRA_VISION=1              (bash)

It triggers only on *tag-poor* pages (few tag-like words found), so normal
text drawings are untouched. Requires `google-cloud-vision` and Google
credentials (GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
JSON). Any failure (missing package, no creds, no poppler) degrades
gracefully: OCR is skipped and text-only extraction is returned.
"""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pdfplumber

# A cheap "this token looks like a tag" test, used only to decide whether a
# page is tag-poor enough to warrant OCR. Not the real extraction regex.
_TAGISH = re.compile(r"\d{2}-[A-Z0-9]")

# OCR fallback is opt-in via env var, so ordinary runs make no API calls.
def _vision_enabled() -> bool:
    return os.environ.get("HULDRA_VISION", "").strip().lower() not in ("", "0", "false")


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


def extract_words(pdf_path: str | Path, use_ocr: bool | None = None,
                  ocr_min_tagish: int = 5) -> list[tuple[str, float, float]]:
    """Return (text, x_center, y_center) for each word on page 1.

    If OCR is enabled (HULDRA_VISION=1, or use_ocr=True) and the text layer
    is tag-poor (fewer than ocr_min_tagish tag-like words), the page is
    rasterised and Google Vision words are merged in.
    """
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[0]
        words = [(w["text"].strip(),
                  (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)
                 for w in p.extract_words()]

    enable = _vision_enabled() if use_ocr is None else use_ocr
    if enable:
        n_tagish = sum(1 for (t, _, _) in words if _TAGISH.search(t))
        if n_tagish < ocr_min_tagish:
            ocr = _ocr_words(pdf_path)
            if ocr:
                print(f"  [vision] {pdf_path.name}: tag-poor text layer "
                      f"({n_tagish} tag-like words) -> OCR added {len(ocr)} words")
                words = words + ocr
    return words


def render(pdf_path: str | Path, dpi: int = 200, out_dir: str | Path | None = None) -> Path:
    """Render page 1 to PNG (for a vision model or human inspection)."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir is not None else Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / pdf_path.stem
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                    str(pdf_path), str(prefix)], check=True)
    return sorted(out_dir.glob(f"{pdf_path.stem}*.png"))[0]


def _ocr_words(pdf_path: str | Path, dpi: int = 200) -> list[tuple[str, float, float]]:
    """Rasterise page 1 and OCR it with Google Vision, returning positioned
    words in the same (text, x_center, y_center) format, scaled to PDF points
    so coordinates line up with pdfplumber output. Returns [] on any failure.
    """
    try:
        from google.cloud import vision
    except Exception:
        print("  [vision] google-cloud-vision not installed; skipping OCR "
              "(pip install google-cloud-vision)")
        return []
    try:
        png = render(pdf_path, dpi=dpi)
        content = Path(png).read_bytes()
        client = vision.ImageAnnotatorClient()
        resp = client.document_text_detection(image=vision.Image(content=content))
        if resp.error.message:
            print(f"  [vision] API error: {resp.error.message}")
            return []
        scale = 72.0 / dpi          # pixels -> PDF points
        out: list[tuple[str, float, float]] = []
        for page in resp.full_text_annotation.pages:
            for block in page.blocks:
                for para in block.paragraphs:
                    for word in para.words:
                        txt = "".join(s.text for s in word.symbols).strip()
                        if not txt:
                            continue
                        xs = [v.x for v in word.bounding_box.vertices]
                        ys = [v.y for v in word.bounding_box.vertices]
                        cx = (min(xs) + max(xs)) / 2 * scale
                        cy = (min(ys) + max(ys)) / 2 * scale
                        out.append((txt, cx, cy))
        return out
    except FileNotFoundError:
        print("  [vision] poppler `pdftoppm` not found; cannot rasterise for OCR")
        return []
    except Exception as e:  # noqa: BLE001
        print(f"  [vision] OCR failed: {e}")
        return []