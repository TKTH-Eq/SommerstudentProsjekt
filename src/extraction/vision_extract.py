"""Vision-based tag extraction via Gemini (for drawings the text layer can't read).

Results are cached to disk (reports/vision_cache/tags/<stem>.json — the
tags/ subfolder keeps this cache separate from the HAZOP vision-excerpt
cache that ai/ai_cache.py stores in the parent folder), because the
free Gemini tier allows ~20 calls/day while the drawing set has ~65
image-only SCDs. With the cache, a --vision run is RESUMABLE: each run only
spends quota on drawings not yet cached, and failures (429 quota, network)
are never cached — they are simply retried on the next run. Re-running the
whole register build therefore converges to fully vision-enriched over a
few days at zero cost. On the first daily-quota 429 in a run, the remaining
vision calls in that run are skipped instead of each failing slowly.

Set HULDRA_VISION_FRESH=1 to bypass the cache and force fresh API calls
(results still overwrite the cache on success). Delete individual files
under reports/vision_cache/tags/ to redo single drawings.
"""
from __future__ import annotations
import json, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

CACHE_DIR = Path("reports") / "vision_cache" / "tags"

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


# ---------------------------------------------------------------------------
# Disk cache — one readable JSON per drawing, successes only
# ---------------------------------------------------------------------------

def _cache_path(pdf_path: Path) -> Path:
    return CACHE_DIR / f"{pdf_path.stem}.json"


def _cache_load(pdf_path: Path) -> list[str] | None:
    """Cached tags for this drawing, or None (no hit / unreadable / bypassed)."""
    if os.getenv("HULDRA_VISION_FRESH") == "1":
        return None
    p = _cache_path(pdf_path)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        tags = payload.get("tags")
        if isinstance(tags, list):
            print(f"[vision] {pdf_path.name}: cache hit "
                  f"({len(tags)} tag(s), saved {payload.get('saved_at', '?')[:16]})")
            return [str(t) for t in tags]
    except Exception as e:  # noqa: BLE001
        print(f"[vision] {pdf_path.name}: unreadable cache ignored ({e})")
    return None


def _cache_save(pdf_path: Path, tags: list[str], model: str, dpi: int) -> None:
    """Persist a SUCCESSFUL result. Failures must never reach this point —
    an uncached failure is what makes the next run retry the drawing."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(pdf_path).write_text(json.dumps({
            "drawing": pdf_path.name,
            "tags": tags,
            "model": model,
            "dpi": dpi,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[vision] {pdf_path.name}: could not write cache ({e})")


# module-global kill-switch: set on the first daily-quota 429 in a run, so the
# remaining uncached drawings are skipped instantly instead of each making a
# slow, doomed API call. Resets naturally on the next process start.
_QUOTA_EXHAUSTED = False


def extract_tags_vision(pdf_path, dpi: int = 200, model: str | None = None) -> list[str]:
    """Read tags from the drawing image. Returns [] on parse failure — never
    raw model text. API errors (quota, network) raise to the caller, which is
    deliberate: they must NOT be cached as empty results.

    Cached per drawing under reports/vision_cache/tags/ — see module docstring.
    """
    global _QUOTA_EXHAUSTED
    pdf_path = Path(pdf_path)
    cached = _cache_load(pdf_path)
    if cached is not None:
        return cached
    if _QUOTA_EXHAUSTED:
        raise RuntimeError("daily vision quota exhausted earlier in this run "
                           "— drawing skipped, retry on the next run")

    from google import genai
    from google.genai import types
    from ai.gemini_client import resolve_model
    model_name = resolve_model(model)
    png = render_png(pdf_path, dpi)
    img = Path(png).read_bytes()
    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=[types.Part.from_bytes(data=img, mime_type="image/png"), PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,      # deterministisk transkripsjon, ikke kreativitet
            ),
        )
    except Exception as e:
        if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
            _QUOTA_EXHAUSTED = True
            print("[vision] daily quota exhausted — skipping remaining "
                  "vision calls in this run (cached drawings still load)")
        raise
    raw = _parse_tags(resp.text or "")
    tags = sorted({t for t in raw if _TAG_RE.match(t)})
    dropped = len(raw) - len(tags)
    if dropped:
        print(f"[vision] {dropped} model output(s) rejected by tag pattern")
    _cache_save(pdf_path, tags, model_name, dpi)
    return tags


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python src/extraction/vision_extract.py <drawing.pdf>")
    tags = extract_tags_vision(sys.argv[1])
    print(f"{len(tags)} tags read by vision:")
    for t in tags:
        print("  ", t)