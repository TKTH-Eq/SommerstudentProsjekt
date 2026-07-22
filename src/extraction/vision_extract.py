"""Vision-based tag extraction via Gemini (for drawings the text layer can't read)."""
from __future__ import annotations
import json, os, re, tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

PROMPT = (
    "This image is an offshore P&ID or System Control Diagram. "
    "List every instrument and equipment tag you can read "
    "(examples of the format: 27-PT4805, 27-XV4813, 27-KA50). "
    "Transcribe each tag EXACTLY as printed. Do NOT invent tags you cannot read. "
    "Return ONLY a JSON array of tag strings."
)

# Grovfilter: noe som ligner et tag (system-prefiks valgfritt, 1-3 bokstaver + tall
# i valgfri rekkefølge). Slipper 27-PT4805, PT4805, 27-4510PV, 27-KA50, N1100.
_TAG_RE = re.compile(r"^\d{0,3}-?(?:[A-Z]{1,3}\d{1,5}|\d{1,5}[A-Z]{1,3}|[A-Z]{1,2}\d{2,5})$")


def render_png(pdf_path: str | Path, dpi: int = 200, page: int = 0) -> str:
    """Render one page to a temp PNG with pypdfium2 (no poppler needed).

    Exported so the OCR reserve in the extraction layer can reuse it
    instead of shelling out to pdftoppm.
    """
    import pypdfium2 as pdfium
    pdf_path = Path(pdf_path)
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        pil = pdf[page].render(scale=dpi / 72).to_pil()
    finally:
        pdf.close()
    out = os.path.join(tempfile.gettempdir(), f"{pdf_path.stem}_p{page}_vision.png")
    pil.save(out)
    return out


def _parse_tags(text: str) -> list[str]:
    """Tolerant parse: strip markdown fences, accept only list-of-strings."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(t).strip().upper() for t in data if str(t).strip()]


def extract_tags_vision(pdf_path, dpi: int = 200, model: str | None = None) -> list[str]:
    """Read tags from the drawing image. Returns [] on any failure — never raw model text."""
    from google import genai
    from google.genai import types
    png = render_png(pdf_path, dpi)
    img = Path(png).read_bytes()
    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    resp = client.models.generate_content(
        model=model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=[types.Part.from_bytes(data=img, mime_type="image/png"), PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,          # deterministisk transkripsjon, ikke kreativitet
        ),
    )
    raw = _parse_tags(resp.text or "")
    tags = sorted({t for t in raw if _TAG_RE.match(t)})
    dropped = len(raw) - len(tags)
    if dropped:
        print(f"[vision] {dropped} model output(s) rejected by tag pattern")
    return tags


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python src/extraction/vision_extract.py <drawing.pdf>")
    tags = extract_tags_vision(sys.argv[1])
    print(f"{len(tags)} tags read by vision:")
    for t in tags:
        print("  ", t)