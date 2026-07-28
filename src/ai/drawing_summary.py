"""
30-second drawing summary: a vision model reads one P&ID sheet and returns a
short orientation — what the drawing is about, its key equipment and the main
hazards — for an engineer who has not seen it before.

Grounded in the project's idiom: the LLM only *proposes*; every tag it claims to
read is verified against the extracted register (verify_tags), so a hallucinated
tag is flagged, not trusted. Successful summaries are cached to disk so repeat
views and demos are free and offline-safe (failures are never cached).
"""
from __future__ import annotations

import json
from pathlib import Path

_CACHE = Path("reports/ai_cache")


def _cache_path(stem: str) -> Path:
    return _CACHE / f"summary_{stem}.json"


def load_summary(stem: str) -> dict | None:
    p = _cache_path(stem)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None


def _save_summary(stem: str, data: dict) -> None:
    _CACHE.mkdir(parents=True, exist_ok=True)
    _cache_path(stem).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")


_PROMPT = (
    "You are looking at a rendered P&ID engineering drawing. In ~30 seconds, "
    "orient an engineer who has never seen it. Respond ONLY with JSON: "
    '{"summary": "<2-3 sentences: what process/system this sheet shows and its '
    'purpose>", "key_equipment": ["<main vessels, pumps, compressors, '
    'exchangers visible>"], "main_hazards": ["<the main process hazards a HAZOP '
    'would focus on here, e.g. overpressure, gas release, loss of containment>"], '
    '"tags": ["<the most important tag numbers you can clearly READ on the '
    'sheet>"]}. Only report what is visibly drawn; do not invent tags or '
    "equipment. Keep each list to at most 6 items.")


def summarize_drawing(pdf_path, known_tags, dpi: int = 200,
                      use_cache: bool = True) -> dict:
    """Vision summary of one sheet. Returns
    {ok, summary, key_equipment, main_hazards, tags:[{tag,status}], cached_at?}.
    known_tags = the register for this drawing, used to verify what the model
    claims to read."""
    stem = Path(pdf_path).stem
    if use_cache:
        hit = load_summary(stem)
        if hit:
            hit = {**hit, "cached_at": hit.get("saved_at", "cache")}
            return hit

    from google.genai import types
    from extraction.vision_extract import render_png
    from ai.gemini_client import generate
    from ai.hazop_vision import verify_tags

    png = render_png(Path(pdf_path), dpi)
    img = Path(png).read_bytes()
    resp = generate(
        [types.Part.from_bytes(data=img, mime_type="image/png"), _PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json"))
    try:
        data = json.loads(resp.text)
    except Exception:                                       # noqa: BLE001
        return {"ok": False, "summary": "Could not parse the model response."}

    mentioned = [str(t) for t in data.get("tags", [])][:12]
    checked = verify_tags({"summary": "", "observations": [
        {"observation": "", "deviation": "", "tags": mentioned}],
        "possible_symbol_only": []}, known_tags)
    tags = checked["observations"][0]["tags"] if mentioned else []

    out = {
        "ok": True,
        "summary": str(data.get("summary", ""))[:800],
        "key_equipment": [str(x) for x in data.get("key_equipment", [])][:6],
        "main_hazards": [str(x) for x in data.get("main_hazards", [])][:6],
        "tags": tags,
        "saved_at": "now (live)",
    }
    _save_summary(stem, out)
    return out
