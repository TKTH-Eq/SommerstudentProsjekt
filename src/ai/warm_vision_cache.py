"""
Warm the vision cache before a demo.

    python src/ai/warm_vision_cache.py "data/raw/P&ID/C025-V-HO27-P-_E-002-01.PDF" ...

For each PDF: extract the tag register, call Gemini vision, verify tags,
save excerpt + raster to reports/vision_cache/. Sleeps between calls to
respect free-tier rate limits. Requires GEMINI_API_KEY and pypdfium2.

Run this the evening before, eyeball the results in the app, and commit
reports/vision_cache/ — then the demo works even fully offline.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from extraction.tag_extractor import extract_tags
from extraction.vision_extract import render_png as _render_png
from ai.hazop_vision import vision_hazop_excerpt
from ai.ai_cache import save_vision


def main(paths: list[str], pause: float = 10.0) -> None:
    if not paths:
        sys.exit(__doc__)
    for i, p in enumerate(paths, 1):
        pdf = Path(p)
        if not pdf.exists():
            print(f"[{i}/{len(paths)}] HOPPER OVER — finnes ikke: {pdf}")
            continue
        print(f"[{i}/{len(paths)}] {pdf.name} …", flush=True)
        try:
            known = extract_tags(str(pdf))
            excerpt = vision_hazop_excerpt(pdf, known)
            png = _render_png(pdf, 200)
            save_vision(pdf.stem, excerpt, png)
            t = excerpt.get("tag_totals", {})
            print(f"    ok — {len(excerpt.get('observations', []))} observasjoner, "
                  f"tags: ✅{t.get('verified', 0)} ☑️{t.get('verified_loose', 0)} "
                  f"🟠{t.get('new_candidate', 0)} ❓{t.get('suspect', 0)}")
        except Exception as e:                              # noqa: BLE001
            print(f"    FEILET: {e}")
        if i < len(paths):
            time.sleep(pause)                # snill mot gratis-tieret
    print("\nFerdig. Åpne HAZOP-fanen og kontroller resultatene, "
          "og vurder å committe reports/vision_cache/.")


if __name__ == "__main__":
    main(sys.argv[1:])