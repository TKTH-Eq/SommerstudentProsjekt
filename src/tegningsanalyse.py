"""
src/tegningsanalyse.py
=====================================================================
Streamlit-side: velg en P&ID, la symbolmodellen (gatevalve-ai) lese den,
og se hvilke komponenter tegningen inneholder — med symbolbilder så
brukeren laerer symbolene, og proof-bildet som viser HVOR funnene er.

Ligger i src/ ved siden av app.py og registreres av st.navigation der
(IKKE i en pages/-mappe). Legg til i app.py:

    st.Page("tegningsanalyse.py", title="Tegningsanalyse", icon="🔍"),

Kjorer gatevalve-ai/classify_drawing.py som subprocess; modell og maler
hentes fra gatevalve-ai/-mappen i prosjektroten.
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

ROOT = Path(__file__).resolve().parents[1]
GATEVALVE_DIR = ROOT / "gatevalve-ai"
RESULTS_DIR = GATEVALVE_DIR / "results"
DEFAULT_MODEL = "model_cnn.pt"

try:
    from config import PID_DIR
except Exception:                                  # noqa: BLE001
    PID_DIR = ROOT / "data" / "raw" / "P&ID"

# klasse -> (visningsnavn, symbolfil i gatevalve-ai, farge i proof-bildet)
CLASS_INFO = {
    "gate_open":       ("Gate valve, apen",   "gate_open.png",      "gronn"),
    "gate_closed":     ("Gate valve, lukket", "gate_closed.png",    "rod"),
    "ball_valve":      ("Ball valve",         "cand_ball.png",      "oransje"),
    "globe_valve":     ("Globe valve",        "cand_globe.png",     "lilla"),
    "check_valve":     ("Check valve",        "cand_check.png",     "turkis"),
    "butterfly_valve": ("Butterfly valve",    "cand_butterfly.png", "rosa"),
    "reducer":         ("Reducer",            "cand_reducer.png",   "brun"),
    "other_valve":     ("Andre ventiler",     None,                 "bla"),
}
FARGEFORKLARING = ("gronn = gate apen · rod = gate lukket · oransje = ball · "
                   "lilla = globe · turkis = check · rosa = butterfly · "
                   "brun = reducer · bla = andre ventiler")


# ------------------------------------------------------------ helpers (UI-fri)
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
    arr = 255 - np.array(Image.open(p).convert("L"))   # svart pa hvitt
    im = Image.fromarray(arr)
    w = max(int(im.width * height / im.height), 1)
    im = im.resize((w, height), Image.NEAREST)
    canvas = Image.new("L", (max(w + 12, 90), height + 12), 255)
    canvas.paste(im, ((canvas.width - w) // 2, 6))
    return canvas


# ------------------------------------------------------------------- side
from ui import page_header
page_header("Drawing analysis",
            "The symbol model (gatevalve-ai) reads the P&ID")
st.caption("Velg en P&ID, la symbolmodellen lese den, og se hvilke "
           "komponenter den inneholder — og hvor. Et utkast for "
           "ingeniorgjennomgang, ikke en autoritativ kilde.")

if not GATEVALVE_DIR.exists():
    st.error(f"Fant ikke gatevalve-ai/ i prosjektroten ({GATEVALVE_DIR}).")
    st.stop()
drawings = list_drawings(PID_DIR)
if not drawings:
    st.error(f"Fant ingen PDF-er under {PID_DIR}.")
    st.stop()

c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    choice = st.selectbox("Tegning", drawings,
                          format_func=lambda p: p.name)
with c2:
    dpi = st.number_input("DPI", 100, 300, 200, step=50)
with c3:
    only_gates = st.checkbox("Kun gate valves", value=False)
reuse = st.checkbox("Bruk forrige resultat hvis det finnes", value=True)

verdict_p, proof_p, det_p = result_paths(choice)
have_cached = verdict_p.exists() and proof_p.exists()

if st.button("Analyser tegning", type="primary"):
    if reuse and have_cached:
        st.info("Bruker eksisterende resultat (fjern haken over for a "
                "kjore pa nytt).")
    else:
        with st.spinner("Modellen leser tegningen … (~1 minutt)"):
            try:
                ok, log = run_classifier(choice, DEFAULT_MODEL, int(dpi),
                                         only_gates)
            except subprocess.TimeoutExpired:
                st.error("Tidsavbrudd — prov lavere DPI.")
                st.stop()
        with st.expander("Kjoringslogg"):
            st.code(log or "(tom)")
        if not ok or not verdict_p.exists():
            st.error("Klassifiseringen feilet — se loggen over.")
            st.stop()
    st.session_state["analyzed"] = str(choice)

if st.session_state.get("analyzed") == str(choice) and verdict_p.exists():
    rows = load_verdict(verdict_p)
    st.subheader("Tegningen inneholder")
    if not rows:
        st.write("Ingen komponenter funnet over tersklene.")
    for r in rows:
        ci, ct = st.columns([1, 5])
        with ci:
            im = symbol_image(r["symbol"])
            if im is not None:
                st.image(im)
        with ct:
            extra = f" + {r['possible']} mulige" if r["possible"] else ""
            st.markdown(
                f"**{r['name']}** — {r['confident']} sikre{extra}  \n"
                f"<span style='color:gray'>beste konfidens {r['best']:.2f} "
                f"· vises i {r['color']} pa tegningen</span>",
                unsafe_allow_html=True)
    st.caption("«Sikre» = over modellens kalibrerte terskel (tykk boks). "
               "«Mulige» = 0,55–terskel (tynn boks) — sjekkliste for mennesket.")

    st.subheader("Hvor pa tegningen?")
    st.image(str(proof_p), use_container_width=True)
    st.caption("Fargekode: " + FARGEFORKLARING)

    if det_p.exists():
        with st.expander("Alle funn (tabell)"):
            dets = json.loads(det_p.read_text(encoding="utf-8"))
            st.dataframe(
                [{"klasse": CLASS_INFO.get(d["cls"], (d["cls"],))[0],
                  "konfidens": d.get("conf"),
                  "lag": d.get("tier", "sikker"),
                  "x": d["bbox_orig"][0], "y": d["bbox_orig"][1]}
                 for d in dets],
                use_container_width=True)
elif have_cached:
    st.caption("Det finnes et tidligere resultat for denne tegningen — "
               "trykk «Analyser tegning» for a vise det.")