"""
src/tegning_sammendrag.py — Streamlit page: 30-second drawing summary.

Select a P&ID; a vision model reads the sheet and returns a short orientation
(what it is, key equipment, main hazards) plus the tags it could read — each
verified against the extracted register. Cached to disk, so demos are offline-safe.

Registered in nav_pages.py. Engine: src/ai/drawing_summary.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()   # GEMINI_API_KEY gate below depends on .env (Streamlit won't auto-load)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import page_header, zoomable_image
from ai.drawing_summary import summarize_drawing, load_summary

try:
    from config import PID_DIR
except Exception:                                                  # noqa: BLE001
    PID_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "P&ID"

_STATUS = {"verified": "✅ in register", "verified_loose": "☑️ in register (loose)",
           "new_candidate": "🟠 not in register", "suspect": "❓ unreadable form"}


@st.cache_data(show_spinner="Rendering the drawing…")
def _render(pdf_str: str, dpi: int = 200) -> str | None:
    """Rasterise the sheet for on-screen viewing (cached). None on failure."""
    try:
        from extraction.vision_extract import render_png
        return render_png(pdf_str, dpi)
    except Exception:                                       # noqa: BLE001
        return None


page_header("30-second drawing summary",
            "A vision model reads one P&ID sheet and orients you — what it is, "
            "key equipment, main hazards")
st.caption("For an engineer opening an unfamiliar sheet: a fast orientation, "
           "not a substitute for reading the drawing. The model only proposes; "
           "every tag it claims to read is checked against the extracted "
           "register, so you can see what is real. Cached to disk — a demo runs "
           "offline once warmed.")

drawings = sorted(p for p in Path(PID_DIR).rglob("*") if p.suffix.lower() == ".pdf")
if not drawings:
    st.error(f"Found no PDFs under {PID_DIR}.")
    st.stop()

choice = st.selectbox("Drawing", drawings, format_func=lambda p: p.name)
stem = choice.stem
cached = load_summary(stem)

col_a, col_b = st.columns([1, 1])
with col_a:
    go = st.button("📝 Summarise the drawing (≈30 s)", type="primary",
                   disabled=not os.getenv("GEMINI_API_KEY"))
with col_b:
    if cached:
        st.caption(f"🗂️ A cached summary exists (saved {cached.get('saved_at','?')}). "
                   "It shows below; press the button to refresh.")

if not os.getenv("GEMINI_API_KEY"):
    st.info("Set GEMINI_API_KEY in your .env to run the vision summary. Cached "
            "summaries (if any) still display.")

result = None
if go:
    from extraction.tag_extractor import extract_tags
    with st.spinner("The vision model is reading the sheet…"):
        try:
            known = extract_tags(str(choice))
            result = summarize_drawing(choice, known, use_cache=False)
        except Exception as e:                              # noqa: BLE001
            st.error(f"Summary failed: {e}")
            st.stop()
elif cached:
    result = {**cached, "cached_at": cached.get("saved_at")}

# drawing + summary side by side, so you read the summary while looking at the
# sheet. The drawing shows as soon as one is selected; the summary fills in.
left, right = st.columns([3, 2], gap="large")
with left:
    png = _render(str(choice))
    if png:
        zoomable_image(png, height=560)
        st.caption(choice.name)
    else:
        st.caption("Could not rasterise the drawing for preview.")

with right:
    if result and result.get("ok"):
        if result.get("cached_at"):
            st.caption(f"🗂️ Cached answer ({result['cached_at']}) — press the "
                       "button to regenerate.")
        st.subheader("What this drawing is")
        st.write(result["summary"] or "—")
        st.markdown("**🏗️ Key equipment**")
        for e in result.get("key_equipment", []) or ["—"]:
            st.write("• " + e)
        st.markdown("**⚠️ Main hazards (HAZOP focus)**")
        for h in result.get("main_hazards", []) or ["—"]:
            st.write("• " + h)
    elif result is not None:
        st.warning(result.get("summary", "The summary could not be produced."))
    else:
        st.info("Press **📝 Summarise the drawing** to generate the orientation "
                "here, beside the sheet.")

if result and result.get("ok"):
    tags = result.get("tags", [])
    if tags:
        st.markdown("**🏷️ Tags the model read** (verified against the register)")
        st.dataframe(
            [{"tag": t.get("tag"), "status": _STATUS.get(t.get("status"),
                                                         t.get("status", ""))}
             for t in tags],
            use_container_width=True, hide_index=True)
        st.caption("✅/☑️ = the tag exists in the extraction · 🟠 = the model "
                   "read a tag the extraction does not have (could be a real "
                   "symbol-only tag, or a misread — verify on the drawing).")

    st.caption("AI-generated orientation with a measured error rate — never "
               "ground truth. Read the drawing before acting.")
