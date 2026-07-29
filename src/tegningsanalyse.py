"""
src/tegningsanalyse.py
=====================================================================
Streamlit page: select a P&ID, let the symbol model (gatevalve-ai) read it,
and see which components the drawing contains — with symbol images so
the user learns the symbols, and the proof image showing WHERE the findings are.

Located in src/ next to app.py and registered by st.navigation there
(NOT in a pages/ folder). Add to app.py:

    st.Page("tegningsanalyse.py", title="Drawing analysis", icon="🔍"),

Runs gatevalve-ai/classify_drawing.py as a subprocess; model and templates
are fetched from the gatevalve-ai/ folder in the project root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tegningsvisning import save_run_meta, view_panel   # noqa: E402
from tegningslikhet import similarity_panel             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATEVALVE_DIR = ROOT / "gatevalve-ai"
RESULTS_DIR = GATEVALVE_DIR / "results"
DEFAULT_MODEL = "model_cnn.pt"

try:
    from config import PID_DIR
except Exception:                                                  # noqa: BLE001
    PID_DIR = ROOT / "data" / "raw" / "P&ID"

# class -> (display name, symbol file in gatevalve-ai, color in the proof image)
CLASS_INFO = {
    "gate_open":       ("Gate valve, open",   "gate_open.png",      "green"),
    "gate_closed":     ("Gate valve, closed", "gate_closed.png",    "red"),
    "ball_valve":      ("Ball valve",         "cand_ball.png",      "orange"),
    "ball_open":       ("Ball valve, open",   "cand_ball.png",      "orange"),
    "ball_closed":     ("Ball valve, closed", "cand_ball_closed.png", "dark orange"),
    "globe_valve":     ("Globe valve",        "cand_globe.png",     "purple"),
    "check_valve":     ("Check valve",        "cand_check.png",     "turquoise"),
    "butterfly_valve": ("Butterfly valve",    "cand_butterfly.png", "pink"),
    "reducer":         ("Reducer",            "cand_reducer.png",   "brown"),
    "other_valve":     ("Other valves",       None,                 "blue"),
}
COLOR_LEGEND = ("green = gate open · red = gate closed · orange = ball open · "
                "dark orange = ball closed · purple = globe · turquoise = check · "
                "pink = butterfly · brown = reducer · blue = other valves")


# ------------------------------------------------------------ helpers (UI-free)
def list_drawings(root: Path) -> list[Path]:
    return sorted(p for p in Path(root).rglob("*") if p.suffix.lower() == ".pdf")


def result_paths(drawing: Path):
    stem = drawing.stem
    return (RESULTS_DIR / f"{stem}_verdict.json",
            RESULTS_DIR / f"{stem}_proof.png",
            RESULTS_DIR / f"{stem}_detections.json")


def run_classifier(drawing: Path, model: str, dpi: int, only_gates: bool,
                   timeout_s: int = 900):
    cmd = [sys.executable, str(GATEVALVE_DIR / "classify_drawing.py"),
           str(drawing), "--dpi", str(dpi), "--model", model,
           "--out-dir", "results", "--dump-detections"]
    if only_gates:
        cmd.append("--only-gates")
    r = subprocess.run(cmd, cwd=GATEVALVE_DIR, capture_output=True,
                       text=True, timeout=timeout_s)
    return r.returncode == 0, (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")


def load_verdict(verdict_path: Path) -> list[dict]:
    v = json.loads(verdict_path.read_text(encoding="utf-8"))
    rows = []
    for cls, info in v.items():
        if not isinstance(info, dict):
            continue
        confident = info.get("confident", info.get("count", 0))
        possible = info.get("possible", info.get("weak_count", 0))
        if confident or possible:
            name, symfile, color = CLASS_INFO.get(cls, (cls, None, ""))
            rows.append({"cls": cls, "name": name, "symbol": symfile,
                         "color": color, "confident": confident,
                         "possible": possible, "best": info.get("best_conf", 0.0)})
    order = list(CLASS_INFO)
    rows.sort(key=lambda r: order.index(r["cls"]) if r["cls"] in order else 99)
    return rows


def symbol_image(symfile: str | None, height: int = 56):
    if not symfile:
        return None
    p = GATEVALVE_DIR / symfile
    if not p.exists():
        return None
    arr = 255 - np.array(Image.open(p).convert("L"))   # black on white
    im = Image.fromarray(arr)
    w = max(int(im.width * height / im.height), 1)
    im = im.resize((w, height), Image.NEAREST)
    canvas = Image.new("L", (max(w + 12, 90), height + 12), 255)
    canvas.paste(im, ((canvas.width - w) // 2, 6))
    return canvas


# ------------------------------------------------------------------- page
from ui import page_header
page_header("Drawing analysis",
            "The symbol model (gatevalve-ai) reads the P&ID")
st.caption("Select a P&ID, let the symbol model read it, and see which "
           "components it contains — and where. A draft for "
           "engineering review, not an authoritative source.")

if not GATEVALVE_DIR.exists():
    st.error(f"Could not find gatevalve-ai/ in the project root ({GATEVALVE_DIR}).")
    st.stop()
drawings = list_drawings(PID_DIR)
if not drawings:
    st.error(f"Found no PDFs under {PID_DIR}.")
    st.stop()

c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    from incident_context import incident_banner, match_index
    _inc = incident_banner("drawing preselected from the incident",
                           key="tegn")
    choice = st.selectbox(
        "Drawing", drawings, format_func=lambda p: p.name,
        index=match_index([p.name for p in drawings],
                          *((_inc.get("drawings") or []) if _inc else []),
                          _inc and _inc.get("system")))
with c2:
    dpi = st.number_input("DPI", 100, 300, 200, step=50)
with c3:
    only_gates = st.checkbox("Only gate valves", value=False)
reuse = st.checkbox("Use previous result if it exists", value=True)

verdict_p, proof_p, det_p = result_paths(choice)
have_cached = verdict_p.exists() and proof_p.exists()

if st.button("Analyze drawing", type="primary"):
    if reuse and have_cached:
        st.info("Using existing result (uncheck above to rerun).")
    else:
        with st.spinner("The model is reading the drawing … (~1 minute)"):
            try:
                ok, log = run_classifier(choice, DEFAULT_MODEL, int(dpi),
                                         only_gates)
            except subprocess.TimeoutExpired:
                st.error("Timeout — try a lower DPI.")
                st.stop()
        with st.expander("Execution log"):
            st.code(log or "(empty)")
        if not ok or not verdict_p.exists():
            st.error("Classification failed — see log above.")
            st.stop()
        # remember the DPI: bbox_orig is in pixels, so the overlay only
        # lines up if the original is re-rendered at the same scale
        save_run_meta(RESULTS_DIR, choice, int(dpi))
    st.session_state["analyzed"] = str(choice)

if st.session_state.get("analyzed") == str(choice) and verdict_p.exists():
    rows = load_verdict(verdict_p)
    st.subheader("The drawing contains")
    if not rows:
        st.write("No components found above thresholds.")
    for r in rows:
        ci, ct = st.columns([1, 5])
        with ci:
            im = symbol_image(r["symbol"])
            if im is not None:
                st.image(im)
        with ct:
            extra = f" + {r['possible']} possible" if r["possible"] else ""
            st.markdown(
                f"**{r['name']}** — {r['confident']} confident{extra}  \n"
                f"<span style='color:gray'>best confidence {r['best']:.2f} "
                f"· shown in {r['color']} on the drawing</span>",
                unsafe_allow_html=True)
    st.caption("«Confident» = above the model's calibrated threshold (thick box). "
               "«Possible» = 0.55 threshold (thin box) — checklist for humans.")

    st.subheader("Where on the drawing?")
    view_panel(choice, proof_p, det_p, RESULTS_DIR,
               fallback_dpi=int(dpi), class_info=CLASS_INFO,
               color_legend=COLOR_LEGEND)

    with st.expander("🔤 Line codes → Model Broker attributes"):
        try:
            sys.path.insert(0, str(GATEVALVE_DIR))
            import line_labels as LL
            labels, sizes = LL.extract_line_labels(str(choice), int(dpi))
            st.write(f"{len(labels)} line codes and {len(sizes)} "
                     f"size markers found in the text layer.")
            if det_p.exists() and labels:
                dets = json.loads(det_p.read_text(encoding="utf-8"))
                att = LL.attach_to_detections(labels, sizes, dets)
                st.dataframe(
                    [{"Class": CLASS_INFO.get(a["cls"], (a["cls"],))[0],
                      "Confidence": a.get("conf"),
                      "Model Broker attributes": LL.broker_hint(a),
                      "Distance (px)": a.get("line_dist_px")}
                     for a in att],
                    use_container_width=True)
                st.caption("The fluid-code table is a STARTER TABLE (codes "
                           "marked «antatt» must be confirmed against the "
                           "line numbering standard). The attributes are "
                           "suggested Model Broker configuration: size, "
                           "system, fluid and piping class.")
            elif labels:
                for lab in labels[:12]:
                    st.write(f'`{lab["raw"]}` — system {lab["system"]}, '
                             f'DN {lab["size_in"]:g}", {lab["fluid"]} '
                             f'({lab["fluid_desc"]}), class {lab["spec"]}')
        except Exception as e:  # noqa: BLE001
            st.warning(f"Line-code interpretation unavailable: {e}")

    if det_p.exists():
        with st.expander("All findings (table)"):
            dets = json.loads(det_p.read_text(encoding="utf-8"))
            st.dataframe(
                [{"Class": CLASS_INFO.get(d["cls"], (d["cls"],))[0],
                  "Confidence": d.get("conf"),
                  "Tier": d.get("tier", "confident"),
                  "x": d["bbox_orig"][0], "y": d["bbox_orig"][1]}
                 for d in dets],
                use_container_width=True)

    # Which other analysed drawings resemble this one, by component profile.
    # Sits at the end of the results block so it appears for every analysed
    # drawing — including ones with no detections file, where the panel says
    # so rather than silently vanishing.
    st.divider()
    similarity_panel(choice, RESULTS_DIR, CLASS_INFO)

elif have_cached:
    st.caption("A previous result exists for this drawing — "
               "press «Analyze drawing» to show it.")