"""
src/hjem.py  —  landing page

First thing a stakeholder sees: what this is, the honest key numbers, a map
of the app, and three guided paths in. Everything else in the app assumes
context; this page provides it.

ONE RULE GOVERNS THE KPI STRIP: a number is only allowed here if it was
measured against an INDEPENDENT ground truth. Precision/recall qualify —
they are scored against the Semantum DEXPI export, which the extractor
never sees. The control room's root-cause hit rate does NOT: its alarm
showers are generated from the same structural model that is then scored,
so the figure describes the simulation, not the plant. Putting it beside
87 % in the same strip would imply equal standing and read as a claim
about real operations. The scenario is still demonstrated — it is just
presented as a walkthrough, without a number attached.
"""
from __future__ import annotations

import streamlit as st

from nav_pages import PAGES
from ui import page_header

# Plant-model figures, from analysis.plant_model.build_plant_model over
# data/raw (stats: drawings, tags). Held as constants so the landing page
# renders instantly — building the model takes ~9 s. Refresh them from the
# 🏭 Plant overview page, which shows the same stats live.
_DRAWINGS, _TAGS = 17, 885


def _go(page, label: str, key: str):
    """Robust navigasjon: knapp + st.switch_page. Brukes i stedet for
    st.page_link, som er upålitelig sammen med st.navigation i enkelte
    Streamlit-versjoner."""
    if st.button(label, key=key, use_container_width=True):
        st.switch_page(page)


page_header("AI opportunities for P&IDs and SCDs",
            "Summer-student project · Huldra data (public) · "
            "decision input for the Wisting digitalisation",
            kpis=[("PRECISION (PDF)", "87 %"), ("RECALL (PDF)", "55 %"),
                  ("DRAWINGS", str(_DRAWINGS)), ("TAGS", str(_TAGS))])

st.markdown(
    "P&IDs and SCDs are still consumed as drawings and documents. This "
    "app demonstrates what becomes possible when they are treated as "
    "**structured engineering information** instead: automatic extraction, "
    "consistency checking, HAZOP preparation, and control-room decision "
    "support — on real drawings, with measured accuracy.")

st.info("**How to read this app:** every AI output is a first draft with a "
        "measured error rate — never ground truth. Each AI-generated claim "
        "is verified against the structured tag register, and everything "
        "deterministic (extraction, graphs, worksheets) works without an "
        "AI key.")

# ---- three guided paths ----------------------------------------------------
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
                "A hidden failure raises alarms across drawings — find the "
                "source with the assistant's help. A **synthetic scenario** "
                "on the real plant topology.")
    _go(PAGES["kontrollrom"], "🎛️ Open the control-room scenario", "go_kr")

st.markdown("Recurring pattern: *same tools, better data, better answers* "
            "— and *AI proposes, the structured register verifies*.")

st.divider()

# ---- map of the app --------------------------------------------------------
# The sidebar is grouped into these same six sections (see nav_pages.NAV).
# Repeating the map here means a visitor knows what exists before clicking.
st.subheader("What's in here")
st.caption("The sidebar is grouped into the same six sections.")

_m1, _m2, _m3 = st.columns(3)
with _m1:
    st.markdown(
        "**Start**  \nWhat this is, the format argument, and the plant "
        "stitched into one model from shared line numbers.")
    st.markdown(
        "**System analysis**  \nThe same analyses run from PDF extraction "
        "and from DEXPI — KPIs, reconciliation, failure explorer, "
        "dependency graph — plus the tag register and real topology "
        "underneath them.")
with _m2:
    st.markdown(
        "**Safety & quality**  \nHAZOP worksheets grounded in extracted "
        "tags, the same worksheet built from both formats, and a "
        "plant-wide roll-up of the structural rule findings.")
    st.markdown(
        "**Operations**  \nThe control-room assistant, plant-wide Q&A "
        "answered from the graph, drawing search in plain language, "
        "30-second sheet summaries, and the NeqSim link.")
with _m3:
    st.markdown(
        "**Drawings**  \nRead a single sheet with the symbol model, or "
        "try to rebuild a structured model from the PDF alone.")
    st.markdown(
        "**Model Broker**  \nSymbol and configuration work: the tag "
        "decoder, coverage gaps, reference symbols and the variant map. "
        "Deep tooling — three of these need a Model Broker export to run "
        "at all.")

st.divider()

# ---- where AI is used, and in what role ------------------------------------
# The brief asks what AI can do for P&ID/SCD work, so the answer should be
# legible without opening 21 pages. Grouped by ROLE rather than by page,
# because the role is what determines how far you can trust the output —
# and because "AI reads the drawing" and "AI rephrases facts the graph
# computed" are different propositions with different failure modes.
st.subheader("Where AI is used — and in what role")
st.caption("Grouped by the job the model actually does. The role decides how "
           "much can be trusted: a model reading pixels can be wrong about "
           "what is on the sheet; a model rephrasing a computed answer "
           "cannot change the answer.")

_r1, _r2 = st.columns(2)
with _r1:
    st.markdown(
        "**👁️ The model reads the drawing**  \n"
        "Vision: the model looks at the sheet and proposes what it sees. "
        "Highest value, highest risk — so **every tag it names is checked "
        "against the extracted register** and shown as ✅ confirmed or 🟠 "
        "unverified, never silently accepted.  \n"
        "📝 *30-sec summary* · ⚠️ *HAZOP preparation* (vision excerpt and a "
        "second opinion on rule findings) · and the vision reserve inside "
        "extraction itself, which is what makes image-only sheets readable "
        "at all.")
    st.markdown(
        "**🗣️ The model writes, the facts are fixed**  \n"
        "The model turns an already-computed fact set into readable prose. "
        "It cannot introduce a fact, because it is given nothing else — and "
        "a deterministic template renders the same content without a key.  \n"
        "📄 🧭 *System analysis* (operator brief) · 📊 *Compliance dashboard* "
        "(three-sentence plant summary, grounded in the counts above it).")
