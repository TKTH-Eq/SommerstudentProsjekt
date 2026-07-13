"""Vision-based tag extraction via Gemini (for drawings the text layer can't read)."""
from __future__ import annotations
import json, os, tempfile
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


def _render_png(pdf_path: Path, dpi: int) -> str:
    """Render page 1 to PNG, cross-platform (no poppler needed)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    pil = pdf[0].render(scale=dpi / 72).to_pil()
    out = os.path.join(tempfile.gettempdir(), Path(pdf_path).stem + "_vision.png")
    pil.save(out)
    return out


def extract_tags_vision(pdf_path, dpi: int = 200, model: str | None = None) -> list[str]:
    from google import genai
    from google.genai import types
    png = _render_png(Path(pdf_path), dpi)
    img = Path(png).read_bytes()
    client = genai.Client()                        # reads GEMINI_API_KEY from the environment
    resp = client.models.generate_content(
        model=model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=[types.Part.from_bytes(data=img, mime_type="image/png"), PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        tags = json.loads(resp.text)
        return [str(t).strip().upper() for t in tags] if isinstance(tags, list) else []
    except Exception:
        return [resp.text]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python src/extraction/vision_extract.py <drawing.pdf>")
    tags = extract_tags_vision(sys.argv[1])
    print(f"{len(tags)} tags read by vision:")
    for t in tags:
        print("  ", t)