"""
Disk cache for AI outputs — demo-proofing.

Why: the free Gemini tier has rate limits, conference wifi is unreliable,
and a live demo should never hinge on an external API answering in the
moment. Everything AI-generated is therefore cached to disk:

    reports/vision_cache/<drawing-stem>.json   verified vision excerpt
    reports/vision_cache/<drawing-stem>.png    the raster the model saw
    reports/ai_cache/<system>__<node>.md       HAZOP node rewrites

The app loads from cache automatically (with a visible timestamp, so
nobody mistakes cached output for a live call) and offers a re-run button
that hits the API and refreshes the cache. Warm the cache the evening
before with:  python src/ai/warm_vision_cache.py <pdf> [<pdf> ...]

Recommendation: COMMIT the cache for the demo drawings to git — then even
a fresh clone on a borrowed laptop demos flawlessly offline.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

VISION_DIR = Path("reports/vision_cache")
AI_DIR = Path("reports/ai_cache")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


# ---- vision excerpts ---------------------------------------------------------

def save_vision(drawing_stem: str, excerpt: dict, png_path: str | None) -> None:
    VISION_DIR.mkdir(parents=True, exist_ok=True)
    stem = _slug(drawing_stem)
    payload = {"excerpt": excerpt, "saved_at": time.strftime("%Y-%m-%d %H:%M")}
    (VISION_DIR / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if png_path and Path(png_path).exists():
        shutil.copyfile(png_path, VISION_DIR / f"{stem}.png")


def load_vision(drawing_stem: str) -> dict | None:
    """{'excerpt': ..., 'saved_at': ..., 'png': path-or-None} or None."""
    stem = _slug(drawing_stem)
    f = VISION_DIR / f"{stem}.json"
    if not f.exists():
        return None
    try:
        payload = json.loads(f.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None
    png = VISION_DIR / f"{stem}.png"
    payload["png"] = str(png) if png.exists() else None
    return payload


# ---- HAZOP node rewrites -----------------------------------------------------

def save_rewrite(system: str, node: str, text: str) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    (AI_DIR / f"{_slug(system)}__{_slug(node)}.md").write_text(
        f"<!-- saved_at: {stamp} -->\n{text}", encoding="utf-8")


def load_rewrite(system: str, node: str) -> dict | None:
    f = AI_DIR / f"{_slug(system)}__{_slug(node)}.md"
    if not f.exists():
        return None
    raw = f.read_text(encoding="utf-8")
    m = re.match(r"<!-- saved_at: (.*?) -->\n", raw)
    return {"text": raw[m.end():] if m else raw,
            "saved_at": m.group(1) if m else "ukjent"}