with _r2:
    st.markdown(
        "**🎯 The model works the edges, the answer is computed**  \n"
        "The model interprets the question on the way in and phrases the "
        "result on the way out. **The answer itself comes from the graph and "
        "the register**, so a hallucinated tag cannot reach it — proposed "
        "tags are resolved against the register before anything is looked "
        "up.  \n"
        "💬 *Plant Q&A* · 🔎 *Find the drawing* (AI only adds synonyms; the "
        "ranking stays deterministic) · 🎛️ *Control-room assistant* "
        "(grounded Q&A over the facts block).")
    st.markdown(
        "**🖥️ Local models, no API and no key**  \n"
        "Classical computer vision and ML on the machine — deterministic, "
        "offline, no data leaves it. This is the channel that reaches the "
        "symbol-only components text extraction can never see.  \n"
        "🔍 *Drawing analysis* · 🧩 *PDF → structure* · ⚙️ 🎯 🧩 *the Model "
        "Broker pages*.")

st.success(
    "**And where there is deliberately none.** 🆚 DEXPI vs PDF · 🏭 Plant "
    "overview · 🏷️ Tag register · 🔗 DEXPI topology · ⚖️ HAZOP PDF vs DEXPI · "
    "🧪 NeqSim · 🧬 DEXPI properties contain no AI at all. They are "
    "measurement and structure — the backbone every AI page above is checked "
    "against. The pages carrying the core format argument are the ones with "
    "no model in them.")

st.divider()

# ---- provenance of every number on this page -------------------------------
with st.expander("📐 How the numbers are measured — and what is deliberately not measured"):
    st.markdown(
        "- **Precision 87 % / recall 55 % (PDF extraction):** measured against "
        "independent DEXPI ground truth over 16 drawings; see `Results.md` "
        "for method. The recall gap is mostly tags drawn as symbols — "
        "information text extraction can never reach. That is the argument "
        "for machine-readable deliverables.\n"
        f"- **{_DRAWINGS} drawings / {_TAGS} tags:** every DEXPI file "
        "stitched into one graph via shared line numbers. Shown live on the "
        "🏭 Plant overview page.")
    st.markdown(
        "**No hit rate is quoted for the control room, on purpose.** The "
        "alarm showers in that scenario are *generated* from the same "
        "structural model the assistant then reasons over, and the alarm "
        "times and process values are synthetic throughout. A percentage "
        "measured that way describes the simulation, not the plant — "
        "quoting it beside the extraction figures would imply the two were "
        "established the same way. The scenario demonstrates the "
        "*workflow*; what it is worth operationally is a question for a "
        "pilot against a real alarm feed, not for this page. The evaluation "
        "harness and its numbers live in `reports/eval_root_cause.json` and "
        "the report, where the synthetic setup is stated alongside them.")

with st.expander("🩺 Demo readiness (check before presenting)"):
    import os
    from config import PID_DIR, ROOT, REPORTS, DATA

    def _row(ok, label, hint):
        st.write(("✅ " if ok else "⚠️ ") + label + ("" if ok else f" — {hint}"))

    _dexpi = list(DATA.rglob("*.DGN.xml"))
    _row(len(_dexpi) >= 1, f"DEXPI files found: {len(_dexpi)}",
         "put the XMLs under data/raw/")
    _pdfs = list(PID_DIR.glob("*.PDF")) + list(PID_DIR.glob("*.pdf"))
    _row(len(_pdfs) >= 1, f"P&ID PDFs found: {len(_pdfs)}",
         "put the PDFs in data/raw/P&ID/")
    _row(bool(os.getenv("GEMINI_API_KEY")), "GEMINI_API_KEY set",
         "AI surfaces are hidden without it; everything deterministic still works")
    try:
        import pypdfium2  # noqa: F401
        _row(True, "pypdfium2 (rasterisation) installed", "")
    except Exception:  # noqa: BLE001
        _row(False, "pypdfium2 missing", "vision/markers need it: uv sync")
    # Absolute paths: these checks used to be relative to the working
    # directory, so running streamlit from anywhere but the repo root
    # reported false warnings.
    _vc = list((REPORTS / "vision_cache").glob("*.json"))
    _row(len(_vc) >= 1, f"Vision cache: {len(_vc)} drawing(s) warm",
         "run python src/ai/warm_vision_cache.py <pdf> the evening before")
    _ac = list((REPORTS / "ai_cache").glob("*.json"))
    _row(len(_ac) >= 1, f"AI cache (rewrites/Q&A): {len(_ac)} entries",
         "generate in the app with demo mode on, and the demo is offline-safe")
    _pc = ROOT / "data" / "processed" / "dexpi_tags.csv"
    _row(_pc.exists(), "data/processed generated (the NeqSim link)",
         "run analysis/parse_dexpi_data.py")

st.caption("Public Huldra data only. All alarm and sensor values in the "
           "demonstrations are synthetic. Prototype — see the README and "
           "report for limitations, method and pilot proposal.")
