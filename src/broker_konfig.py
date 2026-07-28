"""
src/broker_konfig.py
=====================================================================
Streamlit page: inspect a Model Broker configuration, compare it against the
DEXPI output, and generate an ADDITION to it from what the symbol model found.

Three things happen here, in increasing order of ambition:

  1. Catalogue     — what is in the configuration today: 205 patterns across
                     Symbol, Letter, ConnectionSegment and SheetComponent.
  2. Coverage gap  — which DEXPI classes appear in the output with no pattern
                     targeting them, and which patterns target classes that
                     never appear. Needs no model and no geometry; run it
                     first, it is the cheapest useful thing on this page.
  3. Generation    — detections from gatevalve-ai are used as region selectors,
                     the geometry is read out of the PDF's own vector layer,
                     occurrences are clustered to check they agree, and a
                     pattern is written per class.

Generated patterns land in their own folder, in grey, and disabled below a
confidence threshold. The engineer switches them on in Model Broker as they
check them — the tool's own affordances are the review surface.

Caveat worth repeating in the UI: the geometry step needs a PDF with a vector
layer. Scanned sheets produce nothing, and the page says so rather than
producing an empty pattern.

Located in src/ next to app.py. Add to app.py:

    st.Page("broker_konfig.py", title="Model Broker config", icon="⚙️"),
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.broker_config import (               # noqa: E402
    coverage_gap, generate_from_detections, load_config, pattern_catalogue,
    validate_config, write_config,
)
from analysis.dexpi_properties import class_inventory, load_items  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATEVALVE_DIR = ROOT / "gatevalve-ai"
RESULTS_DIR = GATEVALVE_DIR / "results"

try:
    from config import PID_DIR, RAW_DIR                            # noqa: E402
except Exception:                                                  # noqa: BLE001
    RAW_DIR = ROOT / "data" / "raw"
    PID_DIR = RAW_DIR / "P&ID"

try:
    from ui import page_header                                     # noqa: E402
except Exception:                                                  # noqa: BLE001
    def page_header(title, sub="", **_):
        st.title(title)
        if sub:
            st.caption(sub)

# gatevalve-ai class -> DEXPI class. The one table you must maintain by hand;
# everything else on this page is derived. Keys match CLASS_INFO in
# tegningsanalyse.py, values must exist as Dexpi2 targets in the reference
# configuration or the pattern will have nothing to inherit from.
CLASS_TO_DEXPI = {
    "gate_open": "GateValve",
    "gate_closed": "GateValve",
    "ball_valve": "BallValve",
    "ball_open": "BallValve",
    "ball_closed": "BallValve",
    "globe_valve": "GlobeValve",
    "check_valve": "CheckValve",
    "butterfly_valve": "ButterflyValve",
    "reducer": "PipeReducer",
}

page_header("Model Broker config",
            "What the configuration covers — and a generated addition to it")

cfg_path = st.text_input(
    "Reference configuration (JSON exported from Model Broker)",
    str(ROOT / "data" / "broker" / "Huldra DEXPI P&ID 2.0_configuration.json"))
if not Path(cfg_path).exists():
    st.error("Configuration not found. Export it from Model Broker and point "
             "this field at the file.")
    st.stop()

try:
    config = load_config(cfg_path)
except json.JSONDecodeError as e:
    st.error(f"Could not read the configuration: {e}")
    st.stop()

catalogue = pattern_catalogue(config)
by_type = pd.DataFrame(catalogue)["type"].value_counts()

c = st.columns(5)
c[0].metric("Patterns", len(catalogue))
for i, t in enumerate(["Symbol", "Letter", "ConnectionSegment",
                       "SheetComponent"][:4]):
    c[i + 1].metric(t, int(by_type.get(t, 0)))
st.caption("Only the Symbol patterns are in reach of a symbol detector. "
           "Letter, ConnectionSegment and SheetComponent are text, line and "
           "frame handling — generation covers roughly half the configuration, "
           "and it is the repetitive half.")

tab_cat, tab_gap, tab_gen = st.tabs(
    ["Catalogue", "Coverage gap", "Generate addition"])

# ------------------------------------------------------------------ catalogue
with tab_cat:
    only_symbols = st.checkbox("Symbol patterns only", value=True)
    view = [r for r in catalogue if r["type"] == "Symbol"] if only_symbols \
        else catalogue
    st.dataframe(pd.DataFrame(view)[
        ["name", "type", "folder", "enabled", "dexpi", "primitives",
         "terminals"]],
        use_container_width=True, hide_index=True)
    st.caption("«Primitives» is how many vector curves define the pattern. "
               "A symbol with 65 of them is not something you can infer from "
               "a bounding box — it has to be read out of the drawing.")

# --------------------------------------------------------------- coverage gap
with tab_gap:
    dexpi_src = st.text_input("DEXPI folder", str(RAW_DIR), key="gap_src")
    if not Path(dexpi_src).exists():
        st.info("Point this at the folder holding the DEXPI XML files.")
    else:
        items = load_items(dexpi_src)
        if not items:
            st.info("No DEXPI objects found under that folder.")
        else:
            counts = {r["class"]: r["count"] for r in class_inventory(items)}
            gap = coverage_gap(config, counts)

            g = st.columns(3)
            g[0].metric("Covered and present", len(gap["both"]))
            g[1].metric("Present, no pattern", len(gap["missing"]))
            g[2].metric("Pattern, never present", len(gap["unused"]))

            st.markdown("**Classes in the DEXPI output with no pattern "
                        "targeting them**")
            st.caption("Not automatically an error — several of these come "
                       "from connection and sheet handling rather than from a "
                       "symbol pattern. The ones worth a look are the "
                       "equipment and component classes with a high count.")
            st.dataframe(
                pd.DataFrame([{"class": c, "occurrences": counts.get(c, 0)}
                              for c in gap["missing"]]),
                use_container_width=True, hide_index=True)

            with st.expander("Patterns whose class never appears in the output"):
                st.caption("Either dead weight in the configuration, or "
                           "symbols that only occur on drawings you have not "
                           "run yet. Check before deleting anything.")
                st.write(", ".join(gap["unused"]) or "(none)")

# ----------------------------------------------------------------- generation
with tab_gen:
    st.markdown("**Detections → geometry → patterns**")
    st.caption("The detector says WHERE a symbol is and WHICH class it is. "
               "The geometry is then read from the PDF's vector layer — the "
               "same source every pattern in the reference configuration was "
               "authored from.")

    pdfs = sorted(p for p in Path(PID_DIR).rglob("*")
                  if p.suffix.lower() == ".pdf") if Path(PID_DIR).exists() else []
    if not pdfs:
        st.error(f"Found no PDFs under {PID_DIR}.")
        st.stop()

    drawing = st.selectbox("Drawing", pdfs, format_func=lambda p: p.name)
    det_path = RESULTS_DIR / f"{drawing.stem}_detections.json"
    run_path = RESULTS_DIR / f"{drawing.stem}_run.json"

    if not det_path.exists():
        st.warning("No detections for this drawing yet — run it on the "
                   "Drawing analysis page first.")
        st.stop()

    detections = json.loads(det_path.read_text(encoding="utf-8"))
    dpi = 200
    if run_path.exists():
        try:
            dpi = int(json.loads(run_path.read_text(encoding="utf-8"))["dpi"])
        except Exception:                                          # noqa: BLE001
            pass
    st.caption(f"{len(detections)} detections, analysed at {dpi} DPI. The "
               "geometry lookup uses the same DPI — if it is wrong, the "
               "regions land in the wrong place and nothing is found.")

    o1, o2, o3, o4 = st.columns(4)
    with o1:
        min_conf = st.slider("Minimum confidence", 0.5, 1.0, 0.80, 0.05)
    with o2:
        enable_above = st.slider("Ship enabled above", 0.5, 1.0, 0.95, 0.05)
    with o3:
        max_per_class = st.number_input("Occurrences per class", 3, 40, 12)
    with o4:
        min_prims = st.number_input("Minimum primitives", 1, 20, 3,
                                    help="A symbol built from one or two "
                                         "curves is a line, not a symbol. "
                                         "Below this the geometry reader is "
                                         "assumed to have failed.")

    st.caption("Patterns below the second threshold are written with "
               "`enabled: false`. They appear in Model Broker in their own "
               "grey folder and do nothing until switched on.")

    if st.button("Generate addition", type="primary"):
        with st.spinner("Reading geometry and building patterns …"):
            try:
                result = generate_from_detections(
                    config, detections, drawing, dpi, CLASS_TO_DEXPI,
                    min_conf=min_conf, enable_above=enable_above,
                    max_per_class=int(max_per_class),
                    min_primitives=int(min_prims))
            except ImportError:
                st.error("pdfplumber is needed for the geometry step. "
                         "`pip install pdfplumber`")
                st.stop()

        report = result["report"]
        made = [r for r in report if r["status"] == "mønster laget"]

        r1, r2, r3 = st.columns(3)
        r1.metric("Patterns generated", len(made))
        r2.metric("Shipped enabled", sum(1 for r in made if r.get("enabled")))
        r3.metric("Classes skipped", len(report) - len(made))

        errors = [p for p in result.get("problems", [])
                  if p["severity"] == "feil"]
        if errors:
            st.error(f"{len(errors)} structural errors — do NOT import this "
                     f"file. The reference configuration has zero, so this is "
                     f"an exact bar.")
            st.dataframe(pd.DataFrame(errors), use_container_width=True,
                         hide_index=True)
        else:
            st.success("Structural check passed: no dangling references. "
                       "The reference configuration is the baseline — it also "
                       "has zero.")

        if made:
            st.dataframe(
                pd.DataFrame(made)[["class", "dexpi", "donor", "occurrences",
                                    "clusters", "agreement", "primitives",
                                    "terminals", "best_conf", "enabled",
                                    "detail"]],
                use_container_width=True, hide_index=True)
            st.caption("«Agreement» is the share of occurrences whose geometry "
                       "matched the largest cluster. Below 0.8 the detector "
                       "grouped things that are not the same symbol — the "
                       "pattern is still written, but shipped disabled.")

        skipped = [r for r in report if r["status"] != "mønster laget"]
        if skipped:
            with st.expander(f"{len(skipped)} classes produced nothing"):
                st.dataframe(pd.DataFrame(skipped)[["class", "status", "detail"]],
                             use_container_width=True, hide_index=True)

        if made and not errors:
            out = ROOT / "data" / "broker" / \
                f"{Path(cfg_path).stem}__plus_{drawing.stem}.json"
            write_config(result["config"], out)
            st.success(f"Written to `{out}`")
            st.download_button(
                "Download configuration",
                data=json.dumps(result["config"], indent=1,
                                ensure_ascii=False).encode("utf-8"),
                file_name=out.name, mime="application/json")
            st.caption("Nothing existing was modified: version, "
                       "patternTemplate, targetDefinitions and every hand-made "
                       "pattern come through unchanged. Import it into Model "
                       "Broker and the new folder appears alongside the old "
                       "ones.")
        elif errors:
            st.info("Nothing written — fix the structural errors first.")
        else:
            st.info("No patterns were produced. If the report says «for lite "
                    "geometri», the detector worked and the geometry reader "
                    "did not: check the DPI, the y-axis direction in "
                    "extract_region_geometry, and whether the symbols are "
                    "Form XObjects rather than page-level curves.")

st.divider()
st.caption("A draft for engineering review. A generated pattern that matches "
           "the wrong thing is worse than a missing one, which is why nothing "
           "ships enabled unless both the confidence and the geometry "
           "agreement clear their thresholds.")