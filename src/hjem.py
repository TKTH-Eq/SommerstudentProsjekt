"""
src/hjem.py  —  landing page

First thing a stakeholder sees: what this is, the honest key numbers, and
three guided paths into the app. Everything else in the app assumes
context; this page provides it.
"""
from __future__ import annotations
import json
from pathlib import Path

import streamlit as st

from nav_pages import PAGES
from ui import page_header, MOSS

_EVAL_JSON = Path(__file__).resolve().parents[1] / "reports" / "eval_root_cause.json"


def _load_eval() -> dict | None:
    """Result written by eval/eval_root_cause.py, if it has been run against
    the real plant model. Synthetic-fallback results are not shown here —
    the number on this page must mean 'measured on the real topology'."""
    try:
        d = json.loads(_EVAL_JSON.read_text(encoding="utf-8"))
        return d if "real" in d.get("source", "") else None
    except Exception:  # noqa: BLE001  (missing/invalid file -> just hide it)
        return None


def _go(page, label: str, key: str):
    """Robust navigasjon: knapp + st.switch_page. Brukes i stedet for
    st.page_link, som er upålitelig sammen med st.navigation i enkelte
    Streamlit-versjoner."""
    if st.button(label, key=key, use_container_width=True):
        st.switch_page(page)

_ev = _load_eval()


def _cond(name):
    if not (_ev and _ev.get("conditions")):
        return None
    return next((c for c in _ev["conditions"] if c["name"] == name), None)


_drop20 = _cond("20 % tapte alarmer")
_ideal = _cond("ideal")
_hard = _cond("dobbel feil + 20 % tap") or _cond("dobbel feil")

_kpis = [("PRECISION (PDF)", "87 %"), ("RECALL (PDF)", "55 %"),
         ("DRAWINGS", "17"), ("TAGS", "885")]
_kpi_colors: dict[int, str] = {}
if _drop20:
    _kpis.append(("ROOT CAUSE RANKED #1", f"{_drop20['hit1_pct']:.0f} %"))
    _kpi_colors[len(_kpis) - 1] = MOSS

page_header("AI opportunities for P&IDs and SCDs",
            "Summer-student project · Huldra data (public) · "
            "decision input for the Wisting digitalisation",
            kpis=_kpis, kpi_colors=_kpi_colors)

st.markdown(
    "P&IDs and SCDs are still consumed as drawings and documents. This "
    "app demonstrates what becomes possible when they are treated as "
    "**structured engineering information** instead: automatic extraction, "
    "consistency checking, HAZOP preparation, and control-room decision "
    "support — on real drawings, with measured accuracy.")

with st.expander("📐 How the numbers are measured"):
    st.markdown(
        "- **Precision 87 % / recall 55 % (PDF extraction):** measured against "
        "independent DEXPI ground truth over 16 drawings; see Results.md "
        "for method. The recall gap is mostly tags drawn as symbols — "
        "information text extraction can never reach. That is the argument "
        "for machine-readable deliverables.\n"
        "- **Drawings/tags:** all DEXPI files stitched into one graph "
        "via shared line numbers.")
    if _drop20:
        st.markdown(
            f"- **Root cause ranked #1: {_drop20['hit1_pct']:.0f} %** — measured "
            f"with 20 % lost alarms over {_drop20['scenarios']} synthetic "
            f"failure scenarios in the real Huldra topology (run "
            f"{_ev['date']}, reproducible via eval/eval_root_cause.py). "
            f"Top 3: {_drop20['hit3_pct']:.0f} %. Under ideal conditions the "
            f"hit rate is {_ideal['hit1_pct']:.0f} % — expected by "
            f"construction; the 20 %-loss figure is the real test."
            + (f" Hardest condition (\u2018{_hard['name']}\u2019): "
               f"{_hard['hit1_pct']:.0f} %." if _hard else ""))

st.info("**How to read this app:** every AI output is a first draft with a "
        "measured error rate — never ground truth. Each AI-generated claim "
        "is verified against the structured tag register, and everything "
        "deterministic (extraction, graphs, worksheets) works without an "
        "AI key.")

st.subheader("Three ways in")
a, b, c = st.columns(3)
with a:
    st.markdown("**🆚 The format argument in two minutes**  \n"
                "The same drawing from PDF and from DEXPI, side by side: "
                "tags are text — topology is not.")
    _go(PAGES["dexpi_vs_pdf"], "🆚 Open DEXPI vs PDF", "go_dexpi")
with b:
    st.markdown("**⚠️ AI-assisted HAZOP**  \n"
                "A pre-filled worksheet grounded in extracted tags, vision "
                "reading of the drawing itself, editing and "
                "Excel export.")
    _go(PAGES["hazop"], "⚠️ Open HAZOP preparation", "go_hazop")
with c:
    st.markdown("**🎛️ Alarm shower in the control room**  \n"
                "A hidden failure raises 100+ simultaneous alarms across "
                "drawings — find the source with the assistant's help.")
    _go(PAGES["kontrollrom"], "🎛️ Open the control-room scenario", "go_kr")

st.markdown("Recurring pattern: *same tools, better data, better answers* "
            "— and *AI proposes, the structured register verifies*.")

with st.expander("🩺 Demo readiness (check before presenting)"):
    import os
    from pathlib import Path as _P
    from config import PID_DIR

    def _row(ok, label, hint):
        st.write(("✅ " if ok else "⚠️ ") + label + ("" if ok else f" — {hint}"))

    _raw = _P(PID_DIR).parent
    _dexpi = list(_raw.rglob("*.DGN.xml"))
    _row(len(_dexpi) >= 1, f"DEXPI files found: {len(_dexpi)}",
         "put the XMLs under data/raw/")
    _pdfs = list(_P(PID_DIR).glob("*.PDF")) + list(_P(PID_DIR).glob("*.pdf"))
    _row(len(_pdfs) >= 1, f"P&ID PDFs found: {len(_pdfs)}",
         "put the PDFs in data/raw/P&ID/")
    _row(bool(os.getenv("GEMINI_API_KEY")), "GEMINI_API_KEY set",
         "AI surfaces are hidden without it; everything deterministic still works")
    try:
        import pypdfium2  # noqa: F401
        _row(True, "pypdfium2 (rasterisation) installed", "")
    except Exception:  # noqa: BLE001
        _row(False, "pypdfium2 missing", "vision/markers need it: uv sync")
    _vc = list(_P("reports/vision_cache").glob("*.json"))
    _row(len(_vc) >= 1, f"Vision cache: {len(_vc)} drawing(s) warm",
         "run python src/ai/warm_vision_cache.py <pdf> the evening before")
    _ac = list(_P("reports/ai_cache").glob("*.json"))
    _row(len(_ac) >= 1, f"AI cache (rewrites/Q&A): {len(_ac)} entries",
         "generate in the app with demo mode on, and the demo is offline-safe")
    _pc = _P("data/processed/dexpi_tags.csv")
    _row(_pc.exists(), "data/processed generated (the NeqSim link)",
         "run analysis/parse_dexpi_data.py")

st.caption("Public Huldra data and synthetic alarms/sensor values only. "
           "Prototype — see the README and report for limitations, method "
           "and pilot proposal.")