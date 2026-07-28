"""
src/finn_tegning.py — Streamlit page: find the right drawing.

Type what you're looking for in plain language; the page ranks the P&ID sheets
by a profile built from the tag register (type codes expanded to words) plus any
cached 30-second vision summaries. Optional Gemini query-expansion handles
synonyms and Norwegian↔English. View the top hit inline (zoom/pan).

Registered in nav_pages.py. Engine: src/analysis/drawing_search.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import page_header, zoomable_image
from analysis.drawing_search import (build_index, search, expand_query,
                                     relevant_tags)

try:
    from config import PID_DIR, DATA
except Exception:                                                  # noqa: BLE001
    DATA = Path(__file__).resolve().parents[1] / "data" / "raw"
    PID_DIR = DATA / "P&ID"


@st.cache_resource(show_spinner="Indexing the drawings…")
def _index():
    return build_index(str(DATA))


def _pdf_for(stem: str) -> Path | None:
    hits = list(Path(PID_DIR).rglob(f"{stem}.[pP][dD][fF]"))
    return hits[0] if hits else None


@st.cache_data(show_spinner=False)
def _render(stem: str, dpi: int = 200) -> str | None:
    pdf = _pdf_for(stem)
    if not pdf:
        return None
    try:
        from extraction.vision_extract import render_png
        return render_png(str(pdf), dpi)
    except Exception:                                       # noqa: BLE001
        return None


@st.cache_data(show_spinner=False)
def _objects(stem: str):
    """(tag, type_code) for the PDF-readable tags — same tags locate_tags can
    place, so the highlight set matches what can be drawn."""
    pdf = _pdf_for(stem)
    if not pdf:
        return []
    from extraction.tag_extractor import extract_tags, create_objects
    return [(o.tag, o.type_code)
            for o in create_objects(extract_tags(str(pdf)), "P&ID")]


@st.cache_data(show_spinner="Highlighting matching tags…")
def _highlighted(stem: str, tags: tuple) -> tuple[str | None, int]:
    """Render the sheet with the query-matching tags boxed in amber."""
    png = _render(stem)
    pdf = _pdf_for(stem)
    if not (png and pdf):
        return png, 0
    if not tags:
        return png, 0
    from extraction.tag_locator import locate_tags
    from PIL import Image, ImageDraw
    boxes_map = locate_tags(str(pdf), list(tags), dpi=200)
    boxes = [b for t in tags for b in boxes_map.get(t, [])]
    if not boxes:
        return png, 0
    im = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    for (x, y, w, h) in boxes:
        pad = max(12, 0.45 * w)
        r = [x - pad, y - pad, x + w + pad, y + h + pad]
        d.rectangle(r, fill=(255, 193, 7, 70))
        d.rectangle(r, outline=(230, 126, 34, 255), width=5)
    out = str(Path(png).with_name(f"{stem}_hl.png"))
    im.save(out)
    return out, len(boxes)


page_header("Find the right drawing",
            "Search the P&IDs in plain language — stop hunting for the right sheet")
st.caption("Ranks sheets by a profile built from the tag register (type codes "
           "expanded to words — 'PT' → pressure transmitter) plus any cached "
           "30-second vision summaries (that's where 'separator', 'flare' etc. "
           "come from). Works without a key; Gemini optionally expands the query "
           "with synonyms and Norwegian↔English — it only adds search terms, "
           "never invents a drawing.")

idx = _index()
n_sum = sum(d["has_summary"] for d in idx)
st.caption(f"🗂️ {len(idx)} drawings indexed · {n_sum} enriched with a vision "
           f"summary. Enrich more on the **📝 30-sec summary** page for richer "
           f"semantic search (equipment, hazards).")

q = st.text_input("What are you looking for?",
                  placeholder="e.g. pressure relief valve · shutdown logic on "
                              "system 27 · level transmitter · separator")

extra = []
if q and os.getenv("GEMINI_API_KEY"):
    if st.checkbox("🤖 Expand my query with AI (synonyms, NO↔EN)", value=True):
        with st.spinner("Expanding…"):
            extra = expand_query(q)
        if extra:
            st.caption("🤖 Added search terms: " + ", ".join(extra))

if q:
    hits = search(q, idx, extra_terms=extra, top=10)
    if not hits:
        st.warning("No drawing matched. Try instrument/equipment words "
                   "(pressure, relief, level, shutdown, separator) or a system "
                   "number — or enrich drawings with vision summaries first.")
    else:
        st.subheader(f"{len(hits)} match(es)")
        st.dataframe(
            [{"rank": i + 1, "drawing": h["stem"], "system": h["system"],
              "score": h["score"], "matched": ", ".join(h["hits"][:8]),
              "summary?": "✅" if h["has_summary"] else "—"}
             for i, h in enumerate(hits)],
            use_container_width=True, hide_index=True)

        st.subheader("View a match")
        pick = st.selectbox("Drawing", [h["stem"] for h in hits],
                            format_func=lambda s: s)
        chosen = next(h for h in hits if h["stem"] == pick)
        if chosen["summary"]:
            st.caption("🧠 " + chosen["summary"][:300])
        rel = relevant_tags(q, _objects(pick), extra_terms=extra)
        png, n_hl = _highlighted(pick, tuple(rel))
        if png:
            zoomable_image(png, height=560)
            if n_hl:
                st.caption(f"🟠 {n_hl} tag(s) matching your query highlighted in "
                           f"amber on {pick}. Scroll to zoom, drag to pan.")
            else:
                st.caption(f"{pick} — no query tags were locatable in the text "
                           f"layer (they may be symbol-only). Scroll to zoom.")
        else:
            st.caption("Could not render this drawing (no matching PDF found).")
else:
    st.info("Type a query above. Examples: *pressure relief valve*, *emergency "
            "shutdown on system 20*, *level control*, *flare*.")
