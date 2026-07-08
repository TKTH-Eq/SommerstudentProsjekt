"""PDF reading: diagnostics, text, positioned words, page render.

Uses pdfplumber (text + vector geometry) and poppler `pdftoppm` (render).
Chosen over PyMuPDF because it recovers positioned words, which we need to
reassemble the vertically-stacked tags inside instrument bubbles.
"""
from __future__ import annotations
import subprocess
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
    """Return (text, x_center, y_center) for each word on page 1."""
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[0]
        return [(w["text"].strip(),
                 (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)
                for w in p.extract_words()]


def render(pdf_path: str | Path, dpi: int = 200, out_dir: str | Path = "/tmp") -> Path:
    """Render page 1 to PNG (for a vision model or human inspection)."""
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / pdf_path.stem
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                    str(pdf_path), str(prefix)], check=True)
    return sorted(out_dir.glob(f"{pdf_path.stem}*.png"))[0